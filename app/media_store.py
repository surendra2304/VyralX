"""Media warehouse backed by the dedicated VyralX media database.

VyralX uses two Oracle databases on purpose:

* the FRIDAY Universe database holds *application* state (projects, sources,
  assets, render jobs, publish jobs, metrics) under the ``VYRALX`` user;
* the VyralX media database holds *media* state: every file that is downloaded,
  edited or uploaded, with size, checksum and probe metadata, under the
  ``VYRALX_MEDIA`` user.

The warehouse is a catalogue, not a blob store. Files still live on the media
and render volumes; this module records what exists so that duplicate downloads
and re-renders are detectable without walking the filesystem.

Database outages must never lose a render or a publish, so recording is
best-effort: callers get ``None`` and an ERROR log line instead of an exception.
Startup, however, fails closed when no media database is configured.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Identity,
    Index,
    Integer,
    String,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings

log = logging.getLogger("vyralx.media_store")

DOWNLOAD = "DOWNLOAD"
EDIT = "EDIT"
UPLOAD = "UPLOAD"
MEDIA_KINDS: tuple[str, ...] = (DOWNLOAD, EDIT, UPLOAD)

_engine_lock = Lock()
_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_initialised = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaBase(DeclarativeBase):
    pass


class MediaFile(MediaBase):
    """One physical media artefact that VyralX created or ingested."""

    __tablename__ = "media_files"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    file_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # sha1(kind + '\0' + path) so the uniqueness guard fits an Oracle index.
    path_key: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    storage_path: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    project_key: Mapped[str] = mapped_column(String(120), default="", index=True)
    render_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publish_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_ref: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(40), default="present")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


Index("ix_media_files_kind_created", MediaFile.kind, MediaFile.created_at)
Index("ix_media_files_project_kind", MediaFile.project_key, MediaFile.kind)


def media_backend_url() -> str:
    return (get_settings().media_database_url or "").strip()


def is_configured() -> bool:
    return bool(media_backend_url())


def _normalise_url(url: str) -> str:
    if url.startswith("oracle+oracledb_async://"):
        return "oracle+oracledb://" + url[len("oracle+oracledb_async://"):]
    return url


def get_engine() -> Engine | None:
    """Return the media engine, or None when no media database is configured."""

    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        url = media_backend_url()
        if not url:
            return None
        normalised = _normalise_url(url)
        if normalised.startswith("sqlite"):
            if get_settings().app_env.lower() != "development":
                raise RuntimeError(
                    "MEDIA_DATABASE_URL must point at Oracle; SQLite is not a supported "
                    "media backend outside development"
                )
            log.warning("Media warehouse is using a development SQLite file; not a production backend")
            _engine = create_engine(normalised, pool_pre_ping=True)
            return _engine
        _engine = create_engine(
            normalised,
            pool_size=3,
            max_overflow=5,
            pool_recycle=1800,
            pool_pre_ping=True,
            pool_timeout=30,
        )
        return _engine


def get_session() -> Session | None:
    global _session_factory
    engine = get_engine()
    if engine is None:
        return None
    if _session_factory is None:
        with _engine_lock:
            if _session_factory is None:
                _session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return _session_factory()


def bootstrap_media_schema() -> dict[str, Any]:
    """Create the warehouse table in the media schema. Idempotent."""

    global _initialised
    engine = get_engine()
    if engine is None:
        return {"configured": False, "created": False, "tables": []}
    if _initialised:
        return {"configured": True, "created": True, "tables": [MediaFile.__tablename__]}
    try:
        MediaBase.metadata.create_all(bind=engine)
        _initialised = True
        log.info(
            "Media warehouse ready dialect=%s url=%s",
            engine.dialect.name,
            engine.url.render_as_string(hide_password=True),
        )
        return {"configured": True, "created": True, "tables": [MediaFile.__tablename__]}
    except Exception as exc:  # pragma: no cover - depends on live database
        log.error("Media warehouse bootstrap failed: %s: %s", type(exc).__name__, exc)
        raise RuntimeError(f"Media warehouse schema bootstrap failed: {exc}") from exc


def media_warehouse_status() -> dict[str, Any]:
    """Readiness receipt for ``/ready`` without leaking credentials."""

    engine = get_engine()
    if engine is None:
        return {"configured": False, "connected": False, "backend": None, "tables_found": []}
    receipt: dict[str, Any] = {
        "configured": True,
        "backend": engine.dialect.name,
        "url": engine.url.render_as_string(hide_password=True),
        "connected": False,
        "tables_found": [],
    }
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM DUAL") if engine.dialect.name == "oracle" else text("SELECT 1"))
        receipt["connected"] = True
        receipt["tables_found"] = [
            name for name in inspect(engine).get_table_names() if name.lower() == MediaFile.__tablename__
        ]
    except Exception as exc:  # pragma: no cover - depends on live database
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    return receipt


def _path_key(kind: str, storage_path: str) -> str:
    return hashlib.sha1(f"{kind}\x00{storage_path}".encode("utf-8")).hexdigest()


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def record_media_file(
    kind: str,
    storage_path: str | Path,
    *,
    project_key: str = "",
    render_job_id: int | None = None,
    publish_job_id: int | None = None,
    source_ref: str = "",
    mime_type: str = "",
    duration_seconds: float = 0.0,
    width: int = 0,
    height: int = 0,
    status: str = "present",
    checksum: bool = True,
) -> dict[str, Any] | None:
    """Record or refresh one media artefact. Never raises for runtime callers."""

    if kind not in MEDIA_KINDS:
        raise ValueError(f"unknown media kind {kind!r}; expected one of {MEDIA_KINDS}")
    session = get_session()
    if session is None:
        return None
    path = Path(storage_path)
    sha256 = ""
    size = 0
    try:
        if checksum and path.is_file():
            sha256, size = hash_file(path)
        elif path.is_file():
            size = path.stat().st_size
    except OSError as exc:
        log.warning("Media checksum skipped for %s: %s", path, exc)
    stored_path = str(path)[:1000]
    now = _utcnow()
    values = {
        "kind": kind,
        "storage_path": stored_path,
        "sha256": sha256,
        "size_bytes": size,
        "mime_type": mime_type[:120],
        "duration_seconds": float(duration_seconds or 0.0),
        "width": int(width or 0),
        "height": int(height or 0),
        "project_key": (project_key or "")[:120],
        "render_job_id": render_job_id,
        "publish_job_id": publish_job_id,
        "source_ref": (source_ref or "")[:500],
        "status": status[:40],
        "updated_at": now,
    }
    path_key = _path_key(kind, stored_path)
    try:
        row = session.scalars(select(MediaFile).where(MediaFile.path_key == path_key)).first()
        if row is None:
            row = MediaFile(
                file_key=uuid4().hex,
                path_key=path_key,
                created_at=now,
                **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.commit()
        return {
            "file_key": row.file_key,
            "kind": row.kind,
            "storage_path": row.storage_path,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
            "status": row.status,
        }
    except Exception as exc:  # pragma: no cover - depends on live database
        session.rollback()
        log.error("Media warehouse write failed kind=%s path=%s: %s: %s", kind, stored_path, type(exc).__name__, exc)
        return None
    finally:
        session.close()


def list_media_files(
    *,
    kind: str | None = None,
    project_key: str | None = None,
    sha256: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Read back warehouse rows, newest first."""

    session = get_session()
    if session is None:
        return []
    bound = max(1, min(int(limit), 500))
    try:
        statement = select(MediaFile).order_by(MediaFile.id.desc())
        if kind:
            statement = statement.where(MediaFile.kind == kind)
        if project_key:
            statement = statement.where(MediaFile.project_key == project_key)
        if sha256:
            statement = statement.where(MediaFile.sha256 == sha256)
        if session.bind is not None and session.bind.dialect.name == "oracle":
            statement = statement.fetch(bound)
        else:
            statement = statement.limit(bound)
        rows = session.scalars(statement).all()
        return [
            {
                "file_key": row.file_key,
                "kind": row.kind,
                "storage_path": row.storage_path,
                "sha256": row.sha256,
                "size_bytes": row.size_bytes,
                "project_key": row.project_key,
                "status": row.status,
            }
            for row in rows
        ]
    except Exception as exc:  # pragma: no cover - depends on live database
        log.error("Media warehouse read failed: %s: %s", type(exc).__name__, exc)
        return []
    finally:
        session.close()


def media_warehouse_summary() -> dict[str, Any]:
    """Counts per kind for operational dashboards."""

    session = get_session()
    if session is None:
        return {"configured": False, "counts": {}}
    try:
        counts: dict[str, int] = {}
        for kind in MEDIA_KINDS:
            row = session.execute(
                text("SELECT COUNT(*) FROM media_files WHERE kind = :kind"), {"kind": kind}
            ).scalar()
            counts[kind] = int(row or 0)
        return {"configured": True, "counts": counts}
    except Exception as exc:  # pragma: no cover - depends on live database
        log.error("Media warehouse summary failed: %s: %s", type(exc).__name__, exc)
        return {"configured": True, "counts": {}, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        session.close()


def record_many(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Convenience wrapper used by render and publish paths."""

    return [record_media_file(**row) for row in rows]

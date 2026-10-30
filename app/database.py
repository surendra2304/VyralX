from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


logger = logging.getLogger(__name__)

PROVISIONED_TABLES: tuple[str, ...] = (
    "agent_tasks",
    "assets",
    "content_packs",
    "publish_jobs",
    "render_jobs",
    "sources",
    "video_metrics",
    "video_projects",
)


from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import JSON

@compiles(JSON, "oracle")
def _compile_json_oracle(type_, compiler, **kw):
    return "JSON"

class Base(DeclarativeBase):
    pass


def _mask_url_password(url: str) -> str:
    """Mask credentials in database URLs for logging and diagnostic receipts."""
    try:
        parsed = urlsplit(url)
        if parsed.password:
            netloc = f"{parsed.username or ''}:***@{parsed.hostname or ''}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return url


def make_engine(url: str | None = None) -> Engine:
    database_url = url or get_settings().resolved_database_url()
    if database_url.startswith("oracle+oracledb_async://"):
        database_url = "oracle+oracledb://" + database_url[len("oracle+oracledb_async://"):]
    if database_url.startswith("sqlite"):
        kwargs = {"check_same_thread": False}
        return create_engine(database_url, connect_args=kwargs, pool_pre_ping=True)

    # Normalize postgresql:// and postgres:// to postgresql+psycopg2:// for psycopg2-binary compatibility
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg2://" + database_url[13:]
    elif database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg2://" + database_url[11:]

    # Pool configuration for the Oracle Autonomous Database (and any other
    # network database used by a developer): keep connections warm but recycle
    # them well inside ADB's idle timeout.
    engine_kwargs: dict[str, Any] = {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
        "pool_timeout": 30,
    }
    return create_engine(database_url, **engine_kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_database_connection(target_engine: Engine | None = None) -> dict[str, Any]:
    """Verify connectivity and check the presence of provisioned tables."""
    active_engine = target_engine or engine
    receipt: dict[str, Any] = {
        "connected": False,
        "dialect": active_engine.dialect.name,
        "url": _mask_url_password(str(active_engine.url)),
        "tables_found": [],
        "tables_missing": [],
        "verified": False,
    }
    try:
        with active_engine.connect() as conn:
            if active_engine.dialect.name == "oracle":
                conn.execute(text("SELECT 1 FROM DUAL"))
            else:
                conn.execute(text("SELECT 1"))
        receipt["connected"] = True
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        return receipt

    try:
        inspector = inspect(active_engine)
        table_names = set(inspector.get_table_names())
        receipt["tables_found"] = sorted(t for t in PROVISIONED_TABLES if t in table_names)
        receipt["tables_missing"] = sorted(t for t in PROVISIONED_TABLES if t not in table_names)
        receipt["verified"] = len(receipt["tables_missing"]) == 0
    except Exception as exc:
        receipt["error"] = f"Inspector error: {type(exc).__name__}: {exc}"
    return receipt


def verify_persistence(db: Session | None = None) -> dict[str, Any]:
    """Verify durable persistence across video_projects, render_jobs, and publish_jobs."""
    from app.models import Asset, PublishJob, RenderJob, VideoProject, utcnow

    report: dict[str, Any] = {
        "project_persisted": False,
        "render_job_persisted": False,
        "publish_job_persisted": False,
        "verified": False,
    }
    session = db if db is not None else SessionLocal()
    owns_session = db is None

    test_key = f"verify-persistence-{uuid4().hex[:12]}"
    created_project_id: int | None = None
    created_asset_id: int | None = None
    created_render_id: int | None = None
    created_publish_id: int | None = None

    try:
        # 1. Create and persist video_projects record
        project = VideoProject(
            project_key=test_key,
            topic="Persistence Verification Test",
            video_format="shorts",
            status="queued",
            target_seconds=30,
        )
        session.add(project)
        session.flush()
        created_project_id = project.id

        # 2. Create asset record to link render and publish jobs
        asset = Asset(
            title=f"Asset for {test_key}",
            file_path="/app/media/verify_test.mp4",
            duration_seconds=30.0,
            width=1080,
            height=1920,
            rights_verified=True,
        )
        session.add(asset)
        session.flush()
        created_asset_id = asset.id

        # 3. Create and persist render_jobs record linked to project
        render_job = RenderJob(
            asset_id=created_asset_id,
            preset="shorts",
            status="completed",
            output_path="/app/renders/verify_test.mp4",
            project_id=created_project_id,
            started_at=utcnow(),
            completed_at=utcnow(),
        )
        session.add(render_job)
        session.flush()
        created_render_id = render_job.id

        # 4. Create and persist publish_jobs record linked to asset and render_job
        publish_job = PublishJob(
            asset_id=created_asset_id,
            render_job_id=created_render_id,
            title="Verification Publish Job",
            privacy_status="private",
            status="pending_approval",
        )
        session.add(publish_job)
        session.commit()
        created_publish_id = publish_job.id

        # 5. Verify records survive commit and can be read back in a fresh query
        project_reloaded = session.scalar(
            select(VideoProject).where(VideoProject.id == created_project_id)
        )
        if project_reloaded is not None and project_reloaded.project_key == test_key:
            report["project_persisted"] = True

        render_reloaded = session.scalar(
            select(RenderJob).where(RenderJob.id == created_render_id)
        )
        if render_reloaded is not None and render_reloaded.project_id == created_project_id:
            report["render_job_persisted"] = True

        publish_reloaded = session.scalar(
            select(PublishJob).where(PublishJob.id == created_publish_id)
        )
        if publish_reloaded is not None and publish_reloaded.render_job_id == created_render_id:
            report["publish_job_persisted"] = True

        report["verified"] = (
            report["project_persisted"]
            and report["render_job_persisted"]
            and report["publish_job_persisted"]
        )
    finally:
        # Clean up test rows
        try:
            if created_publish_id is not None:
                p_row = session.get(PublishJob, created_publish_id)
                if p_row is not None:
                    session.delete(p_row)
            if created_render_id is not None:
                r_row = session.get(RenderJob, created_render_id)
                if r_row is not None:
                    session.delete(r_row)
            if created_asset_id is not None:
                a_row = session.get(Asset, created_asset_id)
                if a_row is not None:
                    session.delete(a_row)
            if created_project_id is not None:
                pr_row = session.get(VideoProject, created_project_id)
                if pr_row is not None:
                    session.delete(pr_row)
            session.commit()
        except Exception as exc:
            logger.warning("Error cleaning up verification records: %s", exc)
            session.rollback()
        if owns_session:
            session.close()

    return report

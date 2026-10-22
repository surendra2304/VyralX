"""Tests for PostgreSQL production database configuration, connection pooling, and persistence."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from app.database import (
    PROVISIONED_TABLES,
    _mask_url_password,
    get_db,
    make_engine,
    verify_database_connection,
    verify_persistence,
)


def test_mask_url_password():
    url = "postgresql://vyralx_user:lFvCakEtqlmoegjyEQUOlfAS@dokploy-postgres:5432/vyralx_db"
    masked = _mask_url_password(url)
    assert "lFvCakEtqlmoegjyEQUOlfAS" not in masked
    assert "vyralx_user:***@dokploy-postgres:5432/vyralx_db" in masked

    sqlite_url = "sqlite:///./data/vyralx.db"
    assert _mask_url_password(sqlite_url) == sqlite_url


def test_make_engine_postgresql_configuration():
    pg_url = "postgresql://vyralx_user:secret@dokploy-postgres:5432/vyralx_db"
    mock_dbapi_module = MagicMock(paramstyle="pyformat", __version__="2.9.10")

    def mock_dbapi():
        return mock_dbapi_module

    with patch("sqlalchemy.dialects.postgresql.psycopg2.PGDialect_psycopg2.import_dbapi", mock_dbapi):
        engine = make_engine(pg_url)
        assert isinstance(engine, Engine)
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg2"
        assert isinstance(engine.pool, QueuePool)
        # Check pool size and overflow bounds
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10
        assert engine.pool._recycle == 1800
        assert engine.pool._timeout == 30


def test_make_engine_sqlite_configuration():
    sqlite_url = "sqlite:///:memory:"
    engine = make_engine(sqlite_url)
    assert isinstance(engine, Engine)
    assert engine.dialect.name == "sqlite"


def test_verify_database_connection_with_sqlite_test_engine(tmp_path):
    import app.models  # noqa: F401
    from app.database import Base
    db_file = tmp_path / "test_conn.db"
    test_engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=test_engine)

    receipt = verify_database_connection(test_engine)
    assert receipt["connected"] is True
    assert receipt["dialect"] == "sqlite"
    assert receipt["verified"] is True
    assert set(receipt["tables_found"]) == set(PROVISIONED_TABLES)
    assert receipt["tables_missing"] == []


def test_verify_database_connection_failure():
    bad_engine = create_engine("sqlite:///nonexistent_dir/impossible/path.db")
    with patch.object(bad_engine, "connect", side_effect=RuntimeError("Connection refused")):
        receipt = verify_database_connection(bad_engine)
        assert receipt["connected"] is False
        assert "Connection refused" in receipt.get("error", "")


def test_verify_persistence_transaction_cycle():
    """Verify that video_projects, render_jobs, and publish_jobs persist correctly."""
    report = verify_persistence()
    assert report["project_persisted"] is True
    assert report["render_job_persisted"] is True
    assert report["publish_job_persisted"] is True
    assert report["verified"] is True


def test_get_db_session_lifecycle():
    generator = get_db()
    db = next(generator)
    assert db is not None
    assert hasattr(db, "commit")
    with pytest.raises(StopIteration):
        next(generator)

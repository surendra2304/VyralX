"""One-shot schema bootstrap/migration command for Compose and Dokploy."""
from __future__ import annotations

import logging
from typing import Any

import app.models  # noqa: F401 — register all tables before create_all()
from app.config import get_settings
from app.database import Base, engine, verify_database_connection
from app.media_store import bootstrap_media_schema, media_warehouse_status
from app.migrations import run_additive_migrations

settings = get_settings()
settings.prepare_directories()
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("vyralx.init")


def init_database(engine_to_use=None) -> dict[str, Any]:
    target_engine = engine_to_use or engine
    Base.metadata.create_all(bind=target_engine)
    run_additive_migrations(target_engine)
    receipt = verify_database_connection(target_engine)
    if not receipt["connected"]:
        log.error("Failed to connect to database: %s", receipt.get("error"))
        raise RuntimeError(f"Database initialization failed: {receipt.get('error')}")
    media_receipt = media_warehouse_status()
    if media_receipt.get("configured"):
        bootstrap_media_schema()
        media_receipt = media_warehouse_status()
        receipt["media_database"] = media_receipt
        if not media_receipt.get("connected") or not media_receipt.get("tables_found"):
            log.error("Media warehouse is not ready: %s", media_receipt.get("error"))
            raise RuntimeError("Media warehouse initialization failed")
    log.info(
        "Database schema initialized successfully. Dialect: %s, Verified tables: %s",
        receipt["dialect"],
        receipt["tables_found"],
    )
    return receipt


if __name__ == "__main__":
    try:
        init_database()
    except Exception:
        raise SystemExit(1)

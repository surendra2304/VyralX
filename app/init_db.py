"""One-shot schema bootstrap/migration command for Compose and Dokploy."""
import logging

import app.models  # noqa: F401 — register all tables before create_all()
from app.config import get_settings
from app.database import Base, engine, verify_database_connection
from app.migrations import run_additive_migrations

settings = get_settings()
settings.prepare_directories()
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("vyralx.init")

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    run_additive_migrations(engine)
    receipt = verify_database_connection(engine)
    if not receipt["connected"]:
        log.error("Failed to connect to database: %s", receipt.get("error"))
        raise SystemExit(1)
    log.info(
        "Database schema initialized successfully. Dialect: %s, Verified tables: %s",
        receipt["dialect"],
        receipt["tables_found"],
    )

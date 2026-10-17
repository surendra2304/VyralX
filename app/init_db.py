"""One-shot schema bootstrap/migration command for Compose and Dokploy."""
import logging

import app.models  # noqa: F401 — register all tables before create_all()
from app.config import get_settings
from app.database import Base, engine
from app.migrations import run_additive_migrations

settings = get_settings()
settings.prepare_directories()
logging.basicConfig(level=settings.log_level)

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    run_additive_migrations(engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    logging.getLogger("vyralx.init").info("Database schema initialized successfully")

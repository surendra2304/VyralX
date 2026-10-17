"""Small additive migrations for installations using SQLite or PostgreSQL.

New columns are added only when absent so named volumes survive upgrades. For
larger schema changes, use Alembic migrations before a broad production rollout.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "render_jobs": {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "options_json": "TEXT NOT NULL DEFAULT '{}'",
    },
    "publish_jobs": {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "approved_at": "TIMESTAMP",
    },
    "content_packs": {
        "voiceover_path": "VARCHAR(2048) NOT NULL DEFAULT ''",
        "voiceover_status": "VARCHAR(40) NOT NULL DEFAULT 'not_generated'",
    },
}


def run_additive_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, wanted_columns in ADDITIVE_COLUMNS.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, declaration in wanted_columns.items():
                if column_name in existing:
                    continue
                connection.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {declaration}')
                )

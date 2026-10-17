"""Small additive migrations for installations using SQLite or PostgreSQL.

The service has no destructive migrations. New columns are added when absent so
an existing named volume can be upgraded without dropping the user's catalog.
For larger schema changes, move this to Alembic before production rollout.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# table -> column -> SQL fragment. Keep fragments portable between SQLite and PostgreSQL.
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "render_jobs": {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
    },
    "publish_jobs": {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "started_at": "TIMESTAMP",
        "completed_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
        "approved_at": "TIMESTAMP",
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

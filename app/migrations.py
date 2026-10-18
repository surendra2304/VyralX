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
        "project_id": "INTEGER",
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
    "video_projects": {
        "thumbnail_path": "VARCHAR(2048) NOT NULL DEFAULT ''",
        "memora_memory_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        "memora_memory_status": "VARCHAR(32) NOT NULL DEFAULT 'disabled'",
        "auto_discover_trend": "BOOLEAN NOT NULL DEFAULT FALSE",
        "trend_query": "VARCHAR(200) NOT NULL DEFAULT ''",
        "trend_max_results": "INTEGER NOT NULL DEFAULT 10",
        "trend_source_video_id": "VARCHAR(100) NOT NULL DEFAULT ''",
        "trend_source_url": "VARCHAR(2048) NOT NULL DEFAULT ''",
        "trend_score": "FLOAT NOT NULL DEFAULT 0",
    },
    "agent_tasks": {
        "idempotency_key": "VARCHAR(160)",
        "authorization_context_json": "TEXT NOT NULL DEFAULT '{}'",
        "trace_id": "VARCHAR(120) NOT NULL DEFAULT ''",
        "parent_task_id": "VARCHAR(120) NOT NULL DEFAULT ''",
        "request_id": "VARCHAR(120) NOT NULL DEFAULT ''",
        "actor": "VARCHAR(120) NOT NULL DEFAULT 'operator'",
        "capability": "VARCHAR(120) NOT NULL DEFAULT ''",
        "objective": "VARCHAR(500) NOT NULL DEFAULT ''",
        "trust_level": "VARCHAR(40) NOT NULL DEFAULT 'untrusted'",
        "deadline": "VARCHAR(80) NOT NULL DEFAULT ''",
        "requested_mode": "VARCHAR(20) NOT NULL DEFAULT 'async'",
        "priority": "VARCHAR(20) NOT NULL DEFAULT 'normal'",
        "source_agent": "VARCHAR(120) NOT NULL DEFAULT 'friday'",
        "target_agent": "VARCHAR(120) NOT NULL DEFAULT 'vyralx'",
        "action": "VARCHAR(120) NOT NULL DEFAULT ''",
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
                if column_name not in existing:
                    connection.execute(
                        text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {declaration}')
                    )
        if inspector.has_table("agent_tasks"):
            # NULL keys remain available to legacy/direct submissions; named keys are unique.
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_agent_tasks_idempotency_key "
                    "ON agent_tasks (idempotency_key)"
                )
            )

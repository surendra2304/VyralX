"""Small additive migrations for the VyralX application schema.

New columns are added only when absent so durable volumes survive upgrades. The
production database is Oracle Autonomous Database, so every statement here is
dialect-aware:

* identifiers are unquoted (Oracle stores unquoted names in upper case, and a
  quoted lower-case name would not resolve);
* ``TEXT`` becomes ``CLOB``, ``BOOLEAN`` becomes ``NUMBER(1)`` and
  ``TIMESTAMP`` becomes ``TIMESTAMP WITH TIME ZONE`` on Oracle;
* ``CREATE INDEX IF NOT EXISTS`` is replaced with an explicit inspector check.

For larger schema changes, use Alembic migrations before a broad production
rollout.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("vyralx.migrations")

ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "sources": {
        "repeat_use_allowed": "BOOLEAN NOT NULL DEFAULT FALSE",
        "repeat_use_reviewed_at": "TIMESTAMP",
        "repeat_use_review_notes": "TEXT NOT NULL DEFAULT ''",
    },
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
        "confirm_pexels_repeat_use": "BOOLEAN NOT NULL DEFAULT FALSE",
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


def _oracle_declaration(declaration: str) -> str:
    """Translate a SQLite/PostgreSQL declaration into Oracle DDL.

    Oracle treats the empty string as NULL, so ``NOT NULL DEFAULT ''`` cannot be
    added to a populated table. Additive columns on Oracle are therefore added
    nullable and backfilled by the application's Python-side defaults, which is
    how SQLAlchemy already reads missing values.
    """

    translated = declaration.upper()
    if "BOOLEAN" in translated:
        translated = translated.replace("BOOLEAN NOT NULL DEFAULT FALSE", "NUMBER(1) DEFAULT 0 NOT NULL")
        translated = translated.replace("BOOLEAN", "NUMBER(1)")
    if translated.startswith("TEXT"):
        translated = "CLOB" + translated[len("TEXT"):]
    if translated.startswith("TIMESTAMP"):
        translated = "TIMESTAMP WITH TIME ZONE" + translated[len("TIMESTAMP"):]
    # CLOB cannot carry a NOT NULL default of '' on Oracle ('' is NULL).
    if "CLOB" in translated:
        translated = translated.replace("NOT NULL", "").replace("DEFAULT ''", "").strip()
    if translated.endswith("DEFAULT ''"):
        translated = translated[: -len("DEFAULT ''")].strip()
    return translated


def run_additive_migrations(engine: Engine) -> None:
    dialect = engine.dialect.name
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, wanted_columns in ADDITIVE_COLUMNS.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"].lower() for column in inspector.get_columns(table_name)}
            for column_name, declaration in wanted_columns.items():
                if column_name.lower() in existing:
                    continue
                ddl_type = _oracle_declaration(declaration) if dialect == "oracle" else declaration
                connection.execute(
                    text(f"ALTER TABLE {table_name} ADD {column_name} {ddl_type}")
                )
                log.info("Added column %s.%s (%s)", table_name, column_name, ddl_type)
        if inspector.has_table("agent_tasks"):
            # NULL keys remain available to legacy/direct submissions; named keys are unique.
            wanted_index = "ix_agent_tasks_idempotency_key"
            existing_indexes = {index["name"].lower() for index in inspector.get_indexes("agent_tasks")}
            covered = [
                (index.get("column_names") or []) for index in inspector.get_indexes("agent_tasks")
            ]
            for constraint in inspector.get_unique_constraints("agent_tasks"):
                name = constraint.get("name")
                if name:
                    existing_indexes.add(name.lower())
                covered.append(constraint.get("column_names") or [])
            # Oracle auto-names a column-level UNIQUE constraint (SYS_C...), so the
            # name check alone would try to index the same column twice (ORA-01408).
            already_unique = any(
                [column.lower() for column in columns] == ["idempotency_key"] for columns in covered
            )
            if wanted_index not in existing_indexes and not already_unique:
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX {wanted_index} "
                        "ON agent_tasks (idempotency_key)"
                    )
                )
                log.info("Created index %s", wanted_index)

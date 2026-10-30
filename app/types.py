"""Column types that keep Python string semantics on Oracle.

Oracle stores the empty string as NULL, so a ``NOT NULL`` column with a default
of ``""`` rejects every row (ORA-01400). These decorators let the column be
nullable in the database while callers still see ``""`` instead of ``None``,
which is what the existing VyralX code assumes.
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator


class EmptyStringType(TypeDecorator):
    """VARCHAR that stores ``""`` as NULL and reads NULL back as ``""``."""

    impl = String
    cache_ok = True

    def __init__(self, length: int | None = None, **kwargs):
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value, dialect):
        if value == "" and dialect.name == "oracle":
            return None
        return value

    def process_result_value(self, value, dialect):
        if value is None and dialect.name == "oracle":
            return ""
        return value


class EmptyTextType(TypeDecorator):
    """CLOB that stores ``""`` as NULL and reads NULL back as ``""``."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value == "" and dialect.name == "oracle":
            return None
        return value

    def process_result_value(self, value, dialect):
        if value is None and dialect.name == "oracle":
            return ""
        return value

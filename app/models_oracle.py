"""Oracle-aware replacements for VyralX columns that store the empty string.

Oracle treats the empty string as NULL, so any ``NOT NULL DEFAULT ''`` column
rejects every INSERT with ORA-01400. These decorators make VARCHAR/CLOB columns
nullable at the DB level but read NULL back as ``""`` for the existing code,
which assumes ``""`` is a valid value not ``None``. Apply with:

    from app.types import EmptyStringType, EmptyTextType
    Title = Column(EmptyStringType(300), default="")
"""

from __future__ import annotations

from sqlalchemy import String, Text, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmptyStringType(TypeDecorator):
    """VARCHAR that stores ``""`` as NULL and reads NULL back as ``""``."""

    impl = String
    cache_ok = True

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

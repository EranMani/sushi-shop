# src/models/base.py
#
# Declarative base for all SQLAlchemy ORM models.
# Every model class inherits from Base.
# Import this module first to avoid circular dependency issues.

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    Using a subclass (rather than the legacy `declarative_base()` function)
    is the SQLAlchemy 2.x recommended pattern. It gives us a single registry
    and allows `Base.metadata` to be passed directly to Alembic's env.py.
    """

    pass

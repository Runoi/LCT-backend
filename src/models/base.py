"""Declarative base shared by all ORM models."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy ORM models."""

"""One session per request; schema changes are handled through Alembic."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    url = get_settings().database_url
    options = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=options, pool_pre_ping=True)


def get_session():
    factory = sessionmaker(get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session

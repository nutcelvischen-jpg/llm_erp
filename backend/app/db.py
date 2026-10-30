from sqlalchemy import create_engine, text

from .config import settings

engine = create_engine(settings.pg_dsn, pool_pre_ping=True, pool_size=5, future=True)


def ping() -> bool:
    with engine.connect() as c:
        return c.execute(text("select 1")).scalar() == 1

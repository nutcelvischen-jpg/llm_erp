from sqlalchemy import create_engine, text

from .config import settings

engine = create_engine(settings.pg_dsn, pool_pre_ping=True, pool_size=5, future=True)
# LLM 產生的 SQL 一律用唯讀角色執行（只能 SELECT 四個 View）
engine_ro = create_engine(
    settings.pg_dsn_readonly, pool_pre_ping=True, pool_size=3, future=True,
    connect_args={"options": "-c search_path=erp"},  # 讓不帶 erp. 前綴的 View 名稱找得到
)


def ping() -> bool:
    with engine.connect() as c:
        return c.execute(text("select 1")).scalar() == 1

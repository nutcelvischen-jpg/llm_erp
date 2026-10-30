from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str = "lm-studio"
    llm_model: str
    embed_model: str
    embed_dim: int = 1024
    llm_timeout: int = 120
    pg_dsn: str
    pg_dsn_readonly: str = "postgresql+psycopg://llm_reader:llm_reader@localhost:5432/erp_poc"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "erp_docs"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_n: int = 5
    app_port: int = 8000
    app_tz: str = "Asia/Taipei"
    log_level: str = "INFO"
    line_channel_access_token: str = ""
    line_target_id: str = ""


settings = Settings()

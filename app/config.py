"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # PostgreSQL / pgvector
    # Use the same Postgres that Chatwoot already runs.
    # Example: postgresql://user:password@localhost:5432/chatwoot
    postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/tata_agent"
    pg_vector_table: str = "tata_knowledge"
    pg_memory_table: str = "tata_conversations"
    memory_max_turns: int = 10  # number of past conversation turns to include

    # Chatwoot
    chatwoot_base_url: str = "http://localhost:3000"
    chatwoot_api_token: str = ""
    chatwoot_account_id: int = 1

    # Webhook
    webhook_token: str = ""


settings = Settings()

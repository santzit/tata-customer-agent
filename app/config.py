"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI / Azure OpenAI
    # Map directly to the GitHub Actions secret and variables:
    #   secrets.OPENAI_API_KEY       → openai_api_key
    #   vars.LLM_MODEL               → llm_model
    #   vars.LLM_PROVIDER            → llm_provider  ("openai" or "azure")
    #   vars.OPENAI_API_ENDPOINT     → openai_api_endpoint  (Azure Cognitive Services URL)
    #   vars.EMBEDDING_MODEL_SMALL   → embedding_model_small  (1536-dim by default)
    #   vars.EMBEDDING_MODEL_LARGE   → embedding_model_large  (3072-dim by default)
    #   vars.EMBEDDING_DIMENSION     → embedding_dimension  (must match the deployed model)
    openai_api_key: str = ""
    llm_model: str = "gpt-4.1"
    llm_provider: str = "openai"
    openai_api_endpoint: str = ""  # set to Azure endpoint to use Azure OpenAI
    embedding_model_small: str = "text-embedding-3-small"  # 1536 dimensions
    embedding_model_large: str = "text-embedding-3-large"  # 3072 dimensions
    embedding_dimension: int = 1536  # vector column size; change to 3072 when using the large model

    # PostgreSQL / pgvector
    # postgres_user / postgres_password — superuser credentials used **only** at
    # boot time to create the tata_agent database.  These match the standard Docker
    # POSTGRES_USER / POSTGRES_PASSWORD env vars used by the postgres container.
    # Leave both blank to skip the automatic database-creation step.
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
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

    # Message buffer: seconds of silence before the agent replies.
    # When messages arrive within this window they are batched into a single
    # agent call; after the window expires with no new messages the reply is sent.
    # Set RESPONSE_DELAY_SECONDS=0 to disable buffering (reply immediately).
    response_delay_seconds: float = 120.0

    # Logging
    # Controls the verbosity of the application log output.
    # Accepted values (case-insensitive): debug, info, warning, error, critical
    # Use "debug" to see full incoming payloads, every agent step, and
    # Chatwoot HTTP responses; "info" for normal operational logs.
    log_level: str = "info"

    def make_openai_client(self):
        """Create an OpenAI client.

        If ``openai_api_endpoint`` is set the client points at that base URL,
        which enables Azure OpenAI Cognitive Services endpoints
        (e.g. ``https://<resource>.cognitiveservices.azure.com/openai/v1/``).
        """
        from openai import OpenAI

        kwargs: dict = {"api_key": self.openai_api_key}
        if self.openai_api_endpoint:
            kwargs["base_url"] = self.openai_api_endpoint
        return OpenAI(**kwargs)


settings = Settings()

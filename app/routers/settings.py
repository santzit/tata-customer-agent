"""API routes for general application settings (OpenAI, database, webhook)."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import db_models
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SettingsPayload(BaseModel):
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    llm_model: str | None = Field(default=None, description="LLM model name")
    llm_provider: str | None = Field(default=None, description="'openai' or 'azure'")
    openai_api_endpoint: str | None = Field(default=None, description="Azure OpenAI endpoint URL")
    embedding_model: str | None = Field(default=None, description="Embedding model name")
    embedding_dimension: int | None = Field(default=None, description="Vector dimension")
    response_delay_seconds: float | None = Field(
        default=None, description="Silence window before agent replies (seconds)"
    )
    webhook_token: str | None = Field(default=None, description="Webhook security token")
    log_level: str | None = Field(default=None, description="Logging level")


class SettingsOut(BaseModel):
    openai_api_key_set: bool
    llm_model: str
    llm_provider: str
    openai_api_endpoint: str
    embedding_model: str
    embedding_dimension: int
    response_delay_seconds: float
    webhook_token_set: bool
    log_level: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OPENAI_KEY = "openai_api_key"
_LLM_MODEL = "llm_model"
_LLM_PROVIDER = "llm_provider"
_OPENAI_ENDPOINT = "openai_api_endpoint"
_EMBEDDING_MODEL = "embedding_model"
_EMBEDDING_DIM = "embedding_dimension"
_DELAY = "response_delay_seconds"
_WEBHOOK_TOKEN = "webhook_token"
_LOG_LEVEL = "log_level"


def _merged_settings() -> dict:
    """Return DB settings merged with env-var defaults."""
    stored = db_models.get_all_settings()
    return {
        _OPENAI_KEY: stored.get(_OPENAI_KEY, settings.openai_api_key),
        _LLM_MODEL: stored.get(_LLM_MODEL, settings.llm_model),
        _LLM_PROVIDER: stored.get(_LLM_PROVIDER, settings.llm_provider),
        _OPENAI_ENDPOINT: stored.get(_OPENAI_ENDPOINT, settings.openai_api_endpoint),
        _EMBEDDING_MODEL: stored.get(_EMBEDDING_MODEL, settings.embedding_model_small),
        _EMBEDDING_DIM: stored.get(_EMBEDDING_DIM, settings.embedding_dimension),
        _DELAY: stored.get(_DELAY, settings.response_delay_seconds),
        _WEBHOOK_TOKEN: stored.get(_WEBHOOK_TOKEN, settings.webhook_token),
        _LOG_LEVEL: stored.get(_LOG_LEVEL, settings.log_level),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=SettingsOut)
def get_settings():
    """Return the current application settings.

    DB-stored values take precedence over environment variable defaults.
    Sensitive fields (API keys, tokens) are returned only as a boolean
    indicating whether they are set.
    """
    merged = _merged_settings()
    return SettingsOut(
        openai_api_key_set=bool(merged[_OPENAI_KEY]),
        llm_model=merged[_LLM_MODEL],
        llm_provider=merged[_LLM_PROVIDER],
        openai_api_endpoint=merged[_OPENAI_ENDPOINT],
        embedding_model=merged[_EMBEDDING_MODEL],
        embedding_dimension=int(merged[_EMBEDDING_DIM]),
        response_delay_seconds=float(merged[_DELAY]),
        webhook_token_set=bool(merged[_WEBHOOK_TOKEN]),
        log_level=merged[_LOG_LEVEL],
    )


@router.post("", response_model=SettingsOut)
def update_settings(body: SettingsPayload):
    """Persist application settings to the database.

    Only fields that are not ``None`` are written so a partial update is safe.
    """
    to_save: dict = {}
    if body.openai_api_key is not None:
        to_save[_OPENAI_KEY] = body.openai_api_key
    if body.llm_model is not None:
        to_save[_LLM_MODEL] = body.llm_model
    if body.llm_provider is not None:
        to_save[_LLM_PROVIDER] = body.llm_provider
    if body.openai_api_endpoint is not None:
        to_save[_OPENAI_ENDPOINT] = body.openai_api_endpoint
    if body.embedding_model is not None:
        to_save[_EMBEDDING_MODEL] = body.embedding_model
    if body.embedding_dimension is not None:
        to_save[_EMBEDDING_DIM] = body.embedding_dimension
    if body.response_delay_seconds is not None:
        to_save[_DELAY] = body.response_delay_seconds
    if body.webhook_token is not None:
        to_save[_WEBHOOK_TOKEN] = body.webhook_token
    if body.log_level is not None:
        to_save[_LOG_LEVEL] = body.log_level

    if to_save:
        db_models.set_many_settings(to_save)

    merged = _merged_settings()
    return SettingsOut(
        openai_api_key_set=bool(merged[_OPENAI_KEY]),
        llm_model=merged[_LLM_MODEL],
        llm_provider=merged[_LLM_PROVIDER],
        openai_api_endpoint=merged[_OPENAI_ENDPOINT],
        embedding_model=merged[_EMBEDDING_MODEL],
        embedding_dimension=int(merged[_EMBEDDING_DIM]),
        response_delay_seconds=float(merged[_DELAY]),
        webhook_token_set=bool(merged[_WEBHOOK_TOKEN]),
        log_level=merged[_LOG_LEVEL],
    )


@router.get("/setup-status", response_model=dict)
def setup_status():
    """Return whether the first-run setup wizard has been completed.

    The setup is considered complete when at least one active account with an
    API token exists **and** an OpenAI API key has been saved.
    """
    accounts = db_models.list_accounts()
    has_account = any(a["api_token"] and a["is_active"] for a in accounts)
    openai_key = db_models.get_setting(_OPENAI_KEY, settings.openai_api_key)
    return {
        "setup_complete": has_account and bool(openai_key),
        "has_account": has_account,
        "openai_configured": bool(openai_key),
    }

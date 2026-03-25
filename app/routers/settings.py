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

_OPENAI_KEY = "OPENAI_API_KEY"
_LLM_MODEL = "OPENAI_MODEL"
_LLM_PROVIDER = "OPENAI_PROVIDER"
_OPENAI_ENDPOINT = "OPENAI_API_ENDPOINT"
_EMBEDDING_MODEL = "EMBEDDING_MODEL"
_EMBEDDING_DIM = "EMBEDDING_DIMENSION"
_DELAY = "RESPONSE_DELAY_SECONDS"
_WEBHOOK_TOKEN = "WEBHOOK_TOKEN"
_LOG_LEVEL = "LOG_LEVEL"


def _merged_settings() -> dict:
    """Return variables merged with env-var defaults."""
    return {
        _OPENAI_KEY: db_models.get_variable_value(_OPENAI_KEY, settings.openai_api_key),
        _LLM_MODEL: db_models.get_variable_value(_LLM_MODEL, settings.llm_model),
        _LLM_PROVIDER: db_models.get_variable_value(_LLM_PROVIDER, settings.llm_provider),
        _OPENAI_ENDPOINT: db_models.get_variable_value(_OPENAI_ENDPOINT, settings.openai_api_endpoint),
        _EMBEDDING_MODEL: db_models.get_variable_value(_EMBEDDING_MODEL, settings.embedding_model_small),
        _EMBEDDING_DIM: db_models.get_variable_value(_EMBEDDING_DIM, str(settings.embedding_dimension)),
        _DELAY: db_models.get_variable_value(_DELAY, str(settings.response_delay_seconds)),
        _WEBHOOK_TOKEN: db_models.get_variable_value(_WEBHOOK_TOKEN, settings.webhook_token),
        _LOG_LEVEL: db_models.get_variable_value(_LOG_LEVEL, settings.log_level),
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
        db_models.set_many_variables(to_save)

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

    Setup is complete when at least one active account exists, a Chatwoot
    API token is stored in variables, and an OpenAI API key is saved.
    """
    accounts = db_models.list_accounts()
    has_active_account = any(a["is_active"] for a in accounts)
    chatwoot_token = db_models.get_variable_value("CHATWOOT_API_TOKEN")
    openai_key = db_models.get_variable_value(_OPENAI_KEY, settings.openai_api_key)
    return {
        "setup_complete": has_active_account and bool(chatwoot_token) and bool(openai_key),
        "has_account": has_active_account,
        "has_chatwoot_token": bool(chatwoot_token),
        "openai_configured": bool(openai_key),
    }

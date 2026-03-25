"""API routes for the unified configuration variable store (tata_variables).

Variables are named after standard environment variables (e.g. ``OPENAI_API_KEY``,
``POSTGRES_HOST``) and grouped into categories: ``chatwoot``, ``database``,
``openai``, ``agent``.

Secret variables (``is_secret=True``) are never returned in plain text; the
API returns ``"***"`` when a secret is set and ``""`` when it is not.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app import db_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/variables", tags=["variables"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class VariableOut(BaseModel):
    key: str
    value: str
    description: str
    category: str
    is_secret: bool
    is_set: bool


class VariableUpsert(BaseModel):
    key: str
    value: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[VariableOut])
def list_variables(category: str | None = None):
    """Return all configuration variables, optionally filtered by *category*.

    Secret values are masked as ``"***"`` when set, ``""`` when not set.
    """
    rows = db_models.list_variables(category=category, mask_secrets=True)
    return [
        VariableOut(
            key=r["key"],
            value=r["value"],
            description=r["description"],
            category=r["category"],
            is_secret=r["is_secret"],
            is_set=r["is_set"],
        )
        for r in rows
    ]


@router.post("", response_model=list[VariableOut])
def upsert_variables(body: list[VariableUpsert]):
    """Upsert one or more variable values in a single call.

    Secret values are accepted in plain text (over HTTPS) and stored as-is;
    they are never echoed back.
    """
    data = {item.key: item.value for item in body}
    db_models.set_many_variables(data)
    rows = db_models.list_variables(mask_secrets=True)
    return [
        VariableOut(
            key=r["key"],
            value=r["value"],
            description=r["description"],
            category=r["category"],
            is_secret=r["is_secret"],
            is_set=r["is_set"],
        )
        for r in rows
    ]


@router.put("/{key}", response_model=VariableOut)
def set_variable(key: str, body: VariableUpsert):
    """Set a single variable value."""
    db_models.set_variable(key, body.value)
    row = db_models.get_variable(key)
    if row is None:
        # Variable created ad-hoc (not in default list)
        return VariableOut(
            key=key,
            value="" if body.value else "",
            description="",
            category="",
            is_secret=False,
            is_set=bool(body.value),
        )
    masked_value = "***" if (row.is_secret and row.value) else ("" if not row.value else row.value)
    if row.is_secret and row.value:
        masked_value = "***"
    elif not row.value:
        masked_value = ""
    else:
        masked_value = row.value
    return VariableOut(
        key=row.key,
        value=masked_value,
        description=row.description,
        category=row.category,
        is_secret=row.is_secret,
        is_set=bool(row.value),
    )

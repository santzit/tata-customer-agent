"""API routes for managing Chatwoot account connections.

Each account stores its own ``api_token`` so that multiple Chatwoot accounts
can be configured from the web UI without environment variables.
"""

import logging

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app import db_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AccountCreate(BaseModel):
    name: str = Field(default="", description="Human-readable label for this connection")
    chatwoot_base_url: str = Field(..., description="Base URL of the Chatwoot instance")
    chatwoot_account_id: int = Field(..., description="Numeric account ID inside Chatwoot")
    api_token: str = Field(..., description="Chatwoot API access token for this account")
    is_active: bool = Field(default=True)


class AccountUpdate(BaseModel):
    name: str | None = None
    chatwoot_base_url: str | None = None
    chatwoot_account_id: int | None = None
    api_token: str | None = Field(default=None, description="Update the API access token")
    is_active: bool | None = None


class AccountOut(BaseModel):
    id: int
    name: str
    chatwoot_base_url: str
    chatwoot_account_id: int
    api_token_set: bool = Field(
        description="True when an API token has been saved for this account"
    )
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> "AccountOut":
        return cls(
            id=row["id"],
            name=row["name"],
            chatwoot_base_url=row["chatwoot_base_url"],
            chatwoot_account_id=row["chatwoot_account_id"],
            api_token_set=bool(row.get("api_token")),
            is_active=row["is_active"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[AccountOut])
def list_accounts():
    """Return all configured Chatwoot account connections."""
    rows = db_models.list_accounts()
    return [AccountOut.from_row(r) for r in rows]


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountCreate):
    """Add a new Chatwoot account connection with its API token."""
    row = db_models.create_account(
        chatwoot_base_url=body.chatwoot_base_url,
        chatwoot_account_id=body.chatwoot_account_id,
        api_token=body.api_token,
        name=body.name,
        is_active=body.is_active,
    )
    return AccountOut.from_row(row)


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int):
    """Return a single account connection by ID."""
    row = db_models.get_account(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountOut.from_row(row)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountUpdate):
    """Update editable fields (including ``api_token``) on an existing account."""
    row = db_models.update_account(
        account_id,
        name=body.name,
        chatwoot_base_url=body.chatwoot_base_url,
        chatwoot_account_id=body.chatwoot_account_id,
        api_token=body.api_token,
        is_active=body.is_active,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountOut.from_row(row)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int):
    """Remove a Chatwoot account connection."""
    deleted = db_models.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")


@router.post("/{account_id}/test", response_model=dict)
def test_account_connection(account_id: int):
    """Verify the stored API token by calling the Chatwoot accounts endpoint.

    Returns ``{"ok": true, "account_name": "..."}`` on success or
    ``{"ok": false, "error": "..."}`` on failure.
    """
    row = db_models.get_account(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")

    base_url = row["chatwoot_base_url"].rstrip("/")
    token = row["api_token"]
    acct_id = row["chatwoot_account_id"]

    if not token:
        return {"ok": False, "error": "No API token stored for this account"}

    url = f"{base_url}/api/v1/accounts/{acct_id}"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers={"api_access_token": token})
            resp.raise_for_status()
            data = resp.json()
        return {"ok": True, "account_name": data.get("name", "")}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/{account_id}/inboxes", response_model=list[dict])
def list_account_inboxes(account_id: int):
    """Return all inboxes for a given account connection."""
    row = db_models.get_account(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")

    from app.services.chatwoot_client import ChatwootClient

    client = ChatwootClient(
        base_url=row["chatwoot_base_url"],
        api_token=row["api_token"],
        account_id=row["chatwoot_account_id"],
    )
    inboxes = client.list_inboxes()
    return inboxes

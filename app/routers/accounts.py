"""API routes for managing Chatwoot account connections.

Account credentials (base URL, API token) are stored in ``tata_variables``
under the keys ``CHATWOOT_BASE_URL``, ``CHATWOOT_ACCOUNT_ID``, and
``CHATWOOT_API_TOKEN``.  The ``tata_accounts`` table only tracks the
human-readable name, the numeric account ID, and the active/inactive flag.
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
    chatwoot_account_id: int = Field(..., description="Numeric account ID inside Chatwoot")
    is_active: bool = Field(default=True)


class AccountUpdate(BaseModel):
    name: str | None = None
    chatwoot_account_id: int | None = None
    is_active: bool | None = None


class AccountOut(BaseModel):
    id: int
    name: str
    chatwoot_account_id: int
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> "AccountOut":
        return cls(
            id=row["id"],
            name=row["name"],
            chatwoot_account_id=row["chatwoot_account_id"],
            is_active=row["is_active"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/from-chatwoot", response_model=list[dict])
def fetch_accounts_from_chatwoot():
    """Discover Chatwoot accounts accessible with the configured credentials.

    Reads ``CHATWOOT_BASE_URL`` and ``CHATWOOT_API_TOKEN`` from
    ``tata_variables`` and calls ``GET /api/v1/profile`` to retrieve the list
    of accounts the API token belongs to.

    Returns a list of dicts with ``id``, ``name``, and ``role`` for each account.
    """
    base_url = db_models.get_variable_value("CHATWOOT_BASE_URL")
    token = db_models.get_variable_value("CHATWOOT_API_TOKEN")

    if not base_url:
        raise HTTPException(
            status_code=400,
            detail="CHATWOOT_BASE_URL not configured in Variables",
        )
    if not token:
        raise HTTPException(
            status_code=400,
            detail="CHATWOOT_API_TOKEN not configured in Variables",
        )

    # GET /api/v1/profile returns:
    # { "id": 1, "name": "...", "accounts": [{"id": 1, "name": "...", "role": "administrator"}, ...] }
    url = f"{base_url.rstrip('/')}/api/v1/profile"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers={"api_access_token": token})
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Chatwoot returned HTTP {exc.response.status_code}",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    return [
        {"id": acct.get("id"), "name": acct.get("name", ""), "role": acct.get("role", "")}
        for acct in accounts
        if isinstance(acct, dict)
    ]


@router.get("", response_model=list[AccountOut])
def list_accounts():
    """Return all configured Chatwoot account connections."""
    rows = db_models.list_accounts()
    return [AccountOut.from_row(r) for r in rows]


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountCreate):
    """Add a new Chatwoot account connection."""
    row = db_models.create_account(
        chatwoot_account_id=body.chatwoot_account_id,
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
    """Update editable fields on an existing account."""
    row = db_models.update_account(
        account_id,
        name=body.name,
        chatwoot_account_id=body.chatwoot_account_id,
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
    """Verify the Chatwoot credentials stored in ``tata_variables``.

    Reads ``CHATWOOT_BASE_URL`` and ``CHATWOOT_API_TOKEN`` from the variables
    table and calls the Chatwoot accounts endpoint.  Returns
    ``{"ok": true, "account_name": "..."}`` on success or
    ``{"ok": false, "error": "..."}`` on failure.
    """
    row = db_models.get_account(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")

    base_url = db_models.get_variable_value("CHATWOOT_BASE_URL")
    token = db_models.get_variable_value("CHATWOOT_API_TOKEN")
    acct_id = row["chatwoot_account_id"]

    if not base_url:
        return {"ok": False, "error": "CHATWOOT_BASE_URL not configured in Variables"}
    if not token:
        return {"ok": False, "error": "CHATWOOT_API_TOKEN not configured in Variables"}

    url = f"{base_url.rstrip('/')}/api/v1/accounts/{acct_id}"
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
    """Return all inboxes for a given account connection.

    Uses the Chatwoot credentials stored in ``tata_variables``.
    """
    row = db_models.get_account(account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found")

    base_url = db_models.get_variable_value("CHATWOOT_BASE_URL")
    token = db_models.get_variable_value("CHATWOOT_API_TOKEN")

    if not base_url or not token:
        raise HTTPException(
            status_code=400,
            detail="CHATWOOT_BASE_URL and CHATWOOT_API_TOKEN must be set in Variables",
        )

    from app.services.chatwoot_client import ChatwootClient

    client = ChatwootClient(
        base_url=base_url,
        api_token=token,
        account_id=row["chatwoot_account_id"],
    )
    return client.list_inboxes()

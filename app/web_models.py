"""SQLModel ORM models for the v03x Web/App Frontend feature."""

from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Column as SAColumn
from sqlmodel import Field, SQLModel


class ChatwootAccount(SQLModel, table=True):
    __tablename__ = "web_chatwoot_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(unique=True)
    name: str
    token_api: str = ""


class ChatwootInbox(SQLModel, table=True):
    __tablename__ = "web_chatwoot_inboxes"

    id: Optional[int] = Field(default=None, primary_key=True)
    inbox_id: int
    account_id: int  # Chatwoot account_id (not a FK; avoids constraint issues)
    name: str = ""
    portal_slug: str = ""  # Associated Help Center portal slug (if any)


class ChatwootTeam(SQLModel, table=True):
    __tablename__ = "web_chatwoot_teams"

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int
    account_id: int = Field(foreign_key="web_chatwoot_accounts.id")
    name: str = ""


class HelpCenterArticle(SQLModel, table=True):
    __tablename__ = "web_help_center_articles"

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(unique=True)
    title: str
    content: str = ""
    locale: str = "en"
    updated_at: Optional[datetime] = None
    portal_slug: str = ""  # Portal the article belongs to


class OpenAIConfig(SQLModel, table=True):
    __tablename__ = "web_openai_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    api_key: str = ""
    model: str = "gpt-4.1"
    api_endpoint: str = ""
    embedding_model_small: str = ""
    embedding_model_large: str = ""
    llm_provider: str = "openai"
    params: Optional[dict] = Field(default=None, sa_column=SAColumn(sa.JSON))


def create_web_tables(engine) -> None:
    """Create all web frontend SQLModel tables if they don't exist."""
    SQLModel.metadata.create_all(engine)
    # Apply additive migrations for newly introduced columns.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE web_openai_config "
            "ADD COLUMN IF NOT EXISTS api_endpoint TEXT NOT NULL DEFAULT ''"
        )
        conn.exec_driver_sql(
            "ALTER TABLE web_openai_config "
            "ADD COLUMN IF NOT EXISTS embedding_model_small TEXT NOT NULL DEFAULT ''"
        )
        conn.exec_driver_sql(
            "ALTER TABLE web_openai_config "
            "ADD COLUMN IF NOT EXISTS embedding_model_large TEXT NOT NULL DEFAULT ''"
        )
        conn.exec_driver_sql(
            "ALTER TABLE web_openai_config "
            "ADD COLUMN IF NOT EXISTS llm_provider TEXT NOT NULL DEFAULT 'openai'"
        )
        conn.exec_driver_sql(
            "ALTER TABLE web_help_center_articles "
            "ADD COLUMN IF NOT EXISTS portal_slug TEXT NOT NULL DEFAULT ''"
        )
        conn.exec_driver_sql(
            "ALTER TABLE web_chatwoot_inboxes "
            "ADD COLUMN IF NOT EXISTS portal_slug TEXT NOT NULL DEFAULT ''"
        )

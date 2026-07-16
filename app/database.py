from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.config import get_settings
from app.models import Base
from app.services.sales_managers import seed_default_sales_managers

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_sqlite(conn)
        await seed_default_sales_managers(conn)


async def _migrate_sqlite(conn) -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    user_columns = await conn.run_sync(lambda sync_conn: {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(users)")})
    if "platform" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN platform VARCHAR(32) NOT NULL DEFAULT 'telegram'"))
    if "platform_user_id" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN platform_user_id VARCHAR(255)"))
        await conn.execute(text("UPDATE users SET platform_user_id = CAST(telegram_id AS TEXT) WHERE platform_user_id IS NULL"))
    if "phone" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(64)"))
    if "amo_agent_lead_id" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN amo_agent_lead_id BIGINT"))
    if "amo_agent_contact_id" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN amo_agent_contact_id BIGINT"))
    if "amo_agent_status_id" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN amo_agent_status_id BIGINT"))
    if "amo_agent_sync_status" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN amo_agent_sync_status VARCHAR(32)"))
    if "amo_agent_sync_error" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN amo_agent_sync_error TEXT"))
    if "amo_agent_synced_at" not in user_columns:
        await conn.execute(text("ALTER TABLE users ADD COLUMN amo_agent_synced_at DATETIME"))

    lead_columns = await conn.run_sync(lambda sync_conn: {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(leads)")})
    if "platform" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN platform VARCHAR(32) NOT NULL DEFAULT 'telegram'"))
    if "relation_to_agent" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN relation_to_agent VARCHAR(255)"))
    if "agent_payout_phone" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN agent_payout_phone VARCHAR(64)"))
    if "staff_notified_at" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN staff_notified_at DATETIME"))
        await conn.execute(text("UPDATE leads SET staff_notified_at = CURRENT_TIMESTAMP WHERE type = 'agent_client'"))
    if "sales_manager_id" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN sales_manager_id INTEGER"))
    if "amo_lead_id" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN amo_lead_id BIGINT"))
    if "amo_contact_id" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN amo_contact_id BIGINT"))
    if "amo_pipeline_id" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN amo_pipeline_id BIGINT"))
    if "amo_status_id" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN amo_status_id BIGINT"))
    if "amo_sync_status" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN amo_sync_status VARCHAR(32)"))
    if "amo_sync_error" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN amo_sync_error TEXT"))
    if "amo_synced_at" not in lead_columns:
        await conn.execute(text("ALTER TABLE leads ADD COLUMN amo_synced_at DATETIME"))

    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_platform ON users(platform)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_platform_user_id ON users(platform_user_id)"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_platform_user ON users(platform, platform_user_id)"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_amo_agent_lead_id ON users(amo_agent_lead_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_amo_agent_status_id ON users(amo_agent_status_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_platform ON leads(platform)"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_leads_amo_lead_id ON leads(amo_lead_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_amo_pipeline_id ON leads(amo_pipeline_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_amo_status_id ON leads(amo_status_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_sales_manager_id ON leads(sales_manager_id)"))

    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS developer_settings ("
            "key VARCHAR(64) NOT NULL PRIMARY KEY, "
            "value TEXT NOT NULL DEFAULT '', "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL"
            ")"
        )
    )
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS developer_participants ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "platform VARCHAR(32) NOT NULL DEFAULT 'telegram', "
            "platform_user_id VARCHAR(255) NOT NULL, "
            "user_id INTEGER, "
            "role VARCHAR(32) NOT NULL DEFAULT 'user', "
            "label VARCHAR(255), "
            "enabled BOOLEAN NOT NULL DEFAULT 1, "
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "FOREIGN KEY(user_id) REFERENCES users (id), "
            "CONSTRAINT uq_developer_participants_platform_user UNIQUE (platform, platform_user_id)"
            ")"
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_developer_participants_platform ON developer_participants(platform)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_developer_participants_platform_user_id ON developer_participants(platform_user_id)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_developer_participants_user_id ON developer_participants(user_id)"))
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS developer_user_mutes ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "user_id INTEGER NOT NULL UNIQUE, "
            "mute_all BOOLEAN NOT NULL DEFAULT 0, "
            "mute_staff_notifications BOOLEAN NOT NULL DEFAULT 0, "
            "mute_broadcasts BOOLEAN NOT NULL DEFAULT 0, "
            "mute_bonus_notifications BOOLEAN NOT NULL DEFAULT 0, "
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
            "FOREIGN KEY(user_id) REFERENCES users (id)"
            ")"
        )
    )
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_developer_user_mutes_user_id ON developer_user_mutes(user_id)"))


async def close_db() -> None:
    await engine.dispose()

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeveloperSetting, Lead, SalesManager
from app.utils.validators import normalize_phone

ROUND_ROBIN_KEY = "sales_manager_round_robin_index"


@dataclass(frozen=True, slots=True)
class DefaultSalesManager:
    code: str
    sort_order: int
    name: str
    phone: str
    amo_user_id: int


DEFAULT_SALES_MANAGERS = [
    DefaultSalesManager("degtyareva", 10, "Дегтярева Юлия", "+79328504022", 7074220),
    DefaultSalesManager("sheveleva", 20, "Ольга Шевелева", "+79333210141", 3298921),
    DefaultSalesManager("miller", 30, "Юлия Миллер", "+79232700622", 8476783),
    DefaultSalesManager("karepov", 40, "Павел Карепов", "+79230165336", 2328073),
]


async def seed_default_sales_managers(conn) -> None:
    for manager in DEFAULT_SALES_MANAGERS:
        await conn.execute(
            text(
                "INSERT INTO sales_managers (code, sort_order, name, phone, amo_user_id, enabled) "
                "SELECT :code, :sort_order, :name, :phone, :amo_user_id, 1 "
                "WHERE NOT EXISTS (SELECT 1 FROM sales_managers WHERE code = :code)"
            ),
            {
                "code": manager.code,
                "sort_order": manager.sort_order,
                "name": manager.name,
                "phone": manager.phone,
                "amo_user_id": manager.amo_user_id,
            },
        )


async def list_sales_managers(session: AsyncSession) -> list[SalesManager]:
    result = await session.execute(select(SalesManager).order_by(SalesManager.sort_order.asc(), SalesManager.id.asc()))
    return list(result.scalars().all())


async def active_sales_managers(session: AsyncSession) -> list[SalesManager]:
    result = await session.execute(
        select(SalesManager)
        .where(SalesManager.enabled.is_(True))
        .order_by(SalesManager.sort_order.asc(), SalesManager.id.asc())
    )
    return list(result.scalars().all())


async def choose_next_sales_manager(session: AsyncSession) -> SalesManager | None:
    managers = await active_sales_managers(session)
    if not managers:
        return None

    result = await session.execute(select(DeveloperSetting).where(DeveloperSetting.key == ROUND_ROBIN_KEY))
    setting = result.scalar_one_or_none()
    if not setting:
        setting = DeveloperSetting(key=ROUND_ROBIN_KEY, value="0")
        session.add(setting)
        await session.flush()

    try:
        index = int(setting.value or "0")
    except ValueError:
        index = 0
    manager = managers[index % len(managers)]
    setting.value = str((index + 1) % len(managers))
    return manager


async def assign_sales_manager_if_needed(session: AsyncSession, lead: Lead) -> SalesManager | None:
    if lead.sales_manager_id:
        await session.refresh(lead, ["sales_manager"])
        return lead.sales_manager

    manager = await choose_next_sales_manager(session)
    if not manager:
        return None
    lead.sales_manager_id = manager.id
    await session.flush()
    await session.refresh(lead, ["sales_manager"])
    return manager


async def set_sales_manager_enabled(session: AsyncSession, manager: SalesManager, enabled: bool) -> SalesManager:
    manager.enabled = enabled
    await session.commit()
    await session.refresh(manager)
    return manager


async def update_sales_manager_details(
    session: AsyncSession,
    manager: SalesManager,
    *,
    name: str,
    phone: str,
    amo_user_id: int | None,
) -> SalesManager:
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        raise ValueError("Некорректный телефон")
    manager.name = name.strip()[:255] or manager.name
    manager.phone = normalized_phone
    manager.amo_user_id = amo_user_id
    await session.commit()
    await session.refresh(manager)
    return manager


def sales_manager_line(manager: SalesManager) -> str:
    status = "включен" if manager.enabled else "отключен"
    amo = str(manager.amo_user_id) if manager.amo_user_id else "не указан"
    return f"{manager.sort_order}. {manager.name} - {manager.phone} - amoCRM ID: {amo} - {status}"

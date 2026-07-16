from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.enums import LeadStatus
from app.models import Lead, User
from app.services.sales_managers import assign_sales_manager_if_needed

logger = logging.getLogger(__name__)
_STATUS_MAP_CACHE: dict[int, dict[str, int]] = {}
_CONTACT_FIELD_CACHE: dict[str, dict[str, Any]] | None = None
_AGENT_SYNC_LOCKS: dict[int, asyncio.Lock] = {}

AGENT_PIPELINE_STATUSES = [
    "Подписался на бота",
    "Стал агентом",
    "Оставил данные клиента",
    "Начислен первый бонус",
]
AGENT_EVENT_STATUS_MAP = {
    "subscribed": "Подписался на бота",
    "became_agent": "Стал агентом",
    "client_data_submitted": "Оставил данные клиента",
    "first_bonus_awarded": "Начислен первый бонус",
}
AGENT_STAGE_RANK = {name: index for index, name in enumerate(AGENT_PIPELINE_STATUSES)}


def _is_configured(settings: Settings) -> bool:
    return bool(settings.amocrm_base_url and settings.amocrm_access_token and settings.amocrm_pipeline_id)


def _is_agent_pipeline_configured(settings: Settings) -> bool:
    return bool(settings.amocrm_base_url and settings.amocrm_access_token and settings.amocrm_agent_pipeline_id)


def enqueue_amocrm_sync(lead_id: int) -> None:
    settings = get_settings()
    if not _is_configured(settings):
        return
    try:
        asyncio.get_running_loop().create_task(sync_lead_to_amocrm_by_id(lead_id))
    except RuntimeError:
        logger.warning("No running event loop; skipped amoCRM sync for lead %s", lead_id)


async def sync_lead_to_amocrm_by_id(lead_id: int) -> None:
    from app.database import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            select(Lead)
            .where(Lead.id == lead_id)
            .options(
                selectinload(Lead.user).selectinload(User.referrer),
                selectinload(Lead.agent),
                selectinload(Lead.sales_manager),
            )
        )
        lead = result.scalar_one_or_none()
        if lead:
            await sync_lead_to_amocrm(session, lead)


async def sync_lead_to_amocrm(session: AsyncSession, lead: Lead) -> None:
    settings = get_settings()
    if not _is_configured(settings):
        return

    try:
        await session.refresh(lead, ["user", "agent", "sales_manager"])
        if lead.user:
            await session.refresh(lead.user, ["referrer"])
        async with AmoCrmClient(settings) as client:
            if lead.amo_lead_id:
                await _update_amocrm_lead(client, settings, lead)
            else:
                await _create_amocrm_lead(client, settings, lead)
        await session.commit()
    except Exception as exc:
        lead.amo_sync_status = "error"
        lead.amo_sync_error = str(exc)[:1000]
        lead.amo_synced_at = datetime.utcnow()
        await session.commit()
        logger.exception("Failed to sync lead %s to amoCRM", lead.id)


def enqueue_agent_amocrm_sync(user_id: int, event_type: str, payload: dict[str, Any] | None = None) -> None:
    settings = get_settings()
    if not _is_agent_pipeline_configured(settings):
        return
    if event_type not in AGENT_EVENT_STATUS_MAP:
        logger.warning("Skipped unknown agent amoCRM event %s for user %s", event_type, user_id)
        return
    try:
        asyncio.get_running_loop().create_task(
            sync_agent_to_amocrm_by_id(user_id, event_type, dict(payload or {}))
        )
    except RuntimeError:
        logger.warning("No running event loop; skipped agent amoCRM sync for user %s", user_id)


async def sync_agent_to_amocrm_by_id(
    user_id: int,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    from app.database import SessionLocal

    lock = _AGENT_SYNC_LOCKS.setdefault(user_id, asyncio.Lock())
    async with lock:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            if user:
                await sync_agent_event_to_amocrm(session, user, event_type, payload)


async def sync_agent_event_to_amocrm(
    session: AsyncSession,
    user: User,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    if not _is_agent_pipeline_configured(settings):
        return
    target_name = AGENT_EVENT_STATUS_MAP.get(event_type)
    if not target_name:
        raise ValueError(f"Unknown agent amoCRM event: {event_type}")

    payload = payload or {}
    pipeline_id = int(settings.amocrm_agent_pipeline_id)
    try:
        async with AmoCrmClient(settings) as client:
            status_map = await _pipeline_status_map_by_id(client, pipeline_id)
            target_status_id = status_map.get(target_name)
            if not target_status_id:
                raise RuntimeError(f"amoCRM agent pipeline status is missing: {target_name}")

            created = False
            moved = False
            if not user.amo_agent_lead_id:
                create_payload = [{
                    "name": _agent_deal_name(user),
                    "pipeline_id": pipeline_id,
                    "status_id": target_status_id,
                    "request_id": f"a7_agent_{user.platform}_{user.id}",
                    "tags_to_add": [
                        {"name": "a7consult-bot"},
                        {"name": "реферальная программа"},
                        {"name": user.platform or "bot"},
                    ],
                    "_embedded": {"contacts": [_agent_contact_payload(user)]},
                }]
                data = await client.request("POST", "/api/v4/leads/complex", json=create_payload)
                created_data = data[0] if isinstance(data, list) and data else {}
                user.amo_agent_lead_id = _as_int(created_data.get("id"))
                user.amo_agent_contact_id = _extract_contact_id(created_data)
                if not user.amo_agent_lead_id:
                    raise RuntimeError("amoCRM response did not include agent lead id")
                user.amo_agent_status_id = target_status_id
                # Persist the remote IDs before secondary contact/note requests. If one of those
                # requests fails, a later retry updates this deal instead of creating a duplicate.
                user.amo_agent_sync_status = "syncing"
                user.amo_agent_sync_error = None
                user.amo_agent_synced_at = datetime.utcnow()
                await session.commit()
                created = True
            else:
                current = await client.get_lead(int(user.amo_agent_lead_id))
                if _as_int(current.get("pipeline_id")) != pipeline_id:
                    raise RuntimeError("amoCRM agent lead is outside the configured agent pipeline; skipped")
                user.amo_agent_contact_id = user.amo_agent_contact_id or _extract_contact_id(current)
                current_status_id = _as_int(current.get("status_id"))
                current_name = next((name for name, status_id in status_map.items() if status_id == current_status_id), None)
                update_payload: dict[str, Any] = {"name": _agent_deal_name(user)}
                if current_name in AGENT_STAGE_RANK and AGENT_STAGE_RANK[target_name] > AGENT_STAGE_RANK[current_name]:
                    update_payload["status_id"] = target_status_id
                    user.amo_agent_status_id = target_status_id
                    moved = True
                else:
                    user.amo_agent_status_id = current_status_id
                await client.request("PATCH", f"/api/v4/leads/{user.amo_agent_lead_id}", json=update_payload)

            if user.amo_agent_contact_id:
                await client.request(
                    "PATCH",
                    f"/api/v4/contacts/{user.amo_agent_contact_id}",
                    json=_agent_contact_payload(user),
                )

            record_every_event = (
                event_type in {"client_data_submitted", "first_bonus_awarded"}
                and not payload.get("_backfill")
            )
            if created or moved or record_every_event:
                await _add_lead_note(
                    client,
                    int(user.amo_agent_lead_id),
                    _agent_event_note(user, event_type, payload),
                )

        user.amo_agent_sync_status = "synced"
        user.amo_agent_sync_error = None
        user.amo_agent_synced_at = datetime.utcnow()
        await session.commit()
    except Exception as exc:
        user.amo_agent_sync_status = "error"
        user.amo_agent_sync_error = str(exc)[:1000]
        user.amo_agent_synced_at = datetime.utcnow()
        await session.commit()
        logger.exception("Failed to sync agent user %s event %s to amoCRM", user.id, event_type)


def _agent_deal_name(user: User) -> str:
    source = "MAX" if user.platform == "max" else "Telegram"
    identity = f"@{user.username}" if user.username else _user_name(user)
    return f"Агент {source} - {identity or user.platform_user_id or user.id}"


def _agent_contact_payload(user: User) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": _user_name(user) or f"Агент {user.id}"}
    if user.phone:
        payload["custom_fields_values"] = [
            {"field_code": "PHONE", "values": [{"value": user.phone, "enum_code": "WORK"}]}
        ]
    return payload


def _agent_event_note(user: User, event_type: str, payload: dict[str, Any]) -> str:
    event_labels = {
        "subscribed": "Пользователь запустил бот",
        "became_agent": "Пользователь стал агентом реферальной программы",
        "client_data_submitted": "Агент оставил имя и телефон клиента",
        "first_bonus_awarded": "Агенту начислен бонус",
    }
    lines = [
        event_labels[event_type],
        f"ID пользователя в боте: {user.id}",
        f"Платформа: {'MAX' if user.platform == 'max' else 'Telegram'}",
        f"Username: {_username(user)}",
        f"Телефон агента: {user.phone or ''}",
    ]
    if event_type == "client_data_submitted":
        lines.extend([
            f"ID клиентской заявки: {payload.get('lead_id') or ''}",
            f"Имя клиента: {payload.get('client_name') or ''}",
            f"Телефон клиента: {payload.get('phone') or ''}",
        ])
    if event_type == "first_bonus_awarded":
        lines.extend([
            f"ID бонуса: {payload.get('bonus_id') or ''}",
            f"Сумма: {payload.get('amount') or ''} руб.",
            f"Комментарий: {payload.get('comment') or ''}",
        ])
    return "\n".join(lines)


async def ensure_sales_manager_assignment(session: AsyncSession, lead: Lead):
    manager = await assign_sales_manager_if_needed(session, lead)
    await session.commit()
    if not manager:
        return None

    settings = get_settings()
    if not _is_configured(settings):
        return manager

    if not lead.amo_lead_id:
        await sync_lead_to_amocrm(session, lead)
        return manager

    try:
        async with AmoCrmClient(settings) as client:
            current = await client.get_lead(int(lead.amo_lead_id))
            if _as_int(current.get("pipeline_id")) != settings.amocrm_pipeline_id:
                raise RuntimeError("amoCRM lead is outside the configured pipeline; skipped responsible assignment")
            if manager.amo_user_id:
                # Deliberately update only the responsible user. Omitting pipeline_id and status_id
                # guarantees that manager assignment cannot move the deal to another stage or pipeline.
                await client.request(
                    "PATCH",
                    f"/api/v4/leads/{lead.amo_lead_id}",
                    json={"responsible_user_id": int(manager.amo_user_id)},
                )
            lead.amo_pipeline_id = _as_int(current.get("pipeline_id"))
            lead.amo_status_id = _as_int(current.get("status_id"))
            await session.commit()
    except Exception:
        logger.exception("Failed to assign responsible sales manager for lead %s", lead.id)
    return manager


async def add_agent_followup_answer_note(session: AsyncSession, lead: Lead, label: str, answer: str) -> bool:
    settings = get_settings()
    if not _is_configured(settings):
        return False

    try:
        await session.refresh(lead, ["user", "agent", "sales_manager"])
        if lead.user:
            await session.refresh(lead.user, ["referrer"])
        if not lead.amo_lead_id:
            await sync_lead_to_amocrm(session, lead)
            await session.refresh(lead, ["user", "agent", "sales_manager"])
        if not lead.amo_lead_id:
            return False

        async with AmoCrmClient(settings) as client:
            current = await client.get_lead(int(lead.amo_lead_id))
            if _as_int(current.get("pipeline_id")) != settings.amocrm_pipeline_id:
                raise RuntimeError("amoCRM lead is outside the configured pipeline; skipped followup note")
            await _add_lead_note(client, int(lead.amo_lead_id), _followup_answer_note(lead, label, answer))
        return True
    except Exception:
        logger.exception("Failed to add followup answer note for lead %s", lead.id)
        return False


def _followup_answer_note(lead: Lead, label: str, answer: str) -> str:
    lines = [
        "Ответ агента по предупреждению клиента",
        f"ID заявки в боте: {lead.id}",
        f"Клиент: {_client_name(lead)}",
        f"{label}: {answer}",
    ]
    if lead.sales_manager:
        lines.extend(
            [
                "",
                "Назначенный менеджер продаж",
                f"Имя: {lead.sales_manager.name}",
                f"Телефон: {lead.sales_manager.phone}",
                f"amoCRM user ID: {lead.sales_manager.amo_user_id or ''}",
            ]
        )
    return "\n".join(lines)


class AmoCrmClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = (settings.amocrm_base_url or "").rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "AmoCrmClient":
        headers = {
            "Authorization": f"Bearer {self.settings.amocrm_access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._session = aiohttp.ClientSession(headers=headers)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()

    async def request(self, method: str, path: str, **kwargs) -> Any:
        if not self._session:
            raise RuntimeError("amoCRM client is not opened")
        async with self._session.request(method, self.base_url + path, **kwargs) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"amoCRM API error {response.status}: {text[:500]}")
            if not text:
                return {}
            return await response.json()

    async def get_pipeline(self) -> dict[str, Any]:
        pipeline_id = self.settings.amocrm_pipeline_id
        return await self.request("GET", f"/api/v4/leads/pipelines/{pipeline_id}")

    async def get_lead(self, amo_lead_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/api/v4/leads/{amo_lead_id}?with=contacts")


async def _create_amocrm_lead(client: AmoCrmClient, settings: Settings, lead: Lead) -> None:
    status_id = await _status_id_for_local_status(client, settings, lead.status)
    payload = [_lead_payload(settings, lead, status_id)]
    data = await client.request("POST", "/api/v4/leads/complex", json=payload)
    created = data[0] if isinstance(data, list) and data else {}
    lead.amo_lead_id = _as_int(created.get("id"))
    lead.amo_contact_id = _extract_contact_id(created)
    lead.amo_pipeline_id = settings.amocrm_pipeline_id
    lead.amo_status_id = status_id
    lead.amo_sync_status = "synced" if lead.amo_lead_id else "unknown"
    lead.amo_sync_error = None if lead.amo_lead_id else "amoCRM response did not include lead id"
    lead.amo_synced_at = datetime.utcnow()
    if lead.amo_lead_id:
        await _ensure_contact_details(client, lead, lead.amo_contact_id)
        await _add_lead_note(client, int(lead.amo_lead_id), _lead_note(lead))


async def _update_amocrm_lead(client: AmoCrmClient, settings: Settings, lead: Lead) -> None:
    current = await client.get_lead(int(lead.amo_lead_id))
    if _as_int(current.get("pipeline_id")) != settings.amocrm_pipeline_id:
        raise RuntimeError("amoCRM lead is outside the configured pipeline; skipped")
    lead.amo_contact_id = lead.amo_contact_id or _extract_contact_id(current)

    payload: dict[str, Any] = {"name": _lead_name(lead)}
    status_id = _as_int(current.get("status_id"))
    if lead.status and lead.status != LeadStatus.NEW.value:
        requested_status_id = await _status_id_for_local_status(client, settings, lead.status)
        if requested_status_id:
            payload["status_id"] = requested_status_id
            status_id = requested_status_id
    await client.request("PATCH", f"/api/v4/leads/{lead.amo_lead_id}", json=payload)
    await _ensure_contact_details(client, lead, lead.amo_contact_id)
    await _add_lead_note(client, int(lead.amo_lead_id), _lead_note(lead))
    lead.amo_pipeline_id = settings.amocrm_pipeline_id
    lead.amo_status_id = status_id
    lead.amo_sync_status = "synced"
    lead.amo_sync_error = None
    lead.amo_synced_at = datetime.utcnow()


def _lead_payload(settings: Settings, lead: Lead, status_id: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": _lead_name(lead),
        "pipeline_id": settings.amocrm_pipeline_id,
        "request_id": f"bot_lead_{lead.id}",
        "tags_to_add": [{"name": "a7consult-bot"}, {"name": lead.platform or "bot"}, {"name": lead.type or "lead"}],
        "_embedded": {"contacts": [_contact_payload(lead)]},
    }
    if status_id:
        payload["status_id"] = status_id
    responsible_user_id = _responsible_user_id(lead)
    if responsible_user_id:
        payload["responsible_user_id"] = responsible_user_id
    return payload


def _responsible_user_id(lead: Lead) -> int | None:
    if lead.sales_manager and lead.sales_manager.enabled and lead.sales_manager.amo_user_id:
        return int(lead.sales_manager.amo_user_id)
    return None


def _contact_payload(lead: Lead) -> dict[str, Any]:
    contact: dict[str, Any] = {"name": _client_name(lead)}
    phone = _lead_phone(lead)
    if phone:
        contact["custom_fields_values"] = [
            {
                "field_code": "PHONE",
                "values": [{"value": phone, "enum_code": "WORK"}],
            }
        ]
    return contact


async def _ensure_contact_details(client: AmoCrmClient, lead: Lead, amo_contact_id: int | None) -> None:
    if not amo_contact_id:
        return
    custom_fields = await _contact_custom_fields(client, lead)
    payload = {
        "name": _client_name(lead),
        "custom_fields_values": custom_fields,
    }
    if not custom_fields:
        payload.pop("custom_fields_values")
    await client.request("PATCH", f"/api/v4/contacts/{amo_contact_id}", json=payload)


async def _contact_custom_fields(client: AmoCrmClient, lead: Lead) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    used_field_ids: set[int] = set()
    phone = _lead_phone(lead)
    if phone:
        fields.append({"field_code": "PHONE", "values": [{"value": phone, "enum_code": "WORK"}]})

    amo_fields = await _contact_fields(client)
    for field_name, value in _contact_extra_values(lead).items():
        if not value:
            continue
        field = _find_contact_field(amo_fields, field_name)
        if field:
            field_id = int(field["id"])
            if field_id in used_field_ids:
                continue
            used_field_ids.add(field_id)
            fields.append({"field_id": field["id"], "values": [{"value": value}]})
    return fields


async def _contact_fields(client: AmoCrmClient) -> dict[str, dict[str, Any]]:
    global _CONTACT_FIELD_CACHE
    if _CONTACT_FIELD_CACHE is not None:
        return _CONTACT_FIELD_CACHE
    data = await client.request("GET", "/api/v4/contacts/custom_fields")
    fields = data.get("_embedded", {}).get("custom_fields", [])
    result: dict[str, dict[str, Any]] = {}
    for field in fields:
        name = str(field.get("name") or "").strip().lower()
        code = str(field.get("code") or "").strip().lower()
        if name:
            result[name] = field
        if code:
            result[code] = field
    _CONTACT_FIELD_CACHE = result
    return result


def _find_contact_field(fields: dict[str, dict[str, Any]], name_or_code: str) -> dict[str, Any] | None:
    return fields.get(name_or_code.strip().lower())


def _lead_name(lead: Lead) -> str:
    source = "MAX" if lead.platform == "max" else "Telegram"
    recommender = _recommender(lead)
    recommender_name = _user_name(recommender)
    if lead.type == "agent_client" and recommender_name:
        return f"Клиент от агента {recommender_name} - #{lead.id} - {_client_name(lead)}"

    type_label = {
        "consultation": "консультация",
        "question": "вопрос",
        "agent_client": "клиент от агента",
    }.get(lead.type or "", "заявка")
    parts = [source, type_label, f"#{lead.id}"]
    client_name = _client_name(lead)
    if client_name:
        parts.append(client_name)
    return " - ".join(parts)


def _lead_note(lead: Lead) -> str:
    lines = [
        "Заявка из бота",
        f"ID заявки: {lead.id}",
        f"Платформа: {'MAX' if lead.platform == 'max' else 'Telegram'}",
        f"Тип заявки: {lead.type or ''}",
        f"Статус в боте: {lead.status or ''}",
        "",
        "Клиент",
        f"Имя: {_client_name(lead)}",
        f"Username: {_username(lead.user)}",
        f"Телефон: {lead.phone or (lead.user.phone if lead.user else '') or ''}",
    ]
    if lead.question_text:
        lines.extend(["", "Вопрос", lead.question_text])
    if lead.comment:
        lines.extend(["", "Комментарий", lead.comment])

    recommender = _recommender(lead)
    if recommender:
        lines.extend(
            [
                "",
                "Рекомендатель / агент",
                f"Имя: {_user_name(recommender)}",
                f"Username: {_username(recommender)}",
                f"Телефон: {recommender.phone or ''}",
            ]
        )
    if lead.relation_to_agent:
        lines.append(f"Кем приходится рекомендателю: {lead.relation_to_agent}")
    if lead.agent_payout_phone:
        lines.append(f"Телефон агента для выплаты: {lead.agent_payout_phone}")
    return "\n".join(line for line in lines if line is not None)


async def _add_lead_note(client: AmoCrmClient, amo_lead_id: int, text: str) -> None:
    if not text.strip():
        return
    payload = [{"note_type": "common", "params": {"text": text[:20000]}}]
    await client.request("POST", f"/api/v4/leads/{amo_lead_id}/notes", json=payload)


def _client_name(lead: Lead) -> str:
    if lead.client_name:
        return lead.client_name
    user = lead.user
    if not user:
        return f"Lead {lead.id}"
    name = " ".join(part for part in [user.first_name, user.last_name] if part)
    return name or user.username or str(user.platform_user_id or user.telegram_id or lead.id)


def _lead_phone(lead: Lead) -> str:
    return lead.phone or (lead.user.phone if lead.user else "") or ""


def _contact_extra_values(lead: Lead) -> dict[str, str]:
    user = lead.user
    values: dict[str, str] = {
        "Имя": _client_name(lead),
        "ФИО (полностью)": _client_name(lead),
        "Source phone": _lead_phone(lead),
    }
    if not user:
        return values

    username = (user.username or "").lstrip("@")
    platform_user_id = str(user.platform_user_id or "")
    telegram_id = str(user.telegram_id or platform_user_id or "") if user.platform == "telegram" else ""
    max_id = platform_user_id if user.platform == "max" else ""

    if user.platform == "telegram":
        values.update(
            {
                "TelegramUsername_WZ": username,
                "Telegram username": username,
                "TelegramId_WZ": telegram_id,
                "Telegram ID": telegram_id,
                "TGUSERNAME": username,
                "TGID": telegram_id,
            }
        )
        if username:
            values["Telegram"] = f"https://t.me/{username}"
    elif user.platform == "max":
        values.update(
            {
                "MaxId_WZ": max_id,
                "Max ID": max_id,
                "MAXID": max_id,
                "Max User ID": max_id,
                "MAXUSERID": max_id,
            }
        )
    return values


def _recommender(lead: Lead) -> User | None:
    return lead.agent or (lead.user.referrer if lead.user else None)


def _user_name(user: User | None) -> str:
    if not user:
        return ""
    return " ".join(part for part in [user.first_name, user.last_name] if part) or user.username or str(user.platform_user_id or user.telegram_id or "")


def _username(user: User | None) -> str:
    if not user:
        return ""
    if user.username:
        return f"@{user.username}"
    if user.platform == "max" and user.platform_user_id:
        return f"MAX ID {user.platform_user_id}"
    return ""


async def _status_id_for_local_status(client: AmoCrmClient, settings: Settings, status: str | None) -> int | None:
    status_map = await _pipeline_status_map(client, settings)
    regular_statuses = [item for item in status_map.values() if item not in {142, 143}]
    first_regular = regular_statuses[0] if regular_statuses else None
    second_regular = regular_statuses[1] if len(regular_statuses) > 1 else first_regular

    if status == LeadStatus.IN_PROGRESS.value:
        return _allowed_status(settings.amocrm_status_id_in_progress, status_map) or second_regular
    if status == LeadStatus.CLOSED.value:
        return _allowed_status(settings.amocrm_status_id_closed, status_map)
    if status == LeadStatus.CANCELED.value:
        return _allowed_status(settings.amocrm_status_id_canceled, status_map)
    return _allowed_status(settings.amocrm_status_id_new, status_map) or first_regular


async def amocrm_status_to_local_status(client: AmoCrmClient, settings: Settings, status_id: int | None) -> str | None:
    if not status_id:
        return None
    status_map = await _pipeline_status_map(client, settings)
    if status_id not in status_map.values():
        return None
    if status_id == settings.amocrm_status_id_closed:
        return LeadStatus.CLOSED.value
    if status_id == settings.amocrm_status_id_canceled:
        return LeadStatus.CANCELED.value
    if settings.amocrm_status_id_in_progress and status_id == settings.amocrm_status_id_in_progress:
        return LeadStatus.IN_PROGRESS.value
    if settings.amocrm_status_id_new and status_id == settings.amocrm_status_id_new:
        return LeadStatus.NEW.value

    regular_statuses = [item for item in status_map.values() if item not in {142, 143}]
    if regular_statuses and status_id == regular_statuses[0]:
        return LeadStatus.NEW.value
    if status_id in regular_statuses:
        return LeadStatus.IN_PROGRESS.value
    return None


async def _pipeline_status_map(client: AmoCrmClient, settings: Settings) -> dict[str, int]:
    pipeline_id = int(settings.amocrm_pipeline_id or 0)
    cached = _STATUS_MAP_CACHE.get(pipeline_id)
    if cached:
        return cached

    pipeline = await client.get_pipeline()
    statuses = pipeline.get("_embedded", {}).get("statuses", [])
    ordered = sorted(statuses, key=lambda item: item.get("sort", 0))
    status_map = {str(item.get("name") or item.get("id")): int(item["id"]) for item in ordered if item.get("id")}
    _STATUS_MAP_CACHE[pipeline_id] = status_map
    return status_map


async def _pipeline_status_map_by_id(client: AmoCrmClient, pipeline_id: int) -> dict[str, int]:
    cached = _STATUS_MAP_CACHE.get(pipeline_id)
    if cached:
        return cached

    pipeline = await client.request("GET", f"/api/v4/leads/pipelines/{pipeline_id}")
    statuses = pipeline.get("_embedded", {}).get("statuses", [])
    ordered = sorted(statuses, key=lambda item: item.get("sort", 0))
    status_map = {str(item.get("name") or item.get("id")): int(item["id"]) for item in ordered if item.get("id")}
    _STATUS_MAP_CACHE[pipeline_id] = status_map
    return status_map


def _allowed_status(status_id: int | None, status_map: dict[str, int]) -> int | None:
    if status_id and status_id in status_map.values():
        return status_id
    return None


def _extract_contact_id(data: dict[str, Any]) -> int | None:
    contact_id = _as_int(data.get("contact_id"))
    if contact_id:
        return contact_id
    contacts = data.get("_embedded", {}).get("contacts", [])
    if contacts:
        return _as_int(contacts[0].get("id"))
    return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

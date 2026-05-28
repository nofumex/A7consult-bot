from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class IncomingEvent:
    platform: str
    platform_user_id: str
    chat_id: str
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    text: str | None = None
    contact_phone: str | None = None
    callback_data: str | None = None
    callback_id: str | None = None
    raw_update: dict[str, Any] | None = None


def _dig(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _user_from_update(update: dict[str, Any]) -> dict[str, Any]:
    if update.get("update_type") == "message_callback":
        return (
            _dig(update, "callback", "user")
            or _dig(update, "callback", "from")
            or update.get("user")
            or {}
        )
    return (
        update.get("user")
        or _dig(update, "message", "sender")
        or _dig(update, "message", "from")
        or _dig(update, "callback", "user")
        or _dig(update, "callback", "from")
        or {}
    )


def _chat_id_from_update(update: dict[str, Any]) -> str | None:
    return str(
        update.get("chat_id")
        or _dig(update, "message", "recipient", "chat_id")
        or _dig(update, "message", "chat", "chat_id")
        or _dig(update, "message", "chat_id")
        or _dig(update, "callback", "chat_id")
        or ""
    ) or None


def _text_from_update(update: dict[str, Any]) -> str | None:
    return (
        _dig(update, "message", "body", "text")
        or _dig(update, "message", "text")
        or _dig(update, "callback", "payload")
        or _dig(update, "callback", "data")
    )


def _contact_phone(update: dict[str, Any]) -> str | None:
    attachments = _dig(update, "message", "body", "attachments") or _dig(update, "message", "attachments") or []
    for attachment in attachments:
        if attachment.get("type") != "contact":
            continue
        payload = attachment.get("payload") or {}
        vcf_info = payload.get("vcf_info") or ""
        for line in vcf_info.splitlines():
            if line.startswith("TEL"):
                return line.split(":", 1)[-1].strip()
        max_info = payload.get("max_info") or {}
        if max_info.get("phone"):
            return str(max_info["phone"])
    return None


def parse_update(update: dict[str, Any]) -> IncomingEvent | None:
    update_type = update.get("update_type")
    if update_type not in {"message_created", "message_callback", "bot_started", None}:
        return None

    user = _user_from_update(update)
    platform_user_id = user.get("user_id") or user.get("id")
    chat_id = _chat_id_from_update(update) or platform_user_id
    if not platform_user_id or not chat_id:
        return None

    callback = update.get("callback") or {}
    return IncomingEvent(
        platform="max",
        platform_user_id=str(platform_user_id),
        chat_id=str(chat_id),
        username=user.get("username"),
        first_name=user.get("first_name") or user.get("name"),
        last_name=user.get("last_name"),
        text="/start" if update_type == "bot_started" else _text_from_update(update),
        contact_phone=_contact_phone(update),
        callback_data=(callback.get("payload") or callback.get("data")) if update_type == "message_callback" else None,
        callback_id=callback.get("callback_id") or callback.get("id"),
        raw_update=update,
    )

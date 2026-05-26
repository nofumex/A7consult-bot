from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from os import getenv

from dotenv import load_dotenv


def _parse_int_set(raw: str | None) -> set[int]:
    if not raw:
        return set()
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


def _parse_str_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _parse_int(raw: str | None, default: int) -> int:
    try:
        return int(raw or default)
    except ValueError:
        return default


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on", "да"}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    max_bot_token: str
    run_telegram: bool
    run_max: bool
    max_api_base_url: str
    max_bot_link: str | None
    admin_ids: set[int]
    manager_ids: set[int]
    telegram_admin_ids: set[int]
    telegram_manager_ids: set[int]
    max_admin_ids: set[str]
    max_manager_ids: set[str]
    manager_chat_url: str | None
    agent_chat_url: str | None
    company_video_url: str | None
    reviews_url: str | None
    presentation_url: str | None
    manager_contact_text: str
    default_bonus_per_client: int
    second_level_bonus: int
    database_url: str
    drop_pending_updates: bool
    dev_id: int | None
    google_sheets_id: str | None
    google_sheets_worksheet: str
    google_service_account_file: str | None
    amocrm_base_url: str | None
    amocrm_access_token: str | None
    amocrm_pipeline_id: int | None
    amocrm_status_id_new: int | None
    amocrm_status_id_in_progress: int | None
    amocrm_status_id_closed: int | None
    amocrm_status_id_canceled: int | None
    agent_client_notification_delay_seconds: int

    @property
    def bot_token(self) -> str:
        return self.telegram_bot_token

    @property
    def staff_ids(self) -> set[int]:
        return self.telegram_admin_ids | self.telegram_manager_ids


@lru_cache
def get_settings() -> Settings:
    load_dotenv()
    legacy_admin_ids = _parse_int_set(getenv("ADMIN_IDS"))
    legacy_manager_ids = _parse_int_set(getenv("MANAGER_IDS"))
    telegram_admin_ids = _parse_int_set(getenv("TELEGRAM_ADMIN_IDS")) or legacy_admin_ids
    telegram_manager_ids = _parse_int_set(getenv("TELEGRAM_MANAGER_IDS")) or legacy_manager_ids
    return Settings(
        telegram_bot_token=(getenv("TELEGRAM_BOT_TOKEN") or getenv("BOT_TOKEN", "")).strip(),
        max_bot_token=getenv("MAX_BOT_TOKEN", "").strip(),
        run_telegram=_parse_bool(getenv("RUN_TELEGRAM"), True),
        run_max=_parse_bool(getenv("RUN_MAX"), True),
        max_api_base_url=(getenv("MAX_API_BASE_URL") or "https://botapi.max.ru").rstrip("/"),
        max_bot_link=getenv("MAX_BOT_LINK") or None,
        admin_ids=telegram_admin_ids,
        manager_ids=telegram_manager_ids,
        telegram_admin_ids=telegram_admin_ids,
        telegram_manager_ids=telegram_manager_ids,
        max_admin_ids=_parse_str_set(getenv("MAX_ADMIN_IDS")),
        max_manager_ids=_parse_str_set(getenv("MAX_MANAGER_IDS")),
        manager_chat_url=getenv("MANAGER_CHAT_URL") or None,
        agent_chat_url=getenv("AGENT_CHAT_URL") or None,
        company_video_url=getenv("COMPANY_VIDEO_URL") or None,
        reviews_url=getenv("REVIEWS_URL") or None,
        presentation_url=getenv("PRESENTATION_URL") or None,
        manager_contact_text=getenv("MANAGER_CONTACT_TEXT", "Напишите нашему менеджеру"),
        default_bonus_per_client=_parse_int(getenv("DEFAULT_BONUS_PER_CLIENT"), 10000),
        second_level_bonus=_parse_int(getenv("SECOND_LEVEL_BONUS"), 5000),
        database_url=getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db"),
        drop_pending_updates=_parse_bool(getenv("DROP_PENDING_UPDATES"), True),
        dev_id=_parse_int(getenv("DEV_ID"), 0) or None,
        google_sheets_id=getenv("GOOGLE_SHEETS_ID") or None,
        google_sheets_worksheet=getenv("GOOGLE_SHEETS_WORKSHEET", "Leads"),
        google_service_account_file=getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or None,
        amocrm_base_url=(getenv("AMOCRM_BASE_URL") or "").rstrip("/") or None,
        amocrm_access_token=getenv("AMOCRM_ACCESS_TOKEN") or None,
        amocrm_pipeline_id=_parse_int(getenv("AMOCRM_PIPELINE_ID"), 0) or None,
        amocrm_status_id_new=_parse_int(getenv("AMOCRM_STATUS_ID_NEW"), 0) or None,
        amocrm_status_id_in_progress=_parse_int(getenv("AMOCRM_STATUS_ID_IN_PROGRESS"), 0) or None,
        amocrm_status_id_closed=_parse_int(getenv("AMOCRM_STATUS_ID_CLOSED"), 142) or None,
        amocrm_status_id_canceled=_parse_int(getenv("AMOCRM_STATUS_ID_CANCELED"), 143) or None,
        agent_client_notification_delay_seconds=_parse_int(getenv("AGENT_CLIENT_NOTIFICATION_DELAY_SECONDS"), 60),
    )

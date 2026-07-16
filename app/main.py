from __future__ import annotations

import asyncio
import logging
import sys

from app.adapters.max.bot import run_max_bot
from app.adapters.telegram.bot import run_telegram_bot
from app.config import get_settings
from app.database import close_db, init_db
from app.services.agent_crm_backfill import run_agent_crm_backfill_once


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def main() -> None:
    setup_logging()
    settings = get_settings()

    await init_db()

    tasks = []
    if settings.run_telegram and settings.telegram_bot_token:
        tasks.append(run_telegram_bot(settings))
    else:
        logging.info("Telegram bot skipped: RUN_TELEGRAM=%s token_set=%s", settings.run_telegram, bool(settings.telegram_bot_token))

    if settings.run_max and settings.max_bot_token:
        tasks.append(run_max_bot(settings))
    else:
        logging.info("MAX bot skipped: RUN_MAX=%s token_set=%s", settings.run_max, bool(settings.max_bot_token))

    if not tasks:
        await close_db()
        raise RuntimeError("No bot tokens provided. Fill BOT_TOKEN/TELEGRAM_BOT_TOKEN or MAX_BOT_TOKEN.")

    tasks.append(run_agent_crm_backfill_once())

    try:
        await asyncio.gather(*tasks)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from app.adapters.max.keyboards import MaxKeyboard, to_attachments

logger = logging.getLogger(__name__)


class MaxBotClient:
    def __init__(self, token: str, base_url: str) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "MaxBotClient":
        self._session = aiohttp.ClientSession(headers={"Authorization": self.token})
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("MAX client session is not started")
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with self.session.request(method, url, **kwargs) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"MAX API error {response.status}: {payload}")
            return payload

    async def get_updates(
        self,
        marker: int | None = None,
        timeout: int = 30,
        limit: int = 100,
        types: tuple[str, ...] = ("message_created", "message_callback", "bot_started"),
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"timeout": timeout, "limit": limit, "types": ",".join(types)}
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params, timeout=timeout + 10)

    async def send_message(
        self,
        chat_id: str | int | None = None,
        user_id: str | int | None = None,
        text: str | None = None,
        keyboard: MaxKeyboard | None = None,
        attachments: list[dict] | None = None,
        format: str = "html",
    ) -> None:
        params: dict[str, Any] = {}
        if chat_id:
            params["chat_id"] = chat_id
        elif user_id:
            params["user_id"] = user_id
        else:
            raise ValueError("chat_id or user_id is required")

        body: dict[str, Any] = {"text": text or ""}
        keyboard_attachments = to_attachments(keyboard)
        body_attachments = attachments or []
        if keyboard_attachments or body_attachments:
            body["attachments"] = body_attachments + (keyboard_attachments or [])
        if format:
            body["format"] = format
        await self._request("POST", "/messages", params=params, json=body)

    async def answer_callback(self, callback_id: str | None, text: str | None = None) -> None:
        if not callback_id:
            return
        # Endpoint is isolated here because MAX callback answer API may change.
        for path in (f"/messages/callback/{callback_id}", "/messages/callback"):
            try:
                await self._request("POST", path, json={"callback_id": callback_id, "text": text or ""})
                return
            except Exception:
                logger.debug("MAX callback answer failed on %s", path, exc_info=True)
        return

    async def safe_send(self, *args: Any, **kwargs: Any) -> bool:
        try:
            await self.send_message(*args, **kwargs)
            return True
        except Exception:
            logger.exception("MAX send_message failed")
            await asyncio.sleep(0.2)
            return False

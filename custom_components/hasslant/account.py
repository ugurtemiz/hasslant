"""myVAILLANT account client, the integration boundary."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from myPyllant.api import MyPyllantAPI

_LOGGER = logging.getLogger(__name__)

# The access token dies inside an hour. A later quarter-past has to sign in
# again, or today's day total stays on the last figure that token could fetch.
_SESSION_SKEW = timedelta(minutes=3)


def open_account(username: str, password: str, brand: str, country: str | None = None):
    """Sign-in client for one myVAILLANT account. Username is the email."""
    return _Account(
        MyPyllantAPI(
            username=username, password=password, brand=brand, country=country
        )
    )


class _Account:
    def __init__(self, api: MyPyllantAPI) -> None:
        self._api = api

    async def login(self) -> None:
        await self._api.login()

    async def _ensure_session(self) -> None:
        """Sign in again when the access token is missing or about to expire."""
        now = datetime.now(timezone.utc)
        expires = self._api.oauth_session_expires
        if expires is not None and expires - _SESSION_SKEW > now:
            return
        session = self._api.oauth_session or {}
        if expires is not None and session.get("refresh_token"):
            try:
                await self._api.refresh_token()
            except Exception:
                _LOGGER.warning(
                    "myVAILLANT session refresh failed; signing in again",
                    exc_info=True,
                )
            else:
                return
        await self._api.login()

    async def aclose(self) -> None:
        session = self._api.aiohttp_session
        if session is not None and not session.closed:
            await session.close()

    async def get_systems(self):
        await self._ensure_session()
        async for system in self._api.get_systems():
            yield system

    async def get_data_by_device(self, device, resolution, start, end):
        await self._ensure_session()
        async for series in self._api.get_data_by_device(
            device, resolution, start, end
        ):
            yield series

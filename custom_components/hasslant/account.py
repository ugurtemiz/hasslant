"""myVAILLANT account client, the integration boundary."""

from __future__ import annotations

from myPyllant.api import MyPyllantAPI


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

    async def aclose(self) -> None:
        session = self._api.aiohttp_session
        if session is not None and not session.closed:
            await session.close()

    def __getattr__(self, name: str):
        return getattr(self._api, name)

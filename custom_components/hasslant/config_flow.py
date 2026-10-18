"""Config flow for signing in to a myVAILLANT account."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from myPyllant.http_client import (
    AuthenticationFailed,
    LoginEndpointInvalid,
    RealmInvalid,
)

from . import account
from .const import CONF_BRAND, CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_COUNTRY): str,
        vol.Required(CONF_BRAND): str,
    }
)


class HasslantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the myVAILLANT account and create one setup."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = account.open_account(
                username=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                brand=user_input[CONF_BRAND],
                country=user_input[CONF_COUNTRY],
            )
            try:
                await client.login()
            except (AuthenticationFailed, LoginEndpointInvalid, RealmInvalid):
                errors["base"] = "authentication_failed"
            except Exception:
                _LOGGER.exception("Unexpected error signing in to myVAILLANT")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title="Hasslant", data=user_input)
            finally:
                await client.aclose()

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

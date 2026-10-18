"""Hasslant integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from . import account
from .const import CONF_BRAND, CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .coordinator import HeatingDataCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one myVAILLANT account and fetch the heating reading."""
    client = account.open_account(
        username=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        brand=entry.data[CONF_BRAND],
        country=entry.data[CONF_COUNTRY],
    )
    await client.login()
    coordinator = HeatingDataCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": client,
        "coordinator": coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one myVAILLANT account."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    stored = hass.data[DOMAIN].pop(entry.entry_id)
    await stored["coordinator"].async_shutdown()
    await stored["api"].aclose()
    return unloaded

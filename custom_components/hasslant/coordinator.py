"""Fetch homes and the heating day total."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from myPyllant.enums import DeviceDataBucketResolution

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HEATING = "HEATING"
CONSUMED_ELECTRICAL_ENERGY = "CONSUMED_ELECTRICAL_ENERGY"
_KILOWATT_HOUR = Decimal("0.001")


def _is_heating_electricity(series) -> bool:
    return (
        series.operation_mode == HEATING
        and series.value_type == CONSUMED_ELECTRICAL_ENERGY
    )


def _kilowatt_hours(watt_hours: list[float]) -> Decimal | None:
    """Sum watt-hours, then convert and round once to three decimal places."""
    if not watt_hours:
        return None
    total = sum((Decimal(str(value)) for value in watt_hours), Decimal(0))
    return (total / Decimal(1000)).quantize(_KILOWATT_HOUR, rounding=ROUND_HALF_UP)


class HeatingDataCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """One myVAILLANT account's heating readings."""

    def __init__(self, hass: HomeAssistant, api) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.api = api

    async def _async_update_data(self) -> list[dict[str, Any]]:
        homes: list[dict[str, Any]] = []
        async for system in self.api.get_systems():
            primary = next(
                (
                    device
                    for device in system.devices
                    if device.type == "primary_heat_generator"
                ),
                None,
            )
            if primary is None or not any(
                _is_heating_electricity(series) for series in primary.data
            ):
                continue
            for series in primary.data:
                series.skip_data_update = not _is_heating_electricity(series)
            now = datetime.now(system.timezone)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            watt_hours: list[float] = []
            async for series in self.api.get_data_by_device(
                primary, DeviceDataBucketResolution.HOUR, start, end
            ):
                if not _is_heating_electricity(series):
                    continue
                for bucket in series.data:
                    if bucket.value is None or bucket.end_date > now:
                        continue
                    watt_hours.append(bucket.value)
            home_name = system.home.home_name or system.home.nomenclature
            homes.append(
                {
                    "system_id": system.id,
                    "home_name": home_name,
                    "day_total": _kilowatt_hours(watt_hours),
                }
            )
        return homes

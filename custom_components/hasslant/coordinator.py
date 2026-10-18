"""Fetch homes and the heating day total."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from myPyllant.enums import DeviceDataBucketResolution

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

HEATING = "HEATING"
CONSUMED_ELECTRICAL_ENERGY = "CONSUMED_ELECTRICAL_ENERGY"
# myPyllant copies the system payload key onto Device.type. A secondary heat
# generator arrives as the plural key, not the singular domain name.
_HEAT_GENERATOR_TYPES = frozenset(
    {
        "primary_heat_generator",
        "secondary_heat_generator",
        "secondary_heat_generators",
    }
)
_KILOWATT_HOUR = Decimal("0.001")


def _is_heating_electricity(series) -> bool:
    """Heating electricity, on the catalog (``value_type``) or buckets (``energy_type``)."""
    return series.operation_mode == HEATING and (
        getattr(series, "value_type", None) == CONSUMED_ELECTRICAL_ENERGY
        or getattr(series, "energy_type", None) == CONSUMED_ELECTRICAL_ENERGY
    )


def _catalog_requests_heating_electricity(series) -> bool:
    """The catalog series to request. ``skip_data_update`` follows ``value_type``."""
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


def _next_midnight(now: datetime) -> datetime:
    """The next midnight on the clock that produced ``now``."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start + timedelta(days=1)


def _next_quarter_past(now: datetime) -> datetime:
    """The next 15 minutes past the hour on the clock that produced ``now``."""
    candidate = now.replace(minute=15, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(hours=1)
    return candidate


class HeatingDataCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """One myVAILLANT account's heating readings."""

    def __init__(self, hass: HomeAssistant, api) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.api = api
        self._midnight_unsubs: dict[str, Any] = {}
        self._quarter_unsubs: dict[str, Any] = {}

    async def async_shutdown(self) -> None:
        """Cancel the home-clock listeners."""
        for unsub in (*self._midnight_unsubs.values(), *self._quarter_unsubs.values()):
            unsub()
        self._midnight_unsubs.clear()
        self._quarter_unsubs.clear()
        await super().async_shutdown()

    def _schedule_midnight(self, system_id: str, timezone) -> None:
        """Withdraw yesterday's day total at midnight in the home's timezone."""
        previous = self._midnight_unsubs.pop(system_id, None)
        if previous is not None:
            previous()
        when = _next_midnight(datetime.now(timezone))

        @callback
        def _on_midnight(_utc_now: datetime) -> None:
            self._withdraw_day_total(system_id)

        self._midnight_unsubs[system_id] = async_track_point_in_utc_time(
            self.hass, _on_midnight, when
        )

    def _schedule_quarter_past(self, system_id: str, timezone) -> None:
        """Refresh about 15 minutes after each hour closes, on the home's clock."""
        previous = self._quarter_unsubs.pop(system_id, None)
        if previous is not None:
            previous()
        when = _next_quarter_past(datetime.now(timezone))

        async def _on_quarter_past(_utc_now: datetime) -> None:
            await self._refresh_home(system_id)

        self._quarter_unsubs[system_id] = async_track_point_in_utc_time(
            self.hass, _on_quarter_past, when
        )

    @callback
    def _withdraw_day_total(self, system_id: str) -> None:
        """The calendar day changed, so yesterday's day total is no longer today's."""
        withdrawn = []
        for home in self.data:
            if home["system_id"] == system_id:
                withdrawn.append(
                    {
                        **home,
                        "day_total": None,
                        "day": datetime.now(home["timezone"]).date(),
                    }
                )
            else:
                withdrawn.append(home)
        self.async_set_updated_data(withdrawn)

    def _schedule_home_clocks(self, homes: list[dict[str, Any]]) -> None:
        for home in homes:
            self._schedule_midnight(home["system_id"], home["timezone"])
            self._schedule_quarter_past(home["system_id"], home["timezone"])

    def _readings_after_failed_refresh(self) -> list[dict[str, Any]]:
        """Keep today's day total. A new calendar day has nothing to keep."""
        retained = []
        for home in self.data:
            today = datetime.now(home["timezone"]).date()
            if home["day"] == today and home["day_total"] is not None:
                retained.append(home)
            else:
                retained.append({**home, "day_total": None, "day": today})
        return retained

    async def _async_update_data(self) -> list[dict[str, Any]]:
        try:
            homes = await self._fetch_homes()
        except Exception:
            _LOGGER.warning("Heating day total refresh failed", exc_info=True)
            if not self.data:
                raise
            homes = self._readings_after_failed_refresh()
        self._schedule_home_clocks(homes)
        return homes

    async def _refresh_home(self, system_id: str) -> None:
        """Recompute one home. Other homes keep the day total they already show."""
        try:
            fetched = await self._fetch_homes(system_id)
        except Exception:
            _LOGGER.warning("Heating day total refresh failed", exc_info=True)
            if not self.data:
                return
            fetched = [
                home
                for home in self._readings_after_failed_refresh()
                if home["system_id"] == system_id
            ]
        updated = next(
            (home for home in fetched if home["system_id"] == system_id), None
        )
        merged: list[dict[str, Any]] = []
        found = False
        for home in self.data or []:
            if home["system_id"] == system_id:
                found = True
                merged.append(updated if updated is not None else home)
            else:
                merged.append(home)
        if not found and updated is not None:
            merged.append(updated)
        scheduled = updated
        if scheduled is None and found:
            scheduled = next(
                home for home in merged if home["system_id"] == system_id
            )
        if scheduled is not None:
            self._schedule_midnight(scheduled["system_id"], scheduled["timezone"])
            self._schedule_quarter_past(scheduled["system_id"], scheduled["timezone"])
        self.async_set_updated_data(merged)

    async def _fetch_homes(self, system_id: str | None = None) -> list[dict[str, Any]]:
        homes: list[dict[str, Any]] = []
        async for system in self.api.get_systems():
            if system_id is not None and system.id != system_id:
                continue
            heat_generators = [
                device
                for device in system.devices
                if device.type in _HEAT_GENERATOR_TYPES
                and any(
                    _is_heating_electricity(series) for series in device.data
                )
            ]
            if not heat_generators:
                continue
            now = datetime.now(system.timezone)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            watt_hours: list[float] = []
            for heat_generator in heat_generators:
                for series in heat_generator.data:
                    series.skip_data_update = (
                        not _catalog_requests_heating_electricity(series)
                    )
                async for series in self.api.get_data_by_device(
                    heat_generator, DeviceDataBucketResolution.HOUR, start, end
                ):
                    if not _is_heating_electricity(series):
                        continue
                    for bucket in series.data:
                        if (
                            bucket.value is None
                            or bucket.end_date <= start
                            or bucket.end_date > now
                        ):
                            continue
                        watt_hours.append(bucket.value)
            home_name = system.home.home_name or system.home.nomenclature
            homes.append(
                {
                    "system_id": system.id,
                    "home_name": home_name,
                    "day_total": _kilowatt_hours(watt_hours),
                    "timezone": system.timezone,
                    "day": start.date(),
                }
            )
        return homes

"""Heating day total reading."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeatingDataCoordinator, HomeReading


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one heating reading per home, including homes that appear later."""
    coordinator: HeatingDataCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    seen: set[str] = set()

    @callback
    def _add_new_homes() -> None:
        fresh = []
        for home in coordinator.data or ():
            if home.system_id in seen:
                continue
            seen.add(home.system_id)
            fresh.append(HeatingDayTotalSensor(coordinator, home))
        if fresh:
            async_add_entities(fresh)

    coordinator.async_add_listener(_add_new_homes)
    _add_new_homes()


class HeatingDayTotalSensor(CoordinatorEntity[HeatingDataCoordinator], SensorEntity):
    """Today's heating day total for one home."""

    _attr_has_entity_name = True
    _attr_name = "Consumed electrical energy heating"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HeatingDataCoordinator, home: HomeReading) -> None:
        super().__init__(coordinator)
        self._system_id = home.system_id
        self._attr_unique_id = home.system_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, home.system_id)},
            name=home.home_name,
        )

    @property
    def available(self) -> bool:
        """A series with no day total is unavailable, not an unknown number."""
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        home = self._reading()
        if home is None:
            return None
        return home.day_total

    def _reading(self) -> HomeReading | None:
        for home in self.coordinator.data or ():
            if home.system_id == self._system_id:
                return home
        return None

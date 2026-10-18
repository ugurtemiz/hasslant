"""Heating day total reading."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeatingDataCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one heating reading per home."""
    coordinator: HeatingDataCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities(
        HeatingDayTotalSensor(coordinator, home) for home in coordinator.data
    )


class HeatingDayTotalSensor(CoordinatorEntity[HeatingDataCoordinator], SensorEntity):
    """Today's heating day total for one home."""

    _attr_has_entity_name = True
    _attr_name = "Consumed electrical energy heating"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_state_class = None

    def __init__(self, coordinator: HeatingDataCoordinator, home: dict) -> None:
        super().__init__(coordinator)
        self._system_id = home["system_id"]
        self._attr_unique_id = home["system_id"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, home["system_id"])},
            name=home["home_name"],
        )

    @property
    def available(self) -> bool:
        """A series with no day total is unavailable, not an unknown number."""
        return super().available and self.native_value is not None

    @property
    def native_value(self):
        for home in self.coordinator.data:
            if home["system_id"] == self._system_id:
                return home["day_total"]
        return None

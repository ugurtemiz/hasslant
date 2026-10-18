"""Hasslant running under Home Assistant.

A stand-in myVAILLANT account supplies homes and hourly buckets. The only
observable is the heating reading, plus whether a setup was created.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from myPyllant.http_client import AuthenticationFailed
from myPyllant.models import DeviceData, DeviceDataBucket

DOMAIN = "hasslant"
EMAIL = "owner@example.com"
PASSWORD = "secret"
COUNTRY = "germany"
BRAND = "vaillant"
HOME_NAME = "Oak House"
HOME_ID = "home-oak"
HOME_TZ = ZoneInfo("Europe/Berlin")


class MyVaillantAccount:
    """Stands in for the myVAILLANT account at the integration boundary."""

    def __init__(self, *, reject: bool = False, homes=()):
        self.reject = reject
        self.homes = list(homes)
        self.fetches = []

    def __call__(self, username, password, brand, country=None):
        return _Client(self, username, password, brand, country)


class _Client:
    def __init__(self, account, username, password, brand, country):
        self.account = account
        self.username = username
        self.password = password
        self.brand = brand
        self.country = country

    async def login(self):
        if self.account.reject:
            raise AuthenticationFailed("rejected")

    async def aclose(self):
        return None

    async def get_systems(self):
        for home in self.account.homes:
            yield home

    async def get_data_by_device(self, device, resolution, start, end):
        """Yield series the way the library does, skipping those marked off."""
        for series in device.data:
            if getattr(series, "skip_data_update", False):
                continue
            self.account.fetches.append(
                {
                    "device_type": device.type,
                    "operation_mode": series.operation_mode,
                    "value_type": series.value_type,
                    "resolution": str(resolution),
                    "start": start,
                    "end": end,
                }
            )
            yield DeviceData(
                operation_mode=series.operation_mode,
                value_type=series.value_type,
                total_consumption=series.total_consumption,
                data=list(series.fetched_buckets),
            )


def _bucket(start: datetime, end: datetime, value):
    return DeviceDataBucket(start_date=start, end_date=end, value=value)


def _series(operation_mode, value_type, buckets=(), total_consumption=None):
    return SimpleNamespace(
        operation_mode=operation_mode,
        value_type=value_type,
        skip_data_update=False,
        total_consumption=total_consumption,
        data=[],
        fetched_buckets=list(buckets),
    )


def _device(device_type, series):
    return SimpleNamespace(type=device_type, data=list(series))


def _home(devices, *, name=HOME_NAME, system_id=HOME_ID):
    return SimpleNamespace(
        id=system_id,
        timezone=HOME_TZ,
        home=SimpleNamespace(home_name=name, nomenclature=name),
        devices=list(devices),
    )


def _heating_electricity(buckets=(), total_consumption=None):
    return _series(
        "HEATING",
        "CONSUMED_ELECTRICAL_ENERGY",
        buckets,
        total_consumption=total_consumption,
    )


async def _add_hasslant(hass, account: MyVaillantAccount):
    with patch("custom_components.hasslant.account.open_account", account):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "email": EMAIL,
                "password": PASSWORD,
                "country": COUNTRY,
                "brand": BRAND,
            },
        )
        await hass.async_block_till_done()
    return result


def _hasslant_entities(hass):
    registry = er.async_get(hass)
    return [entry for entry in registry.entities.values() if entry.platform == DOMAIN]


async def test_valid_myvaillant_account_creates_a_hasslant_setup(hass):
    account = MyVaillantAccount()
    with patch("custom_components.hasslant.account.open_account", account):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "email": EMAIL,
                "password": PASSWORD,
                "country": COUNTRY,
                "brand": BRAND,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hasslant"
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.name == "Hasslant"
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert dict(entries[0].data) == {
        "email": EMAIL,
        "password": PASSWORD,
        "country": COUNTRY,
        "brand": BRAND,
    }


async def test_rejected_credentials_do_not_create_a_setup(hass):
    account = MyVaillantAccount(reject=True)
    with patch("custom_components.hasslant.account.open_account", account):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "email": EMAIL,
                "password": "wrong",
                "country": COUNTRY,
                "brand": BRAND,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "authentication_failed"
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_one_home_shows_one_heating_reading(hass):
    primary = _device(
        "primary_heat_generator",
        [_heating_electricity(), _series("HEATING", "HEAT_GENERATED")],
    )
    companion = _device(
        "electric_backup_heater",
        [_heating_electricity()],
    )
    account = MyVaillantAccount(homes=[_home([companion, primary])])

    await _add_hasslant(hass, account)

    entities = _hasslant_entities(hass)
    assert len(entities) == 1
    state = hass.states.get(entities[0].entity_id)
    assert state.name == "Oak House Consumed electrical energy heating"


async def test_reading_stays_tied_to_the_home_when_devices_are_reordered(hass):
    companion = _device("electric_backup_heater", [_heating_electricity()])
    primary = _device("primary_heat_generator", [_heating_electricity()])
    dwelling = _home([companion, primary])
    account = MyVaillantAccount(homes=[dwelling])

    with patch("custom_components.hasslant.account.open_account", account):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "email": EMAIL,
                "password": PASSWORD,
                "country": COUNTRY,
                "brand": BRAND,
            },
        )
        await hass.async_block_till_done()
        before = _hasslant_entities(hass)
        assert len(before) == 1
        unique_id = before[0].unique_id
        entity_id = before[0].entity_id

        dwelling.devices = [primary, companion]
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    after = _hasslant_entities(hass)
    assert [(entity.unique_id, entity.entity_id) for entity in after] == [
        (unique_id, entity_id)
    ]


async def test_day_total_is_kilowatt_hours_to_three_decimal_places(hass, freezer):
    """600 Wh + 940 Wh is 1.540 kWh. The library total on the series is not that sum."""
    freezer.move_to("2026-10-18T14:20:00+02:00")
    midnight = datetime(2026, 10, 18, tzinfo=HOME_TZ)
    buckets = [
        _bucket(midnight, midnight + timedelta(hours=1), 600),
        _bucket(midnight + timedelta(hours=1), midnight + timedelta(hours=2), 940),
    ]
    primary = _device(
        "primary_heat_generator",
        [
            _heating_electricity(buckets, total_consumption=1999),
            _series(
                "HEATING",
                "HEAT_GENERATED",
                [_bucket(midnight, midnight + timedelta(hours=1), 8000)],
                total_consumption=8000,
            ),
        ],
    )
    await _add_hasslant(hass, MyVaillantAccount(homes=[_home([primary])]))

    state = hass.states.get(_hasslant_entities(hass)[0].entity_id)
    assert state.state == "1.540"


async def test_companion_device_heating_is_not_in_the_day_total(hass, freezer):
    freezer.move_to("2026-10-18T14:20:00+02:00")
    midnight = datetime(2026, 10, 18, tzinfo=HOME_TZ)
    hour = timedelta(hours=1)
    primary = _device(
        "primary_heat_generator",
        [_heating_electricity([_bucket(midnight, midnight + hour, 1540)])],
    )
    companion = _device(
        "electric_backup_heater",
        [_heating_electricity([_bucket(midnight, midnight + hour, 5000)])],
    )
    await _add_hasslant(
        hass, MyVaillantAccount(homes=[_home([companion, primary])])
    )

    state = hass.states.get(_hasslant_entities(hass)[0].entity_id)
    assert state.state == "1.540"


async def test_startup_fetch_asks_only_for_todays_heating_electricity(hass, freezer):
    freezer.move_to("2026-10-18T14:20:00+02:00")
    midnight = datetime(2026, 10, 18, tzinfo=HOME_TZ)
    hour = timedelta(hours=1)
    primary = _device(
        "primary_heat_generator",
        [
            _heating_electricity([_bucket(midnight, midnight + hour, 1540)]),
            _series("DOMESTIC_HOT_WATER", "CONSUMED_ELECTRICAL_ENERGY"),
            _series("HEATING", "HEAT_GENERATED"),
        ],
    )
    companion = _device(
        "electric_backup_heater",
        [_heating_electricity([_bucket(midnight, midnight + hour, 5000)])],
    )
    account = MyVaillantAccount(homes=[_home([companion, primary])])
    await _add_hasslant(hass, account)

    today = datetime(2026, 10, 18, tzinfo=HOME_TZ)
    assert account.fetches == [
        {
            "device_type": "primary_heat_generator",
            "operation_mode": "HEATING",
            "value_type": "CONSUMED_ELECTRICAL_ENERGY",
            "resolution": "HOUR",
            "start": today,
            "end": today + timedelta(days=1),
        }
    ]


async def test_reading_is_energy_in_kilowatt_hours_without_hourly_statistics(
    hass, freezer
):
    freezer.move_to("2026-10-18T14:20:00+02:00")
    midnight = datetime(2026, 10, 18, tzinfo=HOME_TZ)
    primary = _device(
        "primary_heat_generator",
        [
            _heating_electricity(
                [_bucket(midnight, midnight + timedelta(hours=1), 1540)]
            )
        ],
    )
    with patch(
        "homeassistant.components.recorder.statistics.async_add_external_statistics"
    ) as write_statistics:
        await _add_hasslant(hass, MyVaillantAccount(homes=[_home([primary])]))

    state = hass.states.get(_hasslant_entities(hass)[0].entity_id)
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["device_class"] == "energy"
    assert "state_class" not in state.attributes
    assert write_statistics.call_count == 0

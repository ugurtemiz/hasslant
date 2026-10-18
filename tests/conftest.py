import pathlib

import pytest

PROJECT_ROOT = pathlib.Path(__file__).parent.parent


@pytest.fixture
def hass_config_dir() -> str:
    """Home Assistant config dir that contains custom_components/hasslant."""
    return str(PROJECT_ROOT)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom components such as Hasslant in every test."""
    yield

"""Global fixtures for the HomGar integration."""
from unittest.mock import patch
import pytest

# This plugin provides all the standard Home Assistant fixtures
pytest_plugins = "pytest_homeassistant_custom_component"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir.
    
    This is required for testing custom components in Home Assistant.
    """
    yield

@pytest.fixture
def mock_setup_entry():
    """Override async_setup_entry."""
    with patch(
        "custom_components.homgar.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry

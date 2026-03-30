"""Test HomGar setup process."""
from unittest.mock import patch
import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

async def test_setup_entry(hass, mock_setup_entry):
    """Test setting up the integration."""
    entry = MockConfigEntry(
        domain="homgar",
        data={"username": "test@example.com", "password": "test-password"},
    )
    entry.add_to_hass(hass)
    
    # We trigger the setup of the config entry
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Assert that the fake entry was set up by our mock
    assert mock_setup_entry.called

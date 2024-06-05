"""Initialise Module for ECU Proxy."""

import logging

from homeassistant.components.persistent_notification import async_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, MESSAGE_EVENT
from .coordinator import APSystemCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]


class APSystemsECUProxyInvalidData(Exception):
    """Class provides passforward for error massages."""


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Get server params and start Proxy."""

    hass.data.setdefault(DOMAIN, {})

    coordinator = APSystemCoordinator(hass, config_entry)
    await coordinator.setup_socket_servers()

    hass.data[DOMAIN][config_entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    # Remove the config entry from the hass data object.
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id)

    # Return that unloading was successful.
    return unload_ok


# Enables users to delete a device
async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove inividual devices from the integration (ok)."""
    if device_entry is not None:
        # Notify the user that the device has been removed
        async_create(
            hass,
            f"The following device was removed from the system: {device_entry}",
            title="Device removal",
        )
        return True

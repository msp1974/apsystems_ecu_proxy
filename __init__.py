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
    config_entry.async_create_background_task(
        hass, coordinator.setup_socket_servers(), "Init Socket Servers"
    )
    hass.data[DOMAIN][config_entry.entry_id] = {"coordinator": coordinator}

    async def _async_complete_setup(self):
        """Complete setup of integration."""

        # Register the ECU device
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(DOMAIN, f"ecu_{coordinator.data.get('ecu-id')}")},
            manufacturer="APSystems",
            suggested_area="Roof",
            name=f"ECU {coordinator.data.get('ecu-id')}",
            model=f"{coordinator.data.get('model')}",
        )

        # Register the Inverter devices
        inverters = coordinator.data.get("inverters", {})
        for uid, inv_data in inverters.items():
            device_registry.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers={(DOMAIN, f"inverter_{uid}")},
                manufacturer="APSystems",
                suggested_area="Roof",
                name=f"Inverter {uid}",
                model=inv_data.get("model"),
            )

        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
        _LOGGER.warning("Data received")
        return True

    # Now we need to wait until we get a socket message before continuing setup.
    hass.bus.async_listen_once(MESSAGE_EVENT, _async_complete_setup)
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

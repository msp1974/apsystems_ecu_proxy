"""Example integration using DataUpdateCoordinator."""

import logging
from typing import Any

from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import MySocketAPI
from .const import DOMAIN, SOCKET_PORTS

_LOGGER = logging.getLogger(__name__)


class APSystemCoordinator(DataUpdateCoordinator):
    """My example coordinator."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        self.socket_servers: list[MySocketAPI] = []

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            # Set update method to None.
            update_method=None,
            # Do not set a polling interval as data will be pushed.
            # You can remove this line but left here for explanatory purposes.
            update_interval=None,
        )

    async def async_shutdown(self) -> None:
        """Run shutdown clean up."""
        for socket_server in self.socket_servers:
            # This might be blocking and if so do
            # await hass.async_run_in_executor(socket_server.shutdown())
            socket_server.stop()
        await super().async_shutdown()

    def get_device(self, identifiers):
        """Get device from device registry."""
        device_registry = dr.async_get(self.hass)
        return device_registry.async_get_device(identifiers)

    @callback
    def async_update_callback(self, data: dict[str, Any]):
        """Socket server callback."""

        # Set self.data so that sensor entities can use it when being created.
        self.data = data

        # If not a registered ECU
        if not self.get_device({(DOMAIN, f"ecu_{self.data.get("ecu-id")}")}):
            # New ECU, add sensors
            _LOGGER.debug("Found new ECU: %s", self.data.get("ecu-id"))
            # Send signal to sensor listener to add new ECU
            async_dispatcher_send(self.hass, f"{DOMAIN}_ecu_register", self.data)
        else:
            _LOGGER.debug("Update for known ECU: %s", self.data.get("ecu-id"))

        # Check for not registered inverters
        for uid, inverter in self.data.get("inverters", {}).items():
            if not self.get_device({(DOMAIN, f"inverter_{uid}")}):
                _LOGGER.debug("Found new Inverter: %s", inverter.get("uid"))

                # Add ecu-id to inverter data so that sensor can use this.
                inverter["ecu-id"] = self.data.get("ecu-id")

                # Send signal to sensor listener to add new Inverter
                async_dispatcher_send(
                    self.hass, f"{DOMAIN}_inverter_register", inverter
                )
            else:
                _LOGGER.debug("Update for known inverter: %s", inverter.get("uid"))

        # Trigger entities to update.
        self.async_set_updated_data(self.data)

    async def setup_socket_servers(self) -> None:
        """Initialise socket server."""
        host = await async_get_source_ip(self.hass)

        for port in SOCKET_PORTS:
            _LOGGER.debug("Creating server for port %s", port)
            server = MySocketAPI(host, port, self.async_update_callback)
            await server.start()
            self.socket_servers.append(server)

"""Example integration using DataUpdateCoordinator."""

import logging

from typing import Any

from .api import MySocketAPI
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import DOMAIN, HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import MESSAGE_EVENT, SOCKET_PORTS

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

    @callback
    async def async_update_callback(self, data: dict[str, Any]):
        """Socket server callback."""
        ecu_data = data
        _LOGGER.debug("DATA: %s", ecu_data)
        self.async_set_updated_data(ecu_data)

        # Fires an event which tells setup to finish
        # setup is listening once for this event.
        self.hass.bus.fire(
            MESSAGE_EVENT,
            ecu_data,
        )

    async def setup_socket_servers(self) -> None:
        """Initialise socket server."""
        host = await async_get_source_ip(self.hass)

        for port in SOCKET_PORTS:
            _LOGGER.debug("Creating server for port %s", port)
            server = MySocketAPI(host, port, self.async_update_callback)
            await server.start()
            self.socket_servers.append(server)

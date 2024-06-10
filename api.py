"""API to interact with APSystems ECU."""

import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
import re
import traceback
from typing import Any

from .const import EMA_HOST, MESSAGE_IGNORE_AGE, SEND_TO_EMA

_LOGGER = logging.getLogger(__name__)

ECU_MODELS_216 = {
    "2160": "ECU-R",
    "2162": "ECU-R Pro",
    "2163": "ECU-B",
}

ECU_MODELS_215 = {"215": "ECU-C"}


YC600_MODEL_CODES = ["406", "407", "408", "409", "703", "706"]
QS1_MODEL_CODES = ["801", "802", "806"]
YC1000_MODEL_CODES = ["501", "502", "503", "504"]

POWER_CHANNELS = [63, 83, 103, 123]
VOLTAGE_CHANNELS = [51, 71, 91, 111]
CURRENT_CHANNELS = [60, 80, 100, 120]

INVERTER_MODELS = [
    {
        "name": "YC600/DS3 series",
        "channels": 2,
        "model_codes": YC600_MODEL_CODES,
    },
    {
        "name": "QS1",
        "channels": 4,
        "model_codes": QS1_MODEL_CODES,
    },
    {
        "name": "YC1000/QT2",
        "channels": 4,
        "model_codes": YC1000_MODEL_CODES,
    },
]


class MySocketAPI:
    """API class."""

    def __init__(self, host: str, port: int, callback: Callable) -> None:
        """Initialsie API."""
        self.host = host
        self.port = port
        self.callback = callback
        self.server = None
        self.serve: bool = True

    async def start(self) -> bool:
        """Start listening socket server."""
        try:
            self.server = await asyncio.start_server(
                self.data_received, self.host, self.port
            )
            _LOGGER.debug("Server for port %s started", self.port)
        except OSError as ex:
            _LOGGER.debug("Error starting server - %s", ex)
            return False

    async def stop(self):
        """Stop server."""
        self.serve = False
        self.server.close()
        await self.server.wait_closed()
        _LOGGER.debug("Server for port %s stopped", self.port)

    async def data_received(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        """Decode received message."""

        _LOGGER.debug("Connected clients: %s", len(self.server.sockets))
        while self.serve:
            try:
                ecu = {}

                data = await reader.read(1024)
                if data == b"":
                    _LOGGER.debug("Client disconnected")
                    return

                message = data.decode("utf-8")

                addr = writer.get_extra_info("peername")
                _LOGGER.debug(
                    "From ECU @ %s on port %s - %s", addr[0], self.port, message
                )

                # Send data to EMA and send response from EMA to ECU
                # SEND_TO_EMA is used to stop sending for testing purposes.
                if SEND_TO_EMA:
                    response = await self.send_data_to_ema(self.port, data)
                    await self.send_data_to_ecu(writer, response)

                # Process data

                # If not message type we are interested in, do not process.
                if message[0:7] != "APS18AA":
                    _LOGGER.debug("Not interested in this message type for processing")
                    continue

                # Confirm valid message by confirming checksum
                # If not valid, do not process.
                if int(message[7:10]) != len(message) - 1:
                    _LOGGER.debug(
                        "Checksum error - sum: %s, len: %s",
                        message[7:10],
                        len(message) - 1,
                    )
                    continue

                # Get ECU data
                ecu["timestamp"] = datetime.strptime(message[60:74], "%Y%m%d%H%M%S")

                # We can get old messages from the ECU which provide older data to EMA.
                # We should ignore these if older than 10 mins.
                if (
                    message_age := (datetime.now() - ecu["timestamp"]).total_seconds()
                ) > MESSAGE_IGNORE_AGE:
                    _LOGGER.debug(
                        "Message told old, ignoring.  Age is %ss", int(message_age)
                    )
                    continue

                ecu["ecu-id"] = message[18:30]
                ecu["model"] = self.get_model(message[18:22])
                ecu["lifetime_energy"] = int(message[42:60]) / 10
                ecu["current_power"] = int(message[30:42]) / 100
                ecu["qty_of_online_inverters"] = int(message[74:77])
                ecu["inverters"] = self.get_inverters(ecu["ecu-id"], message)

                # Call callback to send the data
                self.callback(ecu)

            except ConnectionResetError:
                _LOGGER.warning("Error: Connection was reset")
            except Exception:
                _LOGGER.warning("Exception error with %s", traceback.format_exc())
                return None

        writer.close()
        await writer.wait_closed()

    def get_model(self, model_code: str) -> str:
        """Get model from model code."""
        if model := ECU_MODELS_216.get(model_code) or ECU_MODELS_215.get(
            model_code[:3]
        ):
            return model
        return "Unknown"

    def get_inverters(self, ecu_id: str, message: str) -> list[dict[str, Any]]:
        """Get inveters."""
        inverters = {}

        for idx, m in enumerate(
            re.finditer(r"END\d+", message)
        ):  # walk through inverters
            inverter = {}

            def msg_slice(start_pos: int, end_pos: int, m: re.Match = m) -> int:
                s = m.start()
                return message[s + start_pos : s + end_pos]

            inverter["uid"] = str(msg_slice(3, 15))
            inverter["index"] = idx
            inverter["temperature"] = int(msg_slice(25, 28)) - 100
            inverter["frequency"] = int(msg_slice(20, 25)) / 10

            model_code = str(msg_slice(3, 6))

            for model_refs in INVERTER_MODELS:
                if model_code in model_refs.get("model_codes"):
                    inverter["model"] = model_refs.get("name")
                    inverter["channel_qty"] = model_refs.get("channels")
                    inverter["power"] = [
                        int(msg_slice(offset, offset + 3))
                        for offset in POWER_CHANNELS[: model_refs.get("channels")]
                    ]
                    inverter["voltage"] = [
                        int(msg_slice(offset, offset + 3)) / 10
                        for offset in VOLTAGE_CHANNELS[: model_refs.get("channels")]
                    ]
                    inverter["current"] = [
                        int(msg_slice(offset, offset + 3)) / 100
                        for offset in CURRENT_CHANNELS[: model_refs.get("channels")]
                    ]

                    inverters[inverter.get("uid")] = inverter
        return inverters

    async def send_data_to_ema(self, port: int, data: bytes) -> bytes:
        """Send data over async socket."""
        reader, writer = await asyncio.open_connection(EMA_HOST, port)
        writer.write(data)
        await writer.drain()

        response = await reader.read(1024)
        _LOGGER.debug("From EMA: %s", response)
        writer.close()
        return response

    async def send_data_to_ecu(self, writer: asyncio.StreamWriter, data: bytes):
        """Send data to ECU."""
        writer.write(data)
        await writer.drain()

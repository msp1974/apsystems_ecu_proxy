import asyncio
from asyncio.trsock import TransportSocket
from collections.abc import Callable
from datetime import datetime
import logging
import re
import traceback
from typing import Any

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

    async def start(self) -> bool:
        """Start listening socket server."""
        try:
            self.server = await asyncio.start_server(
                self.data_received, self.host, self.port
            )
        except OSError as ex:
            _LOGGER.debug("Error starting server - %s", ex)
            return False

    def stop(self):
        """Stop server."""
        self.server.close()

    async def data_received(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        """Decode received message."""
        ecu = {}
        while True:
            _LOGGER.debug("Connected clients: %s", len(self.server.sockets))
            data = await reader.read(1024)
            if data == b"":
                _LOGGER.debug("Client disconnected")
                return
            try:
                message = data.decode("utf-8")
                # process data
                if message[0:7] == "APS18AA":
                    # analyse valid data strings by using the checksum and exit when invalid
                    if int(message[7:10]) != len(message) - 1:
                        _LOGGER.debug(
                            "Checksum error - sum: %s, len: %s, %s",
                            message[7:10],
                            len(message) - 1,
                            message,
                        )
                        return None
                    addr = writer.get_extra_info("peername")
                    _LOGGER.debug("From ECU @%s - %s", addr, message)
                    # Get ECU data
                    ecu["timestamp"] = str(
                        datetime.strptime(message[60:74], "%Y%m%d%H%M%S")
                    )
                    ecu["ecu-id"] = message[18:30]
                    ecu["model"] = self.get_model(message[18:22])
                    ecu["lifetime_energy"] = int(message[42:60]) / 10
                    ecu["daily_energy"] = 0
                    ecu["lifetime_energy_production"] = 0
                    ecu["current_power"] = int(message[30:42]) / 100
                    ecu["qty_of_online_inverters"] = int(message[74:77])
                    ecu["inverters"] = self.get_inverters(message)

                    # Do not update lifetime energy during maintenance
                    # Move this to sensor updates
                    """
                    if ecu_data.get("lifetime_energy") is None or int(
                        message[42:60]
                    ) / 10 > ecu_data.get("lifetime_energy"):
                        ecu_data["lifetime_energy"] = int(message[42:60]) / 10
                    """

                    response = await self.send_data_to_ema(self.port, data)
                    writer.write(response)
                    await writer.drain()

                    # Do not update sensors when inverters are down (ignore maintenance updates)
                    # TODO: Re-look at this - move to sensor logic
                    """
                    start_time = datetime.strptime(ecu.timestamp, "%Y-%m-%d %H:%M:%S")
                    time_diff_min = (datetime.now() - start_time).total_seconds() / 60
                    _LOGGER.debug(f"{time_diff_min:.2f} minutes: {ecu}")  # noqa: G004
                    if time_diff_min > 10:
                        ecu.current_power = 0
                        ecu.qty_of_online_inverters = 0
                        for inverter_info in ecu.inverters.values():
                            inverter_info.update(
                                {
                                    key: None
                                    for key in inverter_info
                                    if key not in ["uid", "model", "channel_qty"]
                                }
                            )
                        _LOGGER.debug("Timediff > 10 so keys are set to None: %s", ecu_data)
                    """

                    # Call callback to send the data
                    self.callback(ecu)
            except Exception:
                _LOGGER.warning("Exception error with %s", traceback.format_exc())
                return None

    def get_model(self, model_code: str) -> str:
        """Get model from model code."""
        if model := ECU_MODELS_216.get(model_code) or ECU_MODELS_215.get(
            model_code[:3]
        ):
            return model
        return "Unknown"

    def get_inverters(self, message: str) -> list[dict[str, Any]]:
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

    async def send_data_to_ema(self, port: int, data: bytes):
        """Send data over async socket."""
        reader, writer = await asyncio.open_connection("3.67.1.32", port)
        writer.write(data)
        await writer.drain()

        response = await reader.read(1024)
        _LOGGER.debug("From EMA: %s", response)
        return response

"""Helper functions."""

from dataclasses import dataclass, field
from datetime import datetime
import logging
import re
from typing import Any

from .const import (
    CURRENT_CHANNELS,
    ECU_MODELS_215,
    ECU_MODELS_216,
    INVERTER_MODELS,
    POWER_CHANNELS,
    VOLTAGE_CHANNELS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class Inverter:
    uid: str
    index: int
    temperature: int
    frequency: int
    model: str = None
    channels: int = 0
    power: list[int] = field(default_factory=list)
    voltage: list[float] = field(default_factory=list)
    current: list[float] = field(default_factory=list)


@dataclass
class ECU:
    timestamp: str
    ecu_id: str
    model: str
    lifetime_energy: int = 0
    hourly_energy_production: int = 0
    daily_energy_production: int = 0
    lifetime_energy_production: int = 0
    current_power: int = 0
    qty_of_online_inverters: int = 0
    inverters: dict[str, Inverter] = field(default_factory=dict)


def get_model(model_code: str) -> str:
    """Get model from model code."""
    if model := ECU_MODELS_216.get(model_code) or ECU_MODELS_215.get(model_code[:3]):
        return model
    return "Unknown"


def get_inverters(message: str) -> list[dict[str, Any]]:
    """Get inveters."""
    inverters = {}

    for idx, m in enumerate(re.finditer(r"END\d+", message)):  # walk through inverters
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

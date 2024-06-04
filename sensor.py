"""Handles sensor entities."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SOLAR_ICON
from .coordinator import APSystemCoordinator

_LOGGER = logging.getLogger(__name__)


# ===============================================================================
async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
):
    """Initialise sensor platform."""
    coordinator: APSystemCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]

    # Add ECU Sensors
    sensors = [
        APSystemECUPowerSensor(coordinator, "current_power", "Current Power"),
        APSystemECUEnergySensor(
            coordinator, "hourly_energy_production", "Hourly Energy Production"
        ),
        APSystemECUEnergySensor(
            coordinator, "daily_energy_production", "Daily Energy Production"
        ),
        APSystemECUEnergySensor(
            coordinator, "lifetime_energy_production", "Lifetime Energy Production"
        ),
        APSystemECUEnergySensor(coordinator, "lifetime_energy", "Lifetime Energy"),
        APSystemsECUBaseSensor(
            coordinator, "qty_of_online_inverters", "Inverters Online"
        ),
    ]

    # Add Inverter sensors
    for uid, inverter in coordinator.data.get("inverters").items():
        sensors.extend(
            [
                APSystemInvTemperatureSensor(
                    coordinator, "temperature", "Temperature", uid
                ),
                APSystemInvFrequencySensor(coordinator, "frequency", "Frequency", uid),
            ]
        )

        # Add inverter channel sensors
        for inv_ch in range(inverter.get("channel_qty", 0)):
            sensors.extend(
                [
                    APSystemInvChPowerSensor(
                        coordinator, "power", "Power", uid, inv_ch
                    ),
                    APSystemInvChVoltageSensor(
                        coordinator, "voltage", "Voltage", uid, inv_ch
                    ),
                    APSystemInvChCurrentSensor(
                        coordinator, "current", "Current", uid, inv_ch
                    ),
                ]
            )

    add_entities(sensors)


class APSystemsECUBaseSensor(CoordinatorEntity, SensorEntity):
    """Base APSystems sensor class."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, parameter: str, name: str) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.data = coordinator.data
        self._name = name
        self.parameter = parameter

    @property
    def unique_id(self):
        """Return unique id."""
        return f"{self.data.get("ecu-id")}_{self.parameter}"

    @property
    def name(self):
        """Return name."""
        return self._name

    @property
    def native_value(self):
        """Return native value."""
        return self.coordinator.data.get(self.parameter)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(identifiers={(DOMAIN, f"ecu_{self.data.get("ecu-id")}")})

    @property
    def extra_state_attributes(self):
        """Return extra attributes."""
        return {
            "ecu_id": f"{self.data.get("ecu-id")}",
            "last_update": f"{self.coordinator.data.get('timestamp')}",
        }


class APSystemsInvBaseSensor(APSystemsECUBaseSensor):
    """Inverter channel base class."""

    def __init__(
        self,
        coordinator,
        parameter: str,
        name: str,
        inverter_uid: str,
        inv_ch: int | None = None,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator, parameter, name)
        self.inv_uid = inverter_uid
        self.inv_ch = inv_ch

    @property
    def unique_id(self):
        """Return unique id."""
        return (
            f"{self.data.get("ecu-id")}_{self.inv_uid}_{self.parameter}_{self.inv_ch}"
            if self.inv_ch is not None
            else f"{self.data.get("ecu-id")}_{self.inv_uid}_{self.parameter}"
        )

    @property
    def name(self):
        """Return name."""
        return (
            f"{self._name} Ch {self.inv_ch + 1}"
            if self.inv_ch is not None
            else self._name
        )

    @property
    def native_value(self):
        """Return native value."""
        return (
            self.coordinator.data.get("inverters", {})
            .get(self.inv_uid, {})
            .get(self.parameter, [])[self.inv_ch]
            if self.inv_ch is not None
            else self.coordinator.data.get("inverters", {})
            .get(self.inv_uid, {})
            .get(self.parameter)
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(identifiers={(DOMAIN, f"inverter_{self.inv_uid}")})


class APSystemECUPowerSensor(APSystemsECUBaseSensor):
    """ECU Power sensor."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = SOLAR_ICON


class APSystemECUEnergySensor(APSystemsECUBaseSensor):
    """ECU Energy sensor."""

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = SOLAR_ICON


class APSystemInvFrequencySensor(APSystemsInvBaseSensor):
    """Frequency sensor."""

    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class APSystemInvTemperatureSensor(APSystemsInvBaseSensor):
    """Temperature sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC


# Inverter channel classes
class APSystemInvChVoltageSensor(APSystemsInvBaseSensor):
    """Voltage sensor."""

    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class APSystemInvChCurrentSensor(APSystemsInvBaseSensor):
    """Current sensor."""

    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class APSystemInvChPowerSensor(APSystemsInvBaseSensor):
    """Power sensor."""

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = SOLAR_ICON

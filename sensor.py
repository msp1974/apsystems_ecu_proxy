"""Handles sensor entities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SOLAR_ICON
from .coordinator import APSystemCoordinator

_LOGGER = logging.getLogger(__name__)


class SensorClass(StrEnum):
    """Sensor class enum."""

    ECU = "ecu"
    INVERTER = "inverter"


@dataclass
class SensorExtraData:
    """Class to hold data passed to sensor class."""

    sensor_class: SensorClass
    ecu_id: str
    parameter: str
    inverter_id: str | None = None
    inverter_channel: int | None = None
    model: str | None = None


@dataclass(frozen=True, kw_only=True)
class APSystemSensorEntityDescription(SensorEntityDescription):
    """A class that describes APSystem sensor entities."""

    sensor_class: str | None = None
    name_fn: Callable | None = None
    unique_id: str | None = None


# Here we define our sensors using EntityDescritions
ECU_SENSORS: tuple[APSystemSensorEntityDescription, ...] = (
    APSystemSensorEntityDescription(
        key="current_power",
        name="Current Power",
        icon=SOLAR_ICON,
        sensor_class=SensorClass.ECU,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    APSystemSensorEntityDescription(
        key="hourly_energy_production",
        name="Hourly Energy Production",
        icon=SOLAR_ICON,
        sensor_class=SensorClass.ECU,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    APSystemSensorEntityDescription(
        key="daily_energy_production",
        name="Daily Energy Production",
        icon=SOLAR_ICON,
        sensor_class=SensorClass.ECU,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    APSystemSensorEntityDescription(
        key="lifetime_energy_production",
        name="Lifetime Energy Production",
        icon=SOLAR_ICON,
        sensor_class=SensorClass.ECU,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    APSystemSensorEntityDescription(
        key="qty_of_online_inverters",
        name="Inverters Online",
        sensor_class=SensorClass.ECU,
    ),
)

INVERTER_SENSORS: tuple[APSystemSensorEntityDescription, ...] = (
    APSystemSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    APSystemSensorEntityDescription(
        key="frequency",
        name="Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

INVERTER_CHANNEL_SENSORS: tuple[APSystemSensorEntityDescription, ...] = (
    APSystemSensorEntityDescription(
        key="power",
        name_fn=lambda c: f"Power Ch {c}",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    APSystemSensorEntityDescription(
        key="voltage",
        name_fn=lambda c: f"Voltage Ch {c}",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    APSystemSensorEntityDescription(
        key="current",
        name_fn=lambda c: f"Current Ch {c}",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


# ===============================================================================
async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
):
    """Initialise sensor platform."""
    coordinator: APSystemCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]

    # Restore all previously registered entities

    def get_device_entry(device_id):
        """Get device entry by device id."""
        try:
            device_registry = dr.async_get(hass)
            devices = device_registry.devices.get_devices_for_config_entry_id(
                config_entry.entry_id
            )
            return [device for device in devices if device.id == device_id][0]
        except IndexError:
            return

    def restore_sensors():
        """Restore all previsouly registered sensors."""
        sensors = []

        entity_registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
        for entry in entries:
            if entry.domain != "sensor" or entry.disabled_by:
                continue

            # We use the unique id to get the sensor type, ecu-id, inverter uid and channel
            # to pass to our entity class.
            unique_id_params = entry.unique_id.split("-")

            # Set the extra data to pass to the sensor by splittign unique_id
            # This is so that we can send same data structure for update data
            # from the actual device.

            # Get device model from the previously registered device.
            # We need to do this as no other way to get it on a restored entity
            # for device info on the entity.
            if device := get_device_entry(entry.device_id):
                device_model = device.model
            else:
                device_model = "Unknown"

            # Create the entity extra data with the info itneeds to get its value
            # when it receives some ECU data.
            if unique_id_params[0] == SensorClass.ECU:
                extra_data = SensorExtraData(
                    sensor_class=unique_id_params[0],
                    ecu_id=unique_id_params[1],
                    parameter=unique_id_params[2],
                    model=device_model,
                )
            else:
                extra_data = SensorExtraData(
                    sensor_class=unique_id_params[0],
                    ecu_id=unique_id_params[1],
                    parameter=unique_id_params[3],
                    inverter_id=unique_id_params[2],
                    inverter_channel=unique_id_params[4].replace("CH", "")
                    if len(unique_id_params) == 5
                    else None,
                    model=device_model,
                )

            # Create entity description for restored sensor entity
            entity_description = APSystemSensorEntityDescription(
                key=extra_data.parameter,
                sensor_class=extra_data.sensor_class,
                device_class=entry.device_class or entry.original_device_class,
                icon=entry.original_icon,
                name=entry.original_name,
                unique_id=entry.unique_id,
                unit_of_measurement=entry.options.get("sensor", {}).get(
                    "unit_of_measurement"
                ),
                entity_category=entry.entity_category,
            )

            # Define which sensor class to use to create the sensor.
            if extra_data.sensor_class == SensorClass.INVERTER:
                if extra_data.inverter_channel is not None:
                    sensor_class = APSystemsInverterChannelSensor
                else:
                    sensor_class = APSystemsInverterSensor
            else:
                sensor_class = APSystemsSensor

            # Add sensor to the list.
            sensors.append(
                sensor_class(coordinator, entity_description, config_entry, extra_data)
            )

        # Create all the restored sensors.
        add_entities(sensors)

    @callback
    def handle_ecu_registration(data):
        """Handle ECU entity creation."""

        # We have found an ECU that is not resgistered in the device registry
        # So, create all sensors described in ECU_SENSORS

        _LOGGER.debug("Registering new ECU: %s", data)
        sensors = []
        for sensor in ECU_SENSORS:
            extra_data = SensorExtraData(
                sensor_class=SensorClass.ECU,
                ecu_id=data.get("ecu-id"),
                parameter=sensor.key,
            )
            sensors.append(
                APSystemsSensor(coordinator, sensor, config_entry, extra_data)
            )
        add_entities(sensors)

    @callback
    def handle_inverter_registration(data: dict[str, Any]):
        """Handle inverter entity creation."""

        # We have found an Inverter that is not registered in the device registry
        # So, create all sensors described in INVERTER_SENSORS and
        # INVERTER_CHANNEL_SENSORS

        _LOGGER.debug("Registering New Inverter: %s", data)
        # Add Inverter sensors
        sensors = []
        for sensor in INVERTER_SENSORS:
            extra_data = SensorExtraData(
                sensor_class=SensorClass.INVERTER,
                ecu_id=data.get("ecu-id"),
                parameter=sensor.key,
                inverter_id=data.get("uid"),
            )
            sensors.append(
                APSystemsInverterSensor(coordinator, sensor, config_entry, extra_data)
            )

        # Add Inverter channel sensors
        for channel in range(data.get("channel_qty", 0)):
            for sensor in INVERTER_CHANNEL_SENSORS:
                extra_data = SensorExtraData(
                    sensor_class=SensorClass.INVERTER,
                    ecu_id=data.get("ecu-id"),
                    parameter=sensor.key,
                    inverter_id=data.get("uid"),
                    inverter_channel=channel + 1,
                )
                sensors.append(
                    APSystemsInverterChannelSensor(
                        coordinator, sensor, config_entry, extra_data
                    )
                )

        add_entities(sensors)

    # Create listener for ecu registration.
    # Called by coordinator when new ECU found.
    # Allows dynamic creating of sensors.
    async_dispatcher_connect(
        hass,
        f"{DOMAIN}_ecu_register",
        handle_ecu_registration,
    )

    # Create listener for inverter registration.
    # Called by coordinator when new inverter found.
    # Allows dynamic creating of sensors.
    async_dispatcher_connect(
        hass,
        f"{DOMAIN}_inverter_register",
        handle_inverter_registration,
    )

    # Restore sensors for this config entry that have been registered previously.
    # Shows active sensors at startup even if no message form ECU yet received.
    # Restored sensors have their values from when HA was previously shut down/restarted.
    restore_sensors()


class APSystemsSensor(RestoreSensor, CoordinatorEntity, SensorEntity):
    """APSystems ECU Sensor and base class for Inverter sensors."""

    _attr_has_entity_name = True
    entity_description: APSystemSensorEntityDescription

    def __init__(
        self,
        coordinator,
        entity_description: APSystemSensorEntityDescription,
        config_entry: ConfigEntry,
        extra_data: SensorExtraData | None = None,
    ) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._config_entry = config_entry
        self.extra_data = extra_data
        self._state = None
        self._state_data = None

        _LOGGER.debug("Adding %s", self.entity_description.name)

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        await self.restore_state()

    async def restore_state(self):
        """Get restored state from store."""
        if (state := await self.async_get_last_state()) is None:
            return

        self._state = state.state
        self._state_data = await self.async_get_last_sensor_data()

        self._attr_native_unit_of_measurement = (
            self._state_data.native_unit_of_measurement
        )

        _LOGGER.debug(
            "Restored state for %s of %s with uom %s",
            self.entity_id,
            self._state,
            self._state_data.native_unit_of_measurement,
        )

    @property
    def device_info(self):
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"ecu_{self.extra_data.ecu_id}")},
            manufacturer="APSystems",
            suggested_area="Roof",
            name=f"ECU {self.extra_data.ecu_id}",
            model=f"{self.coordinator.data.get('model') if self.coordinator.data else self.extra_data.model}",
        )

    @property
    def native_value(self):
        """Return native value."""
        if self.coordinator.data:
            return self.coordinator.data.get(self.extra_data.parameter)
        if self._state_data:
            return self._state_data.native_value

    @property
    def unique_id(self):
        """Return unique id."""
        if self.entity_description.unique_id:
            return self.entity_description.unique_id
        return f"{SensorClass.ECU}-{self.extra_data.ecu_id}-{self.extra_data.parameter}"


class APSystemsInverterSensor(APSystemsSensor):
    """APSystems Inverter Sensor."""

    @property
    def native_value(self):
        """Return native value."""
        if self.coordinator.data:
            return (
                self.coordinator.data.get("inverters", {})
                .get(self.extra_data.inverter_id)
                .get(self.extra_data.parameter)
            )
        if self._state_data:
            return self._state_data.native_value

    @property
    def unique_id(self):
        """Return unique id."""
        if self.entity_description.unique_id:
            # Entity was restored - return the entity registry unique id.
            return self.entity_description.unique_id
        # Entity is being created - crete unique id from data
        return f"{SensorClass.INVERTER}-{self.extra_data.ecu_id}-{self.extra_data.inverter_id}-{self.extra_data.parameter}"

    @property
    def device_info(self):
        """Return device registry information for this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"inverter_{self.extra_data.inverter_id}")},
            manufacturer="APSystems",
            suggested_area="Roof",
            name=f"Inverter {self.extra_data.inverter_id}",
            model=f"{self.coordinator.data.get('model') if self.coordinator.data else self.extra_data.model}",
        )


class APSystemsInverterChannelSensor(APSystemsInverterSensor):
    """APSystems Inverter Channel Sensor."""

    @property
    def channel_id(self) -> int:
        """Return inverter channel id."""
        return int(self.extra_data.inverter_channel)

    @property
    def name(self):
        """Return name."""
        if self.entity_description.name_fn:
            return self.entity_description.name_fn(self.channel_id)
        return self.entity_description.name

    @property
    def native_value(self):
        """Return native value."""

        if self.coordinator.data:
            return (
                self.coordinator.data.get("inverters", {})
                .get(self.extra_data.inverter_id)
                .get(self.extra_data.parameter)
            )[self.channel_id - 1]
        if self._state_data:
            return self._state_data.native_value

    @property
    def unique_id(self):
        """Return unique id."""
        if self.entity_description.unique_id:
            return self.entity_description.unique_id
        return f"{SensorClass.INVERTER}-{self.extra_data.ecu_id}-{self.extra_data.inverter_id}-{self.extra_data.parameter}-CH{self.channel_id}"

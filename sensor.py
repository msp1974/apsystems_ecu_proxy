"""Handles sensor entities."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SOLAR_ICON

_LOGGER = logging.getLogger(__name__)


@dataclass
class APSystemSensorConfig:
    """Class for a sensor config."""

    unique_id: str | None = None
    name: str | None = None
    device_identifier: str | None = None
    initial_value: str | None = None
    display_uom: str | None = None
    display_precision: int | None = None


@dataclass(frozen=True, kw_only=True)
class APSystemSensorDefinition:
    """Class for sensor definition."""

    name: str
    icon: str | None = None
    parameter: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    unit_of_measurement: str | None = None
    entity_category: EntityCategory | None = None


ECU_SENSORS: tuple[APSystemSensorDefinition, ...] = (
    APSystemSensorDefinition(
        name="Current Power",
        icon=SOLAR_ICON,
        parameter="current_power",
        device_class=SensorDeviceClass.POWER,
        unit_of_measurement=UnitOfPower.WATT,
    ),
    APSystemSensorDefinition(
        name="Hourly Energy Production",
        icon=SOLAR_ICON,
        parameter="hourly_energy_production",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    APSystemSensorDefinition(
        name="Daily Energy Production",
        icon=SOLAR_ICON,
        parameter="daily_energy_production",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    APSystemSensorDefinition(
        name="Lifetime Energy Production",
        icon=SOLAR_ICON,
        parameter="lifetime_energy_production",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    APSystemSensorDefinition(
        name="Lifetime Energy",
        icon=SOLAR_ICON,
        parameter="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    APSystemSensorDefinition(
        name="Inverters Online",
        parameter="qty_of_online_inverters",
    ),
    APSystemSensorDefinition(
        name="Last Update",
        parameter="timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


INVERTER_SENSORS: tuple[APSystemSensorDefinition, ...] = (
    APSystemSensorDefinition(
        name="Temperature",
        parameter="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    APSystemSensorDefinition(
        name="Frequency",
        parameter="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

INVERTER_CHANNEL_SENSORS: tuple[APSystemSensorDefinition, ...] = (
    APSystemSensorDefinition(
        name="Power",
        parameter="power",
        device_class=SensorDeviceClass.POWER,
        unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    APSystemSensorDefinition(
        name="Voltage",
        parameter="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    APSystemSensorDefinition(
        name="Current",
        parameter="current",
        device_class=SensorDeviceClass.CURRENT,
        unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


# ===============================================================================
async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, add_entities: AddEntitiesCallback
):
    """Initialise sensor platform."""

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
            if device := get_device_entry(entry.device_id):
                definition = APSystemSensorDefinition(
                    name=entry.original_name,
                    icon=entry.original_icon,
                    device_class=entry.device_class or entry.original_device_class,
                    unit_of_measurement=entry.unit_of_measurement,
                    entity_category=entry.entity_category,
                )

                config = APSystemSensorConfig(
                    unique_id=entry.unique_id,
                    device_identifier=device.identifiers,
                    display_uom=entry.options.get("sensor", {}).get(
                        "unit_of_measurement"
                    ),
                )

                sensors.append(APSystemsSensor(definition, config))

        if sensors:
            add_entities(sensors)

    @callback
    def handle_ecu_registration(data):
        """Handle ECU entity creation."""

        # We have found an ECU that is not resgistered in the device registry
        # So, create all sensors described in ECU_SENSORS

        _LOGGER.debug("Registering new ECU: %s", data)

        ecu_id = data.get("ecu-id")
        device_identifiers = {(DOMAIN, f"ecu_{ecu_id}")}

        # Create device
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers=device_identifiers,
            manufacturer="APSystems",
            suggested_area="Roof",
            name=f"ECU {ecu_id}",
            model=f"{data.get('model')}",
        )

        sensors = []
        for sensor in ECU_SENSORS:
            config = APSystemSensorConfig(
                unique_id=f"{ecu_id}_{sensor.parameter}",
                device_identifier=device_identifiers,
                initial_value=data.get(sensor.parameter),
            )
            sensors.append(APSystemsSensor(sensor, config))
        add_entities(sensors)

    @callback
    def handle_inverter_registration(data: dict[str, Any]):
        """Handle inverter entity creation."""

        # We have found an Inverter that is not registered in the device registry
        # So, create all sensors described in INVERTER_SENSORS and
        # INVERTER_CHANNEL_SENSORS

        _LOGGER.debug("Registering New Inverter: %s", data)

        ecu_id = data.get("ecu-id")
        uid = data.get("uid")
        device_identifiers = {(DOMAIN, f"inverter_{uid}")}

        # Create device
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers=device_identifiers,
            manufacturer="APSystems",
            suggested_area="Roof",
            name=f"Inverter {data.get('uid')}",
            model=f"{data.get('model')}",
        )

        sensors = []
        for sensor in INVERTER_SENSORS:
            config = APSystemSensorConfig(
                unique_id=f"{ecu_id}_{uid}_{sensor.parameter}",
                device_identifier=device_identifiers,
                initial_value=data.get(sensor.parameter),
            )
            sensors.append(APSystemsSensor(sensor, config))

        # Add Inverter channel sensors
        for channel in range(data.get("channel_qty", 0)):
            for sensor in INVERTER_CHANNEL_SENSORS:
                config = APSystemSensorConfig(
                    unique_id=f"{ecu_id}_{uid}_{sensor.parameter}_{channel}",
                    device_identifier=device_identifiers,
                    initial_value=data.get(sensor.parameter)[channel],
                    name=f"{sensor.name} Ch {channel + 1}",
                )
                sensors.append(APSystemsSensor(sensor, config))

        add_entities(sensors)

    # Create listener for ecu or inverter registration.
    # Called by update callback in APManager class.
    # Allows dynamic creating of sensors.
    async_dispatcher_connect(
        hass,
        f"{DOMAIN}_ecu_register",
        handle_ecu_registration,
    )
    async_dispatcher_connect(
        hass,
        f"{DOMAIN}_inverter_register",
        handle_inverter_registration,
    )

    # Restore sensors for this config entry that have been registered previously.
    # Shows active sensors at startup even if no message from ECU yet received.
    # Restored sensors have their values from when HA was previously shut down/restarted.
    restore_sensors()


class APSystemsSensor(RestoreSensor, SensorEntity):
    """Base APSystems sensor class."""

    _attr_has_entity_name = True

    def __init__(
        self, definition: APSystemSensorDefinition, config: APSystemSensorConfig
    ) -> None:
        """Initialise sensor."""
        self._definition = definition
        self._config = config

        self._attr_device_class = definition.device_class
        self._attr_device_info = DeviceInfo(identifiers=self._config.device_identifier)
        self._attr_icon = definition.icon
        self._attr_name = config.name or definition.name
        self._attr_native_unit_of_measurement = definition.unit_of_measurement
        self._attr_state_class = definition.state_class
        self._attr_unique_id = self._config.unique_id

        if config.initial_value is not None:
            self._attr_native_value = config.initial_value

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{DOMAIN}_{self._config.unique_id}",
                self.update_state,
            )
        )
        if not self._config.initial_value:
            await self.restore_state()

    async def restore_state(self):
        """Get restored state from store."""
        if (state := await self.async_get_last_state()) is not None:
            # Set unit of measurement in case user has changed this in UI
            self._attr_unit_of_measurement = state.attributes.get("unit_of_measurement")

        if (state_data := await self.async_get_last_sensor_data()) is not None:
            # Set our native values
            if state_data.native_unit_of_measurement is not None:
                self._attr_native_unit_of_measurement = (
                    state_data.native_unit_of_measurement
                )
            if state_data.native_value is not None:
                self._attr_native_value = state_data.native_value

        _LOGGER.debug(
            "Restored state for %s of %s with native uom %s and uom %s",
            self.entity_id,
            state_data.native_value,
            state_data.native_unit_of_measurement,
            self._attr_unit_of_measurement,
        )

    @callback
    def update_state(self, data):
        """Update sensor value."""
        _LOGGER.debug(
            "Updating sensor: %s with value %s",
            self.entity_id,
            data,
        )

        # Prevent updating total increasing sensors (ie historical energy sensors)
        # with lower values.
        if (
            self.state_class == SensorStateClass.TOTAL_INCREASING
            and data < self.native_value
        ):
            return

        self.native_value = data
        self.async_write_ha_state()

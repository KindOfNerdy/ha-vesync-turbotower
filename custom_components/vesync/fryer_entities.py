"""Form and action entities for dual-zone air fryers (Turbo Tower fork).

Each platform module calls the matching ``*_entities()`` function so the
upstream platform files only need a one-line hook.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import override

from pyvesync.base_devices.fryer_base import VeSyncFryer
from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.const import AirFryerChamber
from pyvesync.utils.errors import VeSyncError

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import VeSyncDataCoordinator
from .entity import VeSyncBaseEntity
from .fryer import (
    MODE_TO_SYNC_TYPE,
    OPTION_TO_PROGRAM,
    PROGRAM_LIMITS,
    PROGRAM_OPTIONS,
    START_MODE_OPTIONS,
    ZONES,
    FryerCommandError,
    clamp_minutes,
    clamp_temperature,
    cook_config,
    end_zone,
    is_dual_fryer,
    pause_zone,
    preset_values,
    resume_zone,
    start_cook,
    validate,
    zone_status,
    zone_values,
)

# Zone states in which the zone shows its running values instead of the form.
BUSY_STATES = {"ready", "cooking", "paused", "waiting", "basket_out"}
# The cloud reports a new state a few seconds after a command (device tests).
REFRESH_DELAY = 3
STOPPABLE_STATES = BUSY_STATES | {"done"}


def _fryers(devices: Iterable[VeSyncBaseDevice]) -> list[VeSyncFryer]:
    return [dev for dev in devices if is_dual_fryer(dev)]


def _error(key: str, **placeholders: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


class FryerEntity(VeSyncBaseEntity):
    """Base for fryer form/action entities."""

    device: VeSyncFryer

    def __init__(
        self,
        device: VeSyncFryer,
        coordinator: VeSyncDataCoordinator,
        key: str,
        zone: AirFryerChamber | None = None,
    ) -> None:
        """Initialize."""
        super().__init__(device, coordinator)
        self._zone = int(zone) if zone is not None else None
        prefix = f"zone{self._zone}-" if zone is not None else ""
        self._attr_unique_id = f"{self.base_unique_id}-{prefix}{key}"
        self._attr_translation_key = f"zone_{key}" if zone is not None else key
        if zone is not None:
            self._attr_translation_placeholders = {"zone": str(self._zone)}

    @property
    def form(self):
        """Return the fryer's form."""
        return self.coordinator.fryer_form(self.device.cid)

    def _status(self, zone: int) -> str | None:
        return zone_status(self.device, AirFryerChamber(zone))

    def _busy(self) -> bool:
        return self._status(self._zone) in BUSY_STATES

    def _shown(self) -> tuple[str, int, int]:
        """Program, temperature and minutes shown for this zone."""
        if self._busy():
            program, temp, minutes = zone_values(self.device, AirFryerChamber(self._zone))
            if program in PROGRAM_LIMITS and temp and minutes:
                return program, temp, minutes
        zone_form = self.form.zones[self._zone]
        return zone_form.program, zone_form.temperature, zone_form.minutes

    def _check_editable(self) -> None:
        if self._busy():
            raise _error("zone_busy", zone=str(self._zone))

    async def _run(self, *calls: Callable[[], Awaitable[None]]) -> None:
        """Run fryer commands in order, then refresh; errors become HA errors."""
        try:
            for call in calls:
                await call()
        except FryerCommandError as err:
            raise _error("command_failed", command=err.method, code=str(err.code)) from err
        except VeSyncError as err:
            raise _error("command_failed", command="", code=str(err)) from err
        finally:
            await asyncio.sleep(REFRESH_DELAY)
            await self.coordinator.async_request_refresh()


# --- select ---------------------------------------------------------------------


class ZoneProgramSelect(FryerEntity, SelectEntity):
    """Program of one zone (dropdown)."""

    _attr_options = PROGRAM_OPTIONS

    def __init__(self, device, coordinator, zone) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "program", zone)

    @property
    @override
    def current_option(self) -> str | None:
        """Return the program."""
        return self._shown()[0].lower()

    @override
    async def async_select_option(self, option: str) -> None:
        """Select a program; temperature and time jump to its defaults."""
        self._check_editable()
        program = OPTION_TO_PROGRAM[option]
        temperature, minutes = preset_values(
            self.coordinator.fryer_presets.get(self.device.cid), program
        )
        zone_form = self.form.zones[self._zone]
        zone_form.program, zone_form.temperature, zone_form.minutes = (
            program,
            temperature,
            minutes,
        )
        self.form.edited = True
        self.coordinator.async_update_listeners()


class StartModeSelect(FryerEntity, SelectEntity):
    """Mode used by 'Start both'."""

    _attr_options = START_MODE_OPTIONS

    def __init__(self, device, coordinator) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "start_mode")

    @property
    @override
    def current_option(self) -> str:
        """Return the start mode."""
        return self.form.start_mode

    @override
    async def async_select_option(self, option: str) -> None:
        """Set the start mode."""
        self.form.start_mode = option
        self.coordinator.async_update_listeners()


def select_entities(devices, coordinator) -> list[SelectEntity]:
    """Return fryer select entities."""
    entities: list[SelectEntity] = []
    for dev in _fryers(devices):
        entities += [ZoneProgramSelect(dev, coordinator, zone) for zone in ZONES]
        entities.append(StartModeSelect(dev, coordinator))
    return entities


# --- number ---------------------------------------------------------------------


class ZoneTemperatureNumber(FryerEntity, NumberEntity):
    """Temperature of one zone."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, device, coordinator, zone) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "temperature", zone)

    @property
    def _limits(self):
        return PROGRAM_LIMITS[self._shown()[0]]

    @property
    @override
    def native_min_value(self) -> float:
        return self._limits.temp_min

    @property
    @override
    def native_max_value(self) -> float:
        return self._limits.temp_max

    @property
    @override
    def native_step(self) -> float:
        return self._limits.temp_step

    @property
    @override
    def native_value(self) -> float:
        """Return the temperature."""
        return self._shown()[1]

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the temperature."""
        self._check_editable()
        zone_form = self.form.zones[self._zone]
        zone_form.temperature = clamp_temperature(zone_form.program, value)
        self.form.edited = True
        self.coordinator.async_update_listeners()


class ZoneTimeNumber(FryerEntity, NumberEntity):
    """Cook time of one zone in minutes."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, device, coordinator, zone) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "time", zone)

    @property
    def _limits(self):
        return PROGRAM_LIMITS[self._shown()[0]]

    @property
    @override
    def native_min_value(self) -> float:
        return self._limits.time_min

    @property
    @override
    def native_max_value(self) -> float:
        return self._limits.time_max

    @property
    @override
    def native_step(self) -> float:
        return self._limits.time_step

    @property
    @override
    def native_value(self) -> float:
        """Return the time in minutes."""
        return self._shown()[2]

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the time."""
        self._check_editable()
        zone_form = self.form.zones[self._zone]
        zone_form.minutes = clamp_minutes(zone_form.program, value)
        self.form.edited = True
        self.coordinator.async_update_listeners()


def number_entities(devices, coordinator) -> list[NumberEntity]:
    """Return fryer number entities."""
    entities: list[NumberEntity] = []
    for dev in _fryers(devices):
        for zone in ZONES:
            entities += [
                ZoneTemperatureNumber(dev, coordinator, zone),
                ZoneTimeNumber(dev, coordinator, zone),
            ]
    return entities


# --- switch ---------------------------------------------------------------------


class DirectStartSwitch(FryerEntity, SwitchEntity, RestoreEntity):
    """Start cooking right away instead of waiting for the start button."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device, coordinator) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "direct_start")

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the last state (default off)."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.form.direct_start = last.state == "on"

    @property
    @override
    def is_on(self) -> bool:
        """Return True if starts begin right away."""
        return self.form.direct_start

    @override
    async def async_turn_on(self, **kwargs) -> None:
        """Turn on."""
        self.form.direct_start = True
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs) -> None:
        """Turn off."""
        self.form.direct_start = False
        self.async_write_ha_state()


def switch_entities(devices, coordinator) -> list[SwitchEntity]:
    """Return fryer switch entities."""
    return [DirectStartSwitch(dev, coordinator) for dev in _fryers(devices)]


# --- button ---------------------------------------------------------------------


class FryerButton(FryerEntity, ButtonEntity):
    """Start, stop or pause/resume."""

    def __init__(self, device, coordinator, action: str, zone=None) -> None:
        """Initialize."""
        super().__init__(device, coordinator, action, zone)
        self._action = action

    def _config(self, zone: int) -> dict:
        zone_form = self.form.zones[zone]
        try:
            validate(zone_form.program, zone_form.temperature, zone_form.minutes)
        except ValueError as err:
            raise _error("invalid_values", details=str(err)) from err
        return cook_config(
            self.device, zone, zone_form.program, zone_form.temperature, zone_form.minutes
        )

    @override
    async def async_press(self) -> None:
        """Handle the button press."""
        ready = not self.form.direct_start
        if self._action == "start":
            if self._busy():
                raise _error("zone_busy", zone=str(self._zone))
            configs = [self._config(self._zone)]
            await self._run(lambda: start_cook(self.device, configs, ready_start=ready))
        elif self._action == "start_both":
            if any(self._status(int(z)) in BUSY_STATES for z in ZONES):
                raise _error("fryer_busy")
            mode = self.form.start_mode
            if mode == "match":
                first = self._config(1)
                configs = [first, {**first, "chamber": 2}]
            else:
                configs = [self._config(1), self._config(2)]
            sync_type = MODE_TO_SYNC_TYPE[mode]
            await self._run(
                lambda: start_cook(self.device, configs, sync_type=sync_type, ready_start=ready)
            )
        elif self._action == "stop":
            if self._status(self._zone) not in STOPPABLE_STATES:
                raise _error("zone_not_active", zone=str(self._zone))
            await self._run(lambda: end_zone(self.device, self._zone))
        elif self._action == "stop_all":
            zones = [int(z) for z in ZONES if self._status(int(z)) in STOPPABLE_STATES]
            if not zones:
                raise _error("fryer_not_active")
            await self._run(*(lambda z=zone: end_zone(self.device, z) for zone in zones))
        elif self._action == "pause_resume_all":
            cooking = [int(z) for z in ZONES if self._status(int(z)) == "cooking"]
            paused = [int(z) for z in ZONES if self._status(int(z)) == "paused"]
            if cooking:
                await self._run(*(lambda z=zone: pause_zone(self.device, z) for zone in cooking))
            elif paused:
                await self._run(*(lambda z=zone: resume_zone(self.device, z) for zone in paused))
            else:
                raise _error("fryer_not_active")
        elif self._action == "pause_resume":
            status = self._status(self._zone)
            if status == "cooking":  # pausing a waiting (Sync) zone is untested
                await self._run(lambda: pause_zone(self.device, self._zone))
            elif status == "paused":
                await self._run(lambda: resume_zone(self.device, self._zone))
            else:
                raise _error("zone_not_active", zone=str(self._zone))


def button_entities(devices, coordinator) -> list[ButtonEntity]:
    """Return fryer button entities."""
    entities: list[ButtonEntity] = []
    for dev in _fryers(devices):
        for zone in ZONES:
            entities += [
                FryerButton(dev, coordinator, "start", zone),
                FryerButton(dev, coordinator, "stop", zone),
                FryerButton(dev, coordinator, "pause_resume", zone),
            ]
        entities += [
            FryerButton(dev, coordinator, "start_both"),
            FryerButton(dev, coordinator, "stop_all"),
            FryerButton(dev, coordinator, "pause_resume_all"),
        ]
    return entities

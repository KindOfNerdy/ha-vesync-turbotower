"""Form and command entities for dual-basket air fryers (Turbo Tower fork).

Modeled on Home Connect: a program select and temperature/time numbers per
basket hold the values to start with; buttons start, send (start on the
fryer), pause, resume and stop. Each platform module calls the matching
``*_entities()`` function so the upstream platform files only need a one-line
hook.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import override

from pyvesync.base_devices.fryer_base import VeSyncFryer
from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.const import AirFryerChamber, AirFryerCookStatus
from pyvesync.utils.errors import VeSyncError

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN
from .coordinator import VeSyncDataCoordinator
from .entity import VeSyncBaseEntity
from .fryer import (
    BASKETS,
    OPTION_TO_PROGRAM,
    PROGRAM_LIMITS,
    PROGRAM_OPTIONS,
    START_MODE_OPTIONS,
    SYNC_TYPES,
    FryerCommandError,
    basket_values,
    can_stop,
    clamp_minutes,
    clamp_temperature,
    cook_config,
    cook_status,
    end_baskets,
    is_busy,
    is_dual_fryer,
    panel_selected,
    pause_baskets,
    preset_values,
    quit_sync,
    resume_baskets,
    start_cook,
    validate,
)

# The cloud reports a new state a few seconds after a command (device tests).
REFRESH_DELAY = 3


def _fryers(devices: Iterable[VeSyncBaseDevice]) -> list[VeSyncFryer]:
    return [dev for dev in devices if is_dual_fryer(dev)]


def validation_error(key: str, **placeholders: str) -> ServiceValidationError:
    """Return a translated validation error."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


def check_startable(device: VeSyncFryer, basket: int) -> None:
    """Raise if the basket can't take a new program now."""
    status = cook_status(device, basket)
    if status == AirFryerCookStatus.PULL_OUT:
        raise validation_error("basket_out", basket=str(basket))
    if panel_selected(device, basket):
        raise validation_error("panel_selected", basket=str(basket))
    if is_busy(device, basket):
        raise validation_error("basket_busy", basket=str(basket))


async def run_commands(
    coordinator: VeSyncDataCoordinator, *calls: Callable[[], Awaitable[None]]
) -> None:
    """Run fryer commands in order, then refresh; errors become HA errors."""
    try:
        for call in calls:
            await call()
    except FryerCommandError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed" if err.code is not None else "command_not_accepted",
            translation_placeholders={"command": err.method, "code": str(err.code)},
        ) from err
    except VeSyncError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"command": "", "code": str(err)},
        ) from err
    finally:
        await asyncio.sleep(REFRESH_DELAY)
        await coordinator.async_request_refresh()


class FryerEntity(VeSyncBaseEntity):
    """Base for fryer form and command entities."""

    device: VeSyncFryer

    def __init__(
        self,
        device: VeSyncFryer,
        coordinator: VeSyncDataCoordinator,
        key: str,
        basket: AirFryerChamber | None = None,
    ) -> None:
        """Initialize."""
        super().__init__(device, coordinator)
        self._basket = int(basket) if basket is not None else None
        prefix = f"basket{self._basket}-" if basket is not None else ""
        self._attr_unique_id = f"{self.base_unique_id}-{prefix}{key}"
        self._attr_translation_key = f"basket_{key}" if basket is not None else key
        if basket is not None:
            self._attr_translation_placeholders = {"basket": str(self._basket)}

    @property
    def form(self):
        """Return the fryer's form."""
        return self.coordinator.fryer_form(self.device.cid)

    def _shown(self) -> tuple[str, int, int]:
        """Program, temperature and minutes shown for this basket.

        While the basket has a cook (also one chosen on the panel), its values;
        otherwise the values entered in HA.
        """
        if is_busy(self.device, self._basket):
            program, temp, minutes = basket_values(self.device, self._basket)
            if program in PROGRAM_LIMITS and temp and minutes:
                return program, temp, minutes
        basket_form = self.form.baskets[self._basket]
        return basket_form.program, basket_form.temperature, basket_form.minutes

    def _check_editable(self) -> None:
        check_startable(self.device, self._basket)


# --- select ---------------------------------------------------------------------


class BasketProgramSelect(FryerEntity, SelectEntity):
    """Program of one basket."""

    _attr_options = PROGRAM_OPTIONS

    def __init__(self, device, coordinator, basket) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "program", basket)

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
        basket_form = self.form.baskets[self._basket]
        basket_form.program = program
        basket_form.temperature = temperature
        basket_form.minutes = minutes
        self.form.edited = True
        self.coordinator.async_update_listeners()


class StartModeSelect(FryerEntity, SelectEntity):
    """How 'Start both baskets' starts them: separate, Sync or Match."""

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
        entities += [BasketProgramSelect(dev, coordinator, basket) for basket in BASKETS]
        entities.append(StartModeSelect(dev, coordinator))
    return entities


# --- number ---------------------------------------------------------------------


class BasketTemperatureNumber(FryerEntity, NumberEntity):
    """Temperature of one basket."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, device, coordinator, basket) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "temperature", basket)

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
        basket_form = self.form.baskets[self._basket]
        basket_form.temperature = clamp_temperature(basket_form.program, value)
        self.form.edited = True
        self.coordinator.async_update_listeners()


class BasketTimeNumber(FryerEntity, NumberEntity):
    """Cook time of one basket in minutes."""

    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(self, device, coordinator, basket) -> None:
        """Initialize."""
        super().__init__(device, coordinator, "time", basket)

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
        basket_form = self.form.baskets[self._basket]
        basket_form.minutes = clamp_minutes(basket_form.program, value)
        self.form.edited = True
        self.coordinator.async_update_listeners()


def number_entities(devices, coordinator) -> list[NumberEntity]:
    """Return fryer number entities."""
    entities: list[NumberEntity] = []
    for dev in _fryers(devices):
        for basket in BASKETS:
            entities += [
                BasketTemperatureNumber(dev, coordinator, basket),
                BasketTimeNumber(dev, coordinator, basket),
            ]
    return entities


# --- button ---------------------------------------------------------------------

# Per basket: start, send (start on the fryer), pause, resume, stop.
BASKET_ACTIONS = ("start", "send", "pause", "resume", "stop")
# For the whole fryer.
FRYER_ACTIONS = ("start_both", "send_both", "pause_all", "resume_all", "stop_all", "quit_sync")


class FryerButton(FryerEntity, ButtonEntity):
    """A fryer command."""

    def __init__(self, device, coordinator, action: str, basket=None) -> None:
        """Initialize."""
        super().__init__(device, coordinator, action, basket)
        self._action = action
        # Starting remotely heats at once; it has to be switched on on purpose.
        if action in ("start", "start_both"):
            self._attr_entity_registry_enabled_default = False

    def _config(self, basket: int) -> dict:
        basket_form = self.form.baskets[basket]
        try:
            validate(basket_form.program, basket_form.temperature, basket_form.minutes)
        except ValueError as err:
            raise validation_error("invalid_values", details=str(err)) from err
        return cook_config(
            self.device, basket, basket_form.program, basket_form.temperature, basket_form.minutes
        )

    def _baskets_in(self, *statuses: AirFryerCookStatus) -> list[int]:
        return [int(b) for b in BASKETS if cook_status(self.device, b) in statuses]

    @override
    async def async_press(self) -> None:
        """Handle the button press."""
        dev, action = self.device, self._action
        if action in ("start", "send"):
            self._check_editable()
            configs = [self._config(self._basket)]
            ready = action == "send"
            await run_commands(
                self.coordinator, lambda: start_cook(dev, configs, ready_start=ready)
            )
        elif action in ("start_both", "send_both"):
            for basket in BASKETS:
                check_startable(dev, int(basket))
            mode = self.form.start_mode
            first = self._config(1)
            configs = [first, {**first, "chamber": 2}] if mode == "match" else [first, self._config(2)]
            ready = action == "send_both"
            await run_commands(
                self.coordinator,
                lambda: start_cook(dev, configs, sync_type=SYNC_TYPES[mode], ready_start=ready),
            )
        elif action == "pause":
            if cook_status(dev, self._basket) != AirFryerCookStatus.COOKING:
                raise validation_error("basket_not_cooking", basket=str(self._basket))
            await run_commands(self.coordinator, lambda: pause_baskets(dev, [self._basket]))
        elif action == "resume":
            if cook_status(dev, self._basket) != AirFryerCookStatus.COOK_STOP:
                raise validation_error("basket_not_paused", basket=str(self._basket))
            await run_commands(self.coordinator, lambda: resume_baskets(dev, [self._basket]))
        elif action == "stop":
            self._check_stoppable([self._basket])
            await run_commands(self.coordinator, lambda: end_baskets(dev, [self._basket]))
        elif action == "pause_all":
            baskets = self._baskets_in(AirFryerCookStatus.COOKING)
            if not baskets:
                raise validation_error("nothing_cooking")
            await run_commands(self.coordinator, lambda: pause_baskets(dev, baskets))
        elif action == "resume_all":
            baskets = self._baskets_in(AirFryerCookStatus.COOK_STOP)
            if not baskets:
                raise validation_error("nothing_paused")
            await run_commands(self.coordinator, lambda: resume_baskets(dev, baskets))
        elif action == "stop_all":
            baskets = [int(b) for b in BASKETS if can_stop(dev, b)]
            if not baskets:
                self._check_stoppable([int(b) for b in BASKETS])
            await run_commands(self.coordinator, lambda: end_baskets(dev, baskets))
        elif action == "quit_sync":
            if not dev.sync_chambers:
                raise validation_error("not_in_sync")
            await run_commands(self.coordinator, lambda: quit_sync(dev))

    def _check_stoppable(self, baskets: list[int]) -> None:
        for basket in baskets:
            if panel_selected(self.device, basket):
                raise validation_error("panel_selected", basket=str(basket))
        if not any(can_stop(self.device, b) for b in baskets):
            if len(baskets) == 1:
                raise validation_error("basket_not_active", basket=str(baskets[0]))
            raise validation_error("nothing_active")


def button_entities(devices, coordinator) -> list[ButtonEntity]:
    """Return fryer button entities."""
    entities: list[ButtonEntity] = []
    for dev in _fryers(devices):
        for basket in BASKETS:
            entities += [FryerButton(dev, coordinator, a, basket) for a in BASKET_ACTIONS]
        entities += [FryerButton(dev, coordinator, a) for a in FRYER_ACTIONS]
    return entities

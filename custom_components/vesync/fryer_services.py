"""Actions for dual-basket air fryers (Turbo Tower fork).

Only what entities can't do in one step: start with given values (recipes)
and change the fryer's program presets. Stop, pause and resume are buttons.
"""

from __future__ import annotations

from pyvesync.base_devices.fryer_base import VeSyncFryer
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN
from .coordinator import VeSyncDataCoordinator
from .fryer import (
    BASKETS,
    OPTION_TO_PROGRAM,
    PROGRAM_OPTIONS,
    SYNC_TYPES,
    cook_config,
    get_presets,
    is_dual_fryer,
    preset_values,
    reset_preset,
    start_cook,
    update_preset,
    validate,
)
from .fryer_entities import check_startable, run_commands, validation_error

ATTR_DEVICE = "device_id"
PROGRAM = vol.In(PROGRAM_OPTIONS)
TEMP = vol.All(vol.Coerce(int), vol.Range(min=30, max=230))
MINUTES = vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))

START_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE): cv.string,
        vol.Required("basket"): vol.In(["1", "2", "both"]),
        vol.Required("program"): PROGRAM,
        vol.Optional("temperature"): TEMP,
        vol.Optional("duration"): MINUTES,
        vol.Optional("send_only", default=False): cv.boolean,
        vol.Optional("mode", default="separate"): vol.In(list(SYNC_TYPES)),
        vol.Optional("program_2"): PROGRAM,
        vol.Optional("temperature_2"): TEMP,
        vol.Optional("duration_2"): MINUTES,
    }
)
PRESET_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE): cv.string,
        vol.Required("program"): PROGRAM,
        vol.Required("temperature"): TEMP,
        vol.Required("duration"): MINUTES,
    }
)
RESET_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_DEVICE): cv.string, vol.Required("program"): PROGRAM}
)


def _fryers(hass: HomeAssistant) -> list[tuple[VeSyncFryer, VeSyncDataCoordinator]]:
    found = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator: VeSyncDataCoordinator = entry.runtime_data
        found += [
            (dev, coordinator) for dev in coordinator.manager.devices if is_dual_fryer(dev)
        ]
    return found


def _resolve(call: ServiceCall) -> tuple[VeSyncFryer, VeSyncDataCoordinator]:
    """Return the fryer chosen in the call; optional if there is only one."""
    fryers = _fryers(call.hass)
    if not fryers:
        raise validation_error("no_fryer")
    device_id = call.data.get(ATTR_DEVICE)
    if not device_id:
        if len(fryers) > 1:
            raise validation_error("choose_fryer")
        return fryers[0]
    entry = dr.async_get(call.hass).async_get(device_id)
    identifiers = {ident for domain, ident in (entry.identifiers if entry else ()) if domain == DOMAIN}
    for dev, coordinator in fryers:
        base = f"{dev.cid}{dev.sub_device_no!s}" if isinstance(dev.sub_device_no, int) else dev.cid
        if base in identifiers:
            return dev, coordinator
    raise validation_error("not_a_fryer")


def _values(coordinator, dev, option: str, temperature, duration) -> tuple[str, int, int]:
    program = OPTION_TO_PROGRAM[option]
    default_temp, default_min = preset_values(coordinator.fryer_presets.get(dev.cid), program)
    temp = temperature if temperature is not None else default_temp
    minutes = duration if duration is not None else default_min
    try:
        validate(program, temp, minutes)
    except ValueError as err:
        raise validation_error("invalid_values", details=str(err)) from err
    return program, temp, minutes


async def _start_cook(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    data = call.data
    basket = data["basket"]
    first = _values(coordinator, dev, data["program"], data.get("temperature"), data.get("duration"))

    if basket in ("1", "2"):
        check_startable(dev, int(basket))
        configs = [cook_config(dev, int(basket), *first)]
        sync_type = 0
    else:
        for each in BASKETS:
            check_startable(dev, int(each))
        mode = data["mode"]
        config_1 = cook_config(dev, 1, *first)
        if mode == "match":
            configs = [config_1, {**config_1, "chamber": 2}]
        else:
            if "program_2" not in data:
                raise validation_error("basket_2_missing")
            second = _values(
                coordinator, dev, data["program_2"], data.get("temperature_2"), data.get("duration_2")
            )
            configs = [config_1, cook_config(dev, 2, *second)]
        sync_type = SYNC_TYPES[mode]

    ready = data["send_only"]
    await run_commands(
        coordinator, lambda: start_cook(dev, configs, sync_type=sync_type, ready_start=ready)
    )


async def _refresh_presets(coordinator: VeSyncDataCoordinator, dev: VeSyncFryer) -> None:
    coordinator.fryer_presets[dev.cid] = await get_presets(dev)


async def _set_preset(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    program, temp, minutes = _values(
        coordinator, dev, call.data["program"], call.data["temperature"], call.data["duration"]
    )
    current = (coordinator.fryer_presets.get(dev.cid) or {}).get(program) or {}
    preset = {
        "mode": program,
        "cookTemp": temp,
        "cookSetTime": minutes * 60,
        "shakeTime": current.get("shakeTime", 0),
        "tempUnit": "c",
        "allowModified": current.get("allowModified", True),
    }
    await run_commands(
        coordinator,
        lambda: update_preset(dev, preset),
        lambda: _refresh_presets(coordinator, dev),
    )


async def _reset_preset(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    program = OPTION_TO_PROGRAM[call.data["program"]]
    await run_commands(
        coordinator,
        lambda: reset_preset(dev, program),
        lambda: _refresh_presets(coordinator, dev),
    )


@callback
def async_setup_fryer_services(hass: HomeAssistant) -> None:
    """Register the fryer actions."""
    for name, handler, schema in (
        ("start_cook", _start_cook, START_SCHEMA),
        ("set_preset", _set_preset, PRESET_SCHEMA),
        ("reset_preset", _reset_preset, RESET_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)

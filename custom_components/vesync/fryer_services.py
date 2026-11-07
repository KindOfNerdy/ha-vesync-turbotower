"""Services for dual-zone air fryers (Turbo Tower fork)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from pyvesync.base_devices.fryer_base import VeSyncFryer
from pyvesync.const import AirFryerChamber
from pyvesync.utils.errors import VeSyncError
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN
from .coordinator import VeSyncDataCoordinator
from .fryer import (
    MODE_TO_SYNC_TYPE,
    OPTION_TO_PROGRAM,
    PROGRAM_OPTIONS,
    ZONES,
    FryerCommandError,
    cook_config,
    end_zone,
    get_presets,
    is_dual_fryer,
    pause_zone,
    preset_values,
    quit_sync,
    reset_preset,
    resume_zone,
    start_cook,
    update_preset,
    validate,
    zone_status,
)

REFRESH_DELAY = 3
BUSY_STATES = {"ready", "cooking", "paused", "waiting", "basket_out"}
STOPPABLE_STATES = BUSY_STATES | {"done"}

ATTR_DEVICE = "device_id"
PROGRAM = vol.In(PROGRAM_OPTIONS)
TEMP = vol.All(vol.Coerce(int), vol.Range(min=30, max=230))
MINUTES = vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))

START_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE): cv.string,
        vol.Required("zone"): vol.In(["1", "2", "both"]),
        vol.Required("program"): PROGRAM,
        vol.Optional("temperature"): TEMP,
        vol.Optional("duration"): MINUTES,
        vol.Optional("direct_start"): cv.boolean,
        vol.Optional("mode", default="independent"): vol.In(["independent", "sync", "match"]),
        vol.Optional("program_2"): PROGRAM,
        vol.Optional("temperature_2"): TEMP,
        vol.Optional("duration_2"): MINUTES,
    }
)
ZONE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DEVICE): cv.string,
        vol.Optional("zone", default="all"): vol.In(["1", "2", "all"]),
    }
)
DEVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_DEVICE): cv.string})
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


def _validation(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
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
        raise _validation("no_fryer")
    device_id = call.data.get(ATTR_DEVICE)
    if not device_id:
        if len(fryers) > 1:
            raise _validation("choose_fryer")
        return fryers[0]
    entry = dr.async_get(call.hass).async_get(device_id)
    identifiers = {ident for domain, ident in (entry.identifiers if entry else ()) if domain == DOMAIN}
    for dev, coordinator in fryers:
        base = f"{dev.cid}{dev.sub_device_no!s}" if isinstance(dev.sub_device_no, int) else dev.cid
        if base in identifiers:
            return dev, coordinator
    raise _validation("not_a_fryer")


def _status(dev: VeSyncFryer, zone: int) -> str | None:
    return zone_status(dev, AirFryerChamber(zone))


def _zones(arg: str) -> list[int]:
    return [int(z) for z in ZONES] if arg == "all" else [int(arg)]


async def _run(
    coordinator: VeSyncDataCoordinator, *calls: Callable[[], Awaitable[None]]
) -> None:
    try:
        for call in calls:
            await call()
    except FryerCommandError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
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


def _values(coordinator, dev, option: str, temperature, duration) -> tuple[str, int, int]:
    program = OPTION_TO_PROGRAM[option]
    default_temp, default_min = preset_values(coordinator.fryer_presets.get(dev.cid), program)
    temp = temperature if temperature is not None else default_temp
    minutes = duration if duration is not None else default_min
    try:
        validate(program, temp, minutes)
    except ValueError as err:
        raise _validation("invalid_values", details=str(err)) from err
    return program, temp, minutes


async def _start_cook(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    data = call.data
    zone = data["zone"]
    first = _values(coordinator, dev, data["program"], data.get("temperature"), data.get("duration"))
    ready = not data.get("direct_start", coordinator.fryer_form(dev.cid).direct_start)

    if zone in ("1", "2"):
        if _status(dev, int(zone)) in BUSY_STATES:
            raise _validation("zone_busy", zone=zone)
        configs = [cook_config(dev, int(zone), *first)]
        sync_type = 0
    else:
        if any(_status(dev, int(z)) in BUSY_STATES for z in ZONES):
            raise _validation("fryer_busy")
        mode = data["mode"]
        config_1 = cook_config(dev, 1, *first)
        if mode == "match":
            configs = [config_1, {**config_1, "chamber": 2}]
        else:
            if "program_2" not in data:
                raise _validation("zone_2_missing")
            second = _values(
                coordinator, dev, data["program_2"], data.get("temperature_2"), data.get("duration_2")
            )
            configs = [config_1, cook_config(dev, 2, *second)]
        sync_type = MODE_TO_SYNC_TYPE["separate" if mode == "independent" else mode]

    await _run(coordinator, lambda: start_cook(dev, configs, sync_type=sync_type, ready_start=ready))


async def _stop(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    zones = [z for z in _zones(call.data["zone"]) if _status(dev, z) in STOPPABLE_STATES]
    if not zones:
        raise _validation("nothing_to_do")
    await _run(coordinator, *(lambda z=z: end_zone(dev, z) for z in zones))


async def _pause(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    zones = [z for z in _zones(call.data["zone"]) if _status(dev, z) == "cooking"]
    if not zones:
        raise _validation("nothing_to_do")
    await _run(coordinator, *(lambda z=z: pause_zone(dev, z) for z in zones))


async def _resume(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    zones = [z for z in _zones(call.data["zone"]) if _status(dev, z) == "paused"]
    if not zones:
        raise _validation("nothing_to_do")
    await _run(coordinator, *(lambda z=z: resume_zone(dev, z) for z in zones))


async def _quit_sync(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    if coordinator.fryer_sync_type.get(dev.cid) != MODE_TO_SYNC_TYPE["sync"]:
        raise _validation("not_in_sync")
    await _run(coordinator, lambda: quit_sync(dev))


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
    await _run(
        coordinator,
        lambda: update_preset(dev, preset),
        lambda: _refresh_presets(coordinator, dev),
    )


async def _reset_preset(call: ServiceCall) -> None:
    dev, coordinator = _resolve(call)
    program = OPTION_TO_PROGRAM[call.data["program"]]
    await _run(
        coordinator,
        lambda: reset_preset(dev, program),
        lambda: _refresh_presets(coordinator, dev),
    )


@callback
def async_setup_fryer_services(hass: HomeAssistant) -> None:
    """Register the fryer services."""
    for name, handler, schema in (
        ("start_cook", _start_cook, START_SCHEMA),
        ("stop", _stop, ZONE_SCHEMA),
        ("pause", _pause, ZONE_SCHEMA),
        ("resume", _resume, ZONE_SCHEMA),
        ("quit_sync", _quit_sync, DEVICE_SCHEMA),
        ("set_preset", _set_preset, PRESET_SCHEMA),
        ("reset_preset", _reset_preset, RESET_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema)

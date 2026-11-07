"""Dual-zone air fryer support (Turbo Tower fork).

Thin layer over pyvesync 3.5.0 for the CAF-DC111S-AEU. Everything sent here was
verified on a CAF-DC111S-AEU; move to pyvesync once upstream
supports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from pyvesync.base_devices.fryer_base import VeSyncFryer
from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.const import BYPASSV2_SUB_DEVICE_PAYLOAD, AirFryerChamber, AirFryerCookStatus

from homeassistant.util import dt as dt_util

from .common import is_air_fryer

_LOGGER = logging.getLogger(__name__)

ZONES: tuple[AirFryerChamber, ...] = (AirFryerChamber.CHAMBER_1, AirFryerChamber.CHAMBER_2)

# Zone status options (sensor enum) and their mapping from pyvesync.
ZONE_STATUS_OPTIONS = ["off", "ready", "cooking", "paused", "waiting", "basket_out", "done"]
_ZONE_STATUS_MAP: dict[AirFryerCookStatus, str] = {
    AirFryerCookStatus.STANDBY: "off",
    AirFryerCookStatus.READY: "ready",
    AirFryerCookStatus.COOKING: "cooking",
    AirFryerCookStatus.HEATING: "cooking",
    AirFryerCookStatus.COOK_STOP: "paused",
    AirFryerCookStatus.HOLD: "waiting",
    AirFryerCookStatus.PULL_OUT: "basket_out",
    AirFryerCookStatus.COOK_END: "done",
}
ACTIVE_ZONE_STATES = {"ready", "cooking", "paused", "waiting", "basket_out"}
RUNNING_ZONE_STATES = {"cooking", "waiting"}

MODE_OPTIONS = ["off", "separate", "match", "sync"]
SYNC_TYPE_TO_MODE = {0: "separate", 1: "match", 2: "sync"}
MODE_TO_SYNC_TYPE = {v: k for k, v in SYNC_TYPE_TO_MODE.items()}

# Program limits from the user manual (docs/programme.md): minutes and step.
PROGRAMS = ["AirFry", "Bake", "Roast", "Grill", "Reheat", "Dry", "Proof"]


@dataclass(frozen=True)
class ProgramLimits:
    """Temperature (°C) and time (min) limits of a program."""

    temp_min: int
    temp_max: int
    temp_step: int
    time_min: int
    time_max: int
    time_step: int
    default_temp: int
    default_time: int


PROGRAM_LIMITS: dict[str, ProgramLimits] = {
    "AirFry": ProgramLimits(120, 230, 5, 1, 60, 1, 195, 10),
    "Bake": ProgramLimits(80, 205, 5, 1, 60, 1, 165, 20),
    "Roast": ProgramLimits(175, 230, 5, 1, 60, 1, 220, 12),
    "Grill": ProgramLimits(160, 230, 5, 1, 60, 1, 230, 10),
    "Reheat": ProgramLimits(40, 205, 5, 1, 60, 1, 165, 5),
    "Dry": ProgramLimits(35, 95, 5, 30, 1440, 30, 55, 360),
    "Proof": ProgramLimits(30, 45, 1, 15, 720, 15, 30, 60),
}

RECIPE_TYPE = 3  # sent by the app for preset programs


class FryerCommandError(Exception):
    """A fryer command was refused by the cloud."""

    def __init__(self, method: str, code: Any) -> None:
        """Initialize."""
        super().__init__(f"{method} refused (code {code})")
        self.method = method
        self.code = code


def is_dual_fryer(device: VeSyncBaseDevice) -> bool:
    """Return True for dual-zone fryers handled by this module."""
    return is_air_fryer(device) and bool(getattr(device, "is_dual_chamber", False))


def zone_status(device: VeSyncFryer, zone: AirFryerChamber) -> str | None:
    """Return the zone status option."""
    state = device.get_chamber_state(zone)
    if state is None or state.cook_status is None:
        return None
    return _ZONE_STATUS_MAP.get(state.cook_status)


def zone_end_time(device: VeSyncFryer, zone: AirFryerChamber) -> datetime | None:
    """Return when the zone finishes, while it cooks or waits (Sync)."""
    if zone_status(device, zone) not in RUNNING_ZONE_STATES:
        return None
    state = device.get_chamber_state(zone)
    remaining = state.total_time_remaining if state else None
    if remaining is None:
        return None
    # Round to whole minutes so the state doesn't change on every poll.
    end = dt_util.utcnow() + timedelta(seconds=remaining)
    return end.replace(second=0, microsecond=0) + timedelta(minutes=1 if end.second >= 30 else 0)


def zone_values(device: VeSyncFryer, zone: AirFryerChamber) -> tuple[str | None, int | None, int | None]:
    """Return (program, temperature °C, time in minutes) of the zone's current cook."""
    state = device.get_chamber_state(zone)
    if state is None or zone_status(device, zone) in (None, "off"):
        return None, None, None
    minutes = round(state.cook_set_time / 60) if state.cook_set_time else None
    return state.cook_mode, state.cook_set_temp, minutes


def any_zone_active(device: VeSyncFryer) -> bool:
    """Return True if a zone is doing something that needs faster polling."""
    return any(zone_status(device, z) in ACTIVE_ZONE_STATES for z in ZONES)


def reported_sync_type(device: VeSyncFryer) -> int | None:
    """Return syncType from the last status poll (pyvesync only keeps Sync as a bool)."""
    resp = device.last_response
    data = getattr(resp, "response_data", None) or {}
    inner = (data.get("result") or {}).get("result") or {}
    if "statusList" not in inner:
        return None
    return inner.get("syncType")


def fryer_mode(device: VeSyncFryer, sync_type: int | None) -> str:
    """Return the device mode option."""
    if not any(zone_status(device, z) in ACTIVE_ZONE_STATES for z in ZONES):
        return "off"
    return SYNC_TYPE_TO_MODE.get(sync_type or 0, "separate")


# --- Commands -----------------------------------------------------------------


async def _call(device: VeSyncFryer, method: str, data: dict[str, Any]) -> dict[str, Any]:
    resp = await device.call_bypassv2_api(
        payload_method=method, data=data, payload_update=dict(BYPASSV2_SUB_DEVICE_PAYLOAD)
    )
    inner = (resp or {}).get("result") or {}
    if not resp or resp.get("code") != 0 or inner.get("code") != 0:
        raise FryerCommandError(method, inner.get("code", (resp or {}).get("code")))
    return inner.get("result") or {}


def _mode_config(device: VeSyncFryer, program: str):
    """Return pyvesync's preset config (recipe id/name) for an API mode string."""
    for config in device.cook_modes.values():
        if config.api_mode == program:
            return config
    raise ValueError(f"Unknown program {program}")


def cook_config(
    device: VeSyncFryer, zone: int, program: str, temperature: int, minutes: int
) -> dict[str, Any]:
    """Build one cookConfigs item."""
    config = _mode_config(device, program)
    return {
        "chamber": zone,
        "cookSetTime": minutes * 60,
        "cookTemp": temperature,
        "mode": program,
        "recipeId": config.recipe_id,
        "recipeName": config.recipe_name,
        "recipeType": RECIPE_TYPE,
    }


async def start_cook(
    device: VeSyncFryer,
    configs: list[dict[str, Any]],
    *,
    sync_type: int = 0,
    ready_start: bool = False,
) -> None:
    """Start one or both zones (startMultiCook)."""
    work_chamber = configs[0]["chamber"] if len(configs) == 1 else 4
    await _call(
        device,
        "startMultiCook",
        {
            "accountId": device.manager.account_id,
            "cookConfigs": configs,
            "readyStart": ready_start,
            "syncType": sync_type,
            "tempUnit": "c",
            "workChamber": work_chamber,
        },
    )


async def end_zone(device: VeSyncFryer, zone: int) -> None:
    """End one zone."""
    await _call(device, "endCook", {"chamber": zone})


async def pause_zone(device: VeSyncFryer, zone: int) -> None:
    """Pause one zone."""
    await _call(device, "pauseWork", {"chamber": zone})


async def resume_zone(device: VeSyncFryer, zone: int) -> None:
    """Resume one zone."""
    await _call(device, "resumeWork", {"chamber": zone})


async def quit_sync(device: VeSyncFryer) -> None:
    """Leave Sync; a waiting zone starts at once."""
    await _call(device, "quitSyncFinish", {})


async def get_presets(device: VeSyncFryer) -> dict[str, dict[str, Any]]:
    """Return the device's program presets keyed by mode."""
    result = await _call(device, "getPresetRecipe", {})
    return {item["mode"]: item for item in result.get("menu", []) if "mode" in item}


async def update_preset(device: VeSyncFryer, preset: dict[str, Any]) -> None:
    """Change a device preset (full menu item)."""
    await _call(device, "updatePresetRecipe", preset)


async def reset_preset(device: VeSyncFryer, program: str) -> None:
    """Reset a device preset to its factory value."""
    await _call(device, "resetPresetRecipe", {"mode": program})

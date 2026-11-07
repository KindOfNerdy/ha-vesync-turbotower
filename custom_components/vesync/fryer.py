"""Dual-basket air fryer support (Turbo Tower fork).

Thin layer over pyvesync 3.5.0 for the CAF-DC111S-AEU. Everything sent here was
verified on a CAF-DC111S-AEU; move to pyvesync once upstream
supports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from pyvesync.base_devices.fryer_base import FryerState, VeSyncFryer
from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.const import BYPASSV2_SUB_DEVICE_PAYLOAD, AirFryerChamber, AirFryerCookStatus

from homeassistant.util import dt as dt_util

from .common import is_air_fryer

_LOGGER = logging.getLogger(__name__)

BASKETS: tuple[AirFryerChamber, ...] = (AirFryerChamber.CHAMBER_1, AirFryerChamber.CHAMBER_2)

# pyvesync cook states, grouped for the integration's logic.
RUNNING_STATUSES = {
    AirFryerCookStatus.COOKING,
    AirFryerCookStatus.HEATING,
    AirFryerCookStatus.HOLD,
}
# Statuses of a cook that can be ended with endCook (device tests; COOK_END too).
STOPPABLE_STATUSES = RUNNING_STATUSES | {
    AirFryerCookStatus.READY,
    AirFryerCookStatus.COOK_STOP,
    AirFryerCookStatus.PREHEAT_STOP,
    AirFryerCookStatus.PULL_OUT,
    AirFryerCookStatus.COOK_END,
}
IDLE_STATUSES = {AirFryerCookStatus.STANDBY, AirFryerCookStatus.COOK_END}
SYNC_TYPES = {"separate": 0, "match": 1, "sync": 2}

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


# Only the Turbo Tower Pro: programs, limits and commands were verified on it.
# Other dual-chamber fryers (e.g. TwinFry) keep the standard behavior.
TURBO_TOWER_TYPES = ("CAF-DC111S-AEU",)


def is_dual_fryer(device: VeSyncBaseDevice) -> bool:
    """Return True for dual-basket fryers handled by this module (Turbo Tower)."""
    return (
        is_air_fryer(device)
        and device.device_type in TURBO_TOWER_TYPES
        and bool(getattr(device, "is_dual_chamber", False))
    )


def basket_state(device: VeSyncFryer, basket: AirFryerChamber | int) -> FryerState | None:
    """Return pyvesync's state of one basket."""
    return device.get_chamber_state(AirFryerChamber(int(basket)))


def cook_status(device: VeSyncFryer, basket: AirFryerChamber | int) -> AirFryerCookStatus | None:
    """Return the cook status of one basket."""
    state = basket_state(device, basket)
    return state.cook_status if state else None


def panel_selected(device: VeSyncFryer, basket: AirFryerChamber | int) -> bool:
    """Return True if a program was chosen on the control panel but not started.

    The cloud reports ``standby`` with the chosen values (device test "observe").
    It refuses endCook then (11920000), so only the fryer can cancel it.
    pyvesync 3.5.0 drops these values; see compat._fix_standby_selection.
    """
    state = basket_state(device, basket)
    return (
        state is not None
        and state.cook_status == AirFryerCookStatus.STANDBY
        and bool(state.cook_set_time)
    )


def is_busy(device: VeSyncFryer, basket: AirFryerChamber | int) -> bool:
    """Return True if the basket has a cook (also chosen on the panel or basket out)."""
    status = cook_status(device, basket)
    if status is None:
        return False
    return status not in IDLE_STATUSES or panel_selected(device, basket)


def can_stop(device: VeSyncFryer, basket: AirFryerChamber | int) -> bool:
    """Return True if endCook is expected to work for the basket.

    An idle fryer with an empty slot also reports ``pullOut``, but without cook
    values; there is nothing to end then (11923000).
    """
    state = basket_state(device, basket)
    if state is None or state.cook_status not in STOPPABLE_STATUSES:
        return False
    return state.cook_status != AirFryerCookStatus.PULL_OUT or bool(state.cook_set_time)


def state_end_time(state: FryerState) -> datetime | None:
    """Return when a basket finishes, while it cooks or waits (Sync)."""
    if state.cook_status not in RUNNING_STATUSES:
        return None
    remaining = state.total_time_remaining
    if remaining is None:
        return None
    # Round to whole minutes so the state doesn't change on every poll.
    end = dt_util.utcnow() + timedelta(seconds=remaining)
    return end.replace(second=0, microsecond=0) + timedelta(minutes=1 if end.second >= 30 else 0)


def basket_values(
    device: VeSyncFryer, basket: AirFryerChamber | int
) -> tuple[str | None, int | None, int | None]:
    """Return (program, temperature °C, time in minutes) of the basket's cook."""
    state = basket_state(device, basket)
    if state is None or not is_busy(device, basket):
        return None, None, None
    minutes = round(state.cook_set_time / 60) if state.cook_set_time else None
    return state.cook_mode, state.cook_set_temp, minutes


def any_basket_active(device: VeSyncFryer) -> bool:
    """Return True if a basket is doing something that needs faster polling."""
    return any(
        is_busy(device, b) and cook_status(device, b) != AirFryerCookStatus.COOK_END
        for b in BASKETS
    )


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
    device: VeSyncFryer, basket: int, program: str, temperature: int, minutes: int
) -> dict[str, Any]:
    """Build one cookConfigs item."""
    config = _mode_config(device, program)
    return {
        "chamber": basket,
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
    """Start one or both baskets (startMultiCook).

    ready_start=True only sends the program; it starts with the button on the fryer.
    """
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


BOTH_BASKETS = 4  # chamber value for both baskets (endCook/pauseWork/resumeWork)


async def _send(device: VeSyncFryer, method: str, baskets: list[int]) -> None:
    """Send a command for one basket, or once for both; fall back to one per basket.

    One request with chamber 4 works while both baskets run (device tests
    "endboth", "pauseall"); after a dissolved Sync the cloud refuses it
    (11920000), so then each basket is sent on its own.
    """
    if len(baskets) == 2:
        try:
            await _call(device, method, {"chamber": BOTH_BASKETS})
        except FryerCommandError:
            pass
        else:
            return
    for basket in baskets:
        await _call(device, method, {"chamber": basket})


async def end_baskets(device: VeSyncFryer, baskets: list[int]) -> None:
    """End the given baskets."""
    await _send(device, "endCook", baskets)


async def pause_baskets(device: VeSyncFryer, baskets: list[int]) -> None:
    """Pause the given baskets."""
    await _send(device, "pauseWork", baskets)


async def resume_baskets(device: VeSyncFryer, baskets: list[int]) -> None:
    """Resume the given baskets."""
    await _send(device, "resumeWork", baskets)


async def quit_sync(device: VeSyncFryer) -> None:
    """Leave Sync; a waiting basket starts at once."""
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


# --- Form (values entered in HA before starting) ------------------------------

PROGRAM_OPTIONS = [p.lower() for p in PROGRAMS]  # select option keys
OPTION_TO_PROGRAM = {p.lower(): p for p in PROGRAMS}
START_MODE_OPTIONS = ["separate", "sync", "match"]


@dataclass
class BasketForm:
    """Program, temperature (°C) and time (min) entered for one basket."""

    program: str
    temperature: int
    minutes: int


@dataclass
class FryerForm:
    """Form state of one fryer."""

    baskets: dict[int, BasketForm]
    start_mode: str = "separate"
    edited: bool = False  # True once the user changed a basket value


def preset_values(presets: dict[str, dict] | None, program: str) -> tuple[int, int]:
    """Return (temperature, minutes) for a program: device preset, else manual default."""
    limits = PROGRAM_LIMITS[program]
    preset = (presets or {}).get(program) or {}
    temp = preset.get("cookTemp") if preset.get("tempUnit", "c") == "c" else None
    secs = preset.get("cookSetTime")
    temperature = clamp_temperature(program, temp if temp else limits.default_temp)
    minutes = clamp_minutes(program, round(secs / 60) if secs else limits.default_time)
    return temperature, minutes


def clamp_temperature(program: str, value: float) -> int:
    """Clamp and round a temperature to the program's limits."""
    lim = PROGRAM_LIMITS[program]
    value = round(value / lim.temp_step) * lim.temp_step
    return int(min(max(value, lim.temp_min), lim.temp_max))


def clamp_minutes(program: str, value: float) -> int:
    """Clamp and round a time to the program's limits."""
    lim = PROGRAM_LIMITS[program]
    value = round(value / lim.time_step) * lim.time_step
    return int(min(max(value, lim.time_min), lim.time_max))


def validate(program: str, temperature: int, minutes: int) -> None:
    """Raise ValueError if values are outside the program's limits."""
    lim = PROGRAM_LIMITS[program]
    if not lim.temp_min <= temperature <= lim.temp_max or temperature % lim.temp_step:
        raise ValueError(
            f"{program}: {temperature} °C outside {lim.temp_min}-{lim.temp_max} °C "
            f"(step {lim.temp_step})"
        )
    if not lim.time_min <= minutes <= lim.time_max or minutes % lim.time_step:
        raise ValueError(
            f"{program}: {minutes} min outside {lim.time_min}-{lim.time_max} min "
            f"(step {lim.time_step})"
        )


def new_form(presets: dict[str, dict] | None) -> FryerForm:
    """Create a form with Air Fry and the device's defaults in both baskets."""
    baskets = {}
    for basket in BASKETS:
        temperature, minutes = preset_values(presets, "AirFry")
        baskets[int(basket)] = BasketForm("AirFry", temperature, minutes)
    return FryerForm(baskets=baskets)

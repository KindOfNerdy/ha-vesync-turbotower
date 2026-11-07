"""Runtime fixes for pyvesync 3.5.0 (Turbo Tower fork).

Each fix checks whether it is still needed and does nothing otherwise, so a
newer pyvesync that fixes the problem upstream (possibly differently) is left
alone. Remove a fix once the pinned pyvesync contains the upstream change.
"""

from __future__ import annotations

from dataclasses import replace
import inspect
import logging
from types import MappingProxyType

from pyvesync import device_map
from pyvesync.const import AirFryerCookModes, AirFryerCookStatus
from pyvesync.device_container import DeviceContainer

_LOGGER = logging.getLogger(__name__)

TURBO_TOWER_TYPES = ("CAF-DC111S-AEU",)
BAKE_MIN_TEMP_C = 80  # user manual + verified on the device (pyvesync issue #598)
BAKE_MIN_TEMP_F = 175  # Cosori FAQ: 175-400 °F

_applied = False


def apply() -> None:
    """Apply all needed fixes once, before devices are created."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    _applied = True
    _fix_unknown_device_logging()
    for entry in device_map.air_fryer_modules:
        if any(t in entry.dev_types for t in TURBO_TOWER_TYPES):
            _fix_cook_end_status(entry)
            _fix_bake_min_temp(entry)


def _fix_unknown_device_logging() -> None:
    """Unknown devices crash get_devices() (pyvesync PR #589).

    3.5.0 logs ``device.to_json(indent=True)`` for unmapped device types; the
    argument is evaluated even with debug logging off and raises TypeError with
    mashumaro >= 3.23. That aborts discovery, so supported devices listed after
    the unknown one (here: the Core300S purifier after the CRC-R501) are lost.
    """
    original = DeviceContainer._build_device_instance  # noqa: SLF001
    try:
        source = inspect.getsource(original)
    except (OSError, TypeError):
        return
    if "to_json(indent=True)" not in source:
        return

    def _build_device_instance(self, device, manager):
        if device_map.get_device_config(device.deviceType) is None:
            _LOGGER.debug("Device type %s not supported by pyvesync", device.deviceType)
            return None
        return original(self, device, manager)

    DeviceContainer._build_device_instance = _build_device_instance  # noqa: SLF001
    _LOGGER.debug("Applied fix for unknown device logging (pyvesync #589)")


def _fix_cook_end_status(entry: device_map.AirFryerMap) -> None:
    """Map ``cookEnd`` (pyvesync PR #590); otherwise a finished zone keeps showing cooking."""
    if "cookEnd" in entry.status_map:
        return
    entry.status_map = MappingProxyType(
        {**entry.status_map, "cookEnd": AirFryerCookStatus.COOK_END}
    )
    _LOGGER.debug("Applied cookEnd status fix (pyvesync #590)")


def _fix_bake_min_temp(entry: device_map.AirFryerMap) -> None:
    """Allow Bake from 80 °C as in the manual (pyvesync issue #598)."""
    bake = entry.cook_modes.get(AirFryerCookModes.BAKE)
    if bake is None or bake.temp_c is None or bake.temp_c.min_temp <= BAKE_MIN_TEMP_C:
        return
    changes = {"temp_c": replace(bake.temp_c, min_temp=BAKE_MIN_TEMP_C)}
    if bake.temp_f is not None and bake.temp_f.min_temp > BAKE_MIN_TEMP_F:
        changes["temp_f"] = replace(bake.temp_f, min_temp=BAKE_MIN_TEMP_F)
    entry.cook_modes[AirFryerCookModes.BAKE] = replace(bake, **changes)
    _LOGGER.debug("Applied Bake minimum temperature fix (pyvesync #598)")

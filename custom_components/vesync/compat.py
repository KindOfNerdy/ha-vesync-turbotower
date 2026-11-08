"""Runtime fixes for pyvesync 3.5.1 (Turbo Tower fork).

Each fix checks whether it is still needed and does nothing otherwise, so a
newer pyvesync that fixes the problem upstream (possibly differently) is left
alone. Remove a fix once the pinned pyvesync contains the upstream change.
"""

from __future__ import annotations

from dataclasses import replace
import inspect
import logging

from dataclasses import MISSING, fields

from pyvesync import VeSync, device_map
from pyvesync.devices.vesynckitchen import VeSyncDualAirFryer
from pyvesync.const import AirFryerCookModes, AirFryerCookStatus, ConnectionStatus
from pyvesync.models.vesync_models import RequestFirmwareModel, ResponseFirmwareModel
from pyvesync.utils.helpers import Helpers

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
    _fix_air_fryer_firmware()
    _fix_standby_selection()
    for entry in device_map.air_fryer_modules:
        if any(t in entry.dev_types for t in TURBO_TOWER_TYPES):
            _fix_bake_min_temp(entry)


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


def _fix_air_fryer_firmware() -> None:
    """Also check firmware of air fryers.

    pyvesync 3.5.0 leaves air fryers out of getFirmwareUpdateInfoList, so their
    firmware shows as unknown. The endpoint answers fine for the CAF-DC111S-AEU
    (main 2.0.02, MCU 1.0.10), so query air fryers in a second request.
    """
    original = VeSync.check_firmware
    try:
        source = inspect.getsource(original)
    except (OSError, TypeError):
        return
    if "AIR_FRYER" not in source:
        return

    async def check_firmware(self: VeSync) -> bool:
        result = await original(self)
        cids = [
            dev.cid
            for dev in self.devices.air_fryers
            if dev.state.connection_status == ConnectionStatus.ONLINE
        ]
        if not cids:
            return result
        names = tuple(
            f.name
            for f in fields(RequestFirmwareModel)
            if f.default_factory is MISSING and f.default is MISSING
        )
        body = Helpers.get_manager_attributes(self, names)
        body["cidList"] = cids
        try:
            resp, _ = await self.async_call_api(
                "/cloud/v2/deviceManaged/getFirmwareUpdateInfoList",
                "post",
                json_object=RequestFirmwareModel(**body),
            )
            if resp and resp.get("code") == 0:
                model = ResponseFirmwareModel.from_dict(resp)
                self._update_fw_version(model.result.cidFwInfoList)  # noqa: SLF001
        except Exception as err:  # noqa: BLE001 - never break setup for firmware info
            _LOGGER.debug("Air fryer firmware check failed: %s", err)
        return result

    VeSync.check_firmware = check_firmware
    _LOGGER.debug("Applied air fryer firmware fix")


def _fix_standby_selection() -> None:
    """Keep the values of a program chosen on the control panel.

    With the fryer on and a program chosen but not started, the cloud reports
    ``standby`` with cookTemp/cookSetTime/mode set (device test "observe"); a
    switched-off basket reports zeros. pyvesync 3.5.0 clears them, so HA can't
    tell "chosen on the panel" from "off". Keep them on the standby state.
    Candidate for a pyvesync PR.
    """
    original = VeSyncDualAirFryer._apply_chamber_status  # noqa: SLF001

    def _apply_chamber_status(self, status_item):
        chamber = original(self, status_item)
        if (
            chamber is not None
            and status_item.cookStatus == AirFryerCookStatus.STANDBY.value
            and status_item.cookSetTime
        ):
            state = self.get_chamber_state(chamber)
            if state is not None and state.cook_set_time is None:
                state.cook_set_time = self.convert_time_for_state(status_item.cookSetTime)
                state.cook_set_temp = status_item.cookTemp or None
                state.cook_mode = status_item.mode or state.cook_mode
        return chamber

    VeSyncDualAirFryer._apply_chamber_status = _apply_chamber_status  # noqa: SLF001
    _LOGGER.debug("Applied standby selection fix")

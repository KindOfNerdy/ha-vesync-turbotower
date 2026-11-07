"""Class to manage VeSync data updates."""

from datetime import timedelta
import logging
import time
from typing import override

from pyvesync import VeSync
from pyvesync.utils.errors import VeSyncError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import UPDATE_INTERVAL, UPDATE_INTERVAL_ENERGY
from .fryer import (
    FryerCommandError,
    FryerForm,
    any_zone_active,
    get_presets,
    is_dual_fryer,
    new_form,
    reported_sync_type,
)

# Turbo Tower fork: poll faster while a fryer zone is active, presets once a day.
UPDATE_INTERVAL_FRYER_ACTIVE = 20
UPDATE_INTERVAL_FRYER_PRESETS = 24 * 60 * 60

_LOGGER = logging.getLogger(__name__)

type VesyncConfigEntry = ConfigEntry[VeSyncDataCoordinator]


class VeSyncDataCoordinator(DataUpdateCoordinator[None]):
    """Class representing data coordinator for VeSync devices."""

    config_entry: VesyncConfigEntry
    update_time: float | None = None
    presets_time: float | None = None

    def __init__(
        self, hass: HomeAssistant, config_entry: VesyncConfigEntry, manager: VeSync
    ) -> None:
        """Initialize."""
        self.manager = manager
        # Per fryer (cid): syncType of the last poll and the device presets.
        self.fryer_sync_type: dict[str, int | None] = {}
        self.fryer_presets: dict[str, dict[str, dict]] = {}
        self.fryer_forms: dict[str, FryerForm] = {}

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="VeSyncDataCoordinator",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    def should_update_energy(self) -> bool:
        """Test if specified update interval has been exceeded."""
        if self.update_time is None:
            return True

        return time.time() - self.update_time >= UPDATE_INTERVAL_ENERGY

    @override
    async def _async_update_data(self) -> None:
        """Fetch data from API endpoint."""
        try:
            await self.manager.update_all_devices()

            if self.should_update_energy():
                self.update_time = time.time()
                for outlet in self.manager.devices.outlets:
                    await outlet.update_energy()
        except VeSyncError as err:
            raise UpdateFailed(f"The service is unavailable: {err}") from err

        await self._async_update_fryers()

    def fryer_form(self, cid: str) -> FryerForm:
        """Return the form of a fryer, created with the device defaults."""
        if cid not in self.fryer_forms:
            self.fryer_forms[cid] = new_form(self.fryer_presets.get(cid))
        return self.fryer_forms[cid]

    async def _async_update_fryers(self) -> None:
        """Track fryer sync type, presets and polling speed."""
        fryers = [dev for dev in self.manager.devices.air_fryers if is_dual_fryer(dev)]
        for fryer in fryers:
            self.fryer_sync_type[fryer.cid] = reported_sync_type(fryer)

        if fryers and (
            self.presets_time is None
            or time.time() - self.presets_time >= UPDATE_INTERVAL_FRYER_PRESETS
        ):
            self.presets_time = time.time()
            for fryer in fryers:
                try:
                    self.fryer_presets[fryer.cid] = await get_presets(fryer)
                    form = self.fryer_forms.get(fryer.cid)
                    if form is not None and not form.edited:
                        fresh = new_form(self.fryer_presets[fryer.cid])
                        form.zones = fresh.zones
                except (FryerCommandError, VeSyncError) as err:
                    _LOGGER.warning("Could not read presets of %s: %s", fryer.device_name, err)

        fast = any(any_zone_active(fryer) for fryer in fryers)
        self.update_interval = timedelta(
            seconds=UPDATE_INTERVAL_FRYER_ACTIVE if fast else UPDATE_INTERVAL
        )

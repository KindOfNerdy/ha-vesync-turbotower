"""Event entities for dual-basket air fryers (Turbo Tower fork).

One event entity per basket; events are derived from status changes seen by
the coordinator (polling, so up to one poll interval late).
"""

from datetime import datetime, timedelta
from typing import override

from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.const import AirFryerChamber, AirFryerCookStatus

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import VS_DEVICES, VS_DISCOVERY
from .coordinator import VesyncConfigEntry, VeSyncDataCoordinator
from .entity import VeSyncBaseEntity
from .fryer import BASKETS, basket_state, basket_values, is_dual_fryer, panel_selected

PARALLEL_UPDATES = 0

EVENT_TYPES = ["ready", "started", "paused", "resumed", "basket_out", "finished", "stopped"]
ACTIVE = {"ready", "cooking", "paused", "waiting", "basket_out"}
# A basket switched off at most this long before its expected end counts as
# finished: people switch off when it beeps, before the next poll sees cookEnd.
FINISH_TOLERANCE = timedelta(seconds=5)


# pyvesync status -> simplified status used to derive events.
_SIMPLE = {
    AirFryerCookStatus.STANDBY: "off",
    AirFryerCookStatus.READY: "ready",
    AirFryerCookStatus.COOKING: "cooking",
    AirFryerCookStatus.HEATING: "cooking",
    AirFryerCookStatus.COOK_STOP: "paused",
    AirFryerCookStatus.PREHEAT_STOP: "paused",
    AirFryerCookStatus.HOLD: "waiting",
    AirFryerCookStatus.PULL_OUT: "basket_out",
    AirFryerCookStatus.COOK_END: "done",
}


def simple_status(device, basket: AirFryerChamber) -> str | None:
    """Return the simplified status of a basket (a panel selection counts as ready)."""
    state = basket_state(device, basket)
    if state is None or state.cook_status is None:
        return None
    if panel_selected(device, basket):
        return "ready"
    return _SIMPLE.get(state.cook_status)


def status_in_cook(status: str | None) -> bool:
    """Return True if the status belongs to a cook that is ready or running."""
    return status in ("ready", "cooking", "paused", "waiting")


def event_for(old: str | None, new: str | None) -> str | None:
    """Return the event type for a basket status change, if any."""
    if old is None or new is None or old == new:
        return None
    if new == "ready":
        return "ready"
    if new == "cooking":
        return "resumed" if old in ("paused", "basket_out") else "started"
    if new == "paused":
        return "paused"
    if new == "basket_out":
        return "basket_out"
    if new == "done":
        return "finished"
    if new == "off" and old in ACTIVE:
        return "stopped"
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VesyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up fryer basket events."""
    coordinator = config_entry.runtime_data

    @callback
    def discover(devices: list[VeSyncBaseDevice]) -> None:
        async_add_entities(
            VeSyncFryerBasketEvent(dev, coordinator, basket)
            for dev in devices
            if is_dual_fryer(dev)
            for basket in BASKETS
        )

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, VS_DISCOVERY.format(VS_DEVICES), discover)
    )
    discover(coordinator.manager.devices)


class VeSyncFryerBasketEvent(VeSyncBaseEntity, EventEntity):
    """Started, paused, finished … of one fryer basket."""

    _attr_event_types = EVENT_TYPES
    _attr_translation_key = "basket_event"

    def __init__(
        self,
        device: VeSyncBaseDevice,
        coordinator: VeSyncDataCoordinator,
        basket: AirFryerChamber,
    ) -> None:
        """Initialize."""
        super().__init__(device, coordinator)
        self._basket = basket
        self._attr_unique_id = f"{self.base_unique_id}-basket{int(basket)}-event"
        self._attr_translation_placeholders = {"basket": str(int(basket))}
        self._last_status: str | None = simple_status(device, basket)
        self._last_values = basket_values(device, basket)
        self._expected_end: datetime | None = None
        self._finished = False  # the current cook already reported finished
        self._in_cook = status_in_cook(self._last_status)  # a cook is ready/running

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Fire an event when the basket status changes."""
        status = simple_status(self.device, self._basket)
        event_type = event_for(self._last_status, status)
        if (
            event_type == "stopped"
            and self._last_status == "cooking"
            and self._expected_end is not None
            and dt_util.utcnow() >= self._expected_end - FINISH_TOLERANCE
        ):
            event_type = "finished"
        # Basket out only matters during a cook; an empty slot while idle is not news,
        # and putting a basket back while idle is not a cancel.
        if event_type == "basket_out" and self._last_status not in ("cooking", "paused", "waiting"):
            event_type = None
        if event_type == "stopped" and (self._finished or not self._in_cook):
            event_type = None  # off after done, or nothing was cooking
        if event_type in ("ready", "started"):
            self._finished = False
        elif event_type == "finished":
            self._finished = True
        if status_in_cook(status):
            self._in_cook = True
        elif status in ("off", "done"):
            self._in_cook = False
        self._last_status = status
        state = basket_state(self.device, self._basket)
        remaining = state.total_time_remaining if state else None
        self._expected_end = (
            dt_util.utcnow() + timedelta(seconds=remaining)
            if status == "cooking" and remaining is not None
            else None
        )
        values = basket_values(self.device, self._basket)
        if values[0] is None:  # basket already off: report what it was doing
            values = self._last_values
        self._last_values = values
        if event_type is not None:
            program, temperature, minutes = values
            self._trigger_event(
                event_type,
                {"program": program, "temperature": temperature, "time": minutes},
            )
        super()._handle_coordinator_update()

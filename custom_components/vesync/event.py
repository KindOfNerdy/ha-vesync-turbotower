"""Event entities for dual-zone air fryers (Turbo Tower fork).

One event entity per zone; events are derived from zone status changes seen
by the coordinator (polling, so up to one poll interval late).
"""

from typing import override

from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.const import AirFryerChamber

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import VS_DEVICES, VS_DISCOVERY
from .coordinator import VesyncConfigEntry, VeSyncDataCoordinator
from .entity import VeSyncBaseEntity
from .fryer import ZONES, is_dual_fryer, zone_status, zone_values

PARALLEL_UPDATES = 0

EVENT_TYPES = ["ready", "started", "paused", "resumed", "basket_out", "finished", "stopped"]
ACTIVE = {"ready", "cooking", "paused", "waiting", "basket_out"}


def event_for(old: str | None, new: str | None) -> str | None:
    """Return the event type for a zone status change, if any."""
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
    """Set up fryer zone events."""
    coordinator = config_entry.runtime_data

    @callback
    def discover(devices: list[VeSyncBaseDevice]) -> None:
        async_add_entities(
            VeSyncFryerZoneEvent(dev, coordinator, zone)
            for dev in devices
            if is_dual_fryer(dev)
            for zone in ZONES
        )

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, VS_DISCOVERY.format(VS_DEVICES), discover)
    )
    discover(coordinator.manager.devices)


class VeSyncFryerZoneEvent(VeSyncBaseEntity, EventEntity):
    """Started, paused, finished … of one fryer zone."""

    _attr_event_types = EVENT_TYPES
    _attr_translation_key = "zone_event"

    def __init__(
        self,
        device: VeSyncBaseDevice,
        coordinator: VeSyncDataCoordinator,
        zone: AirFryerChamber,
    ) -> None:
        """Initialize."""
        super().__init__(device, coordinator)
        self._zone = zone
        self._attr_unique_id = f"{self.base_unique_id}-zone{int(zone)}-event"
        self._attr_translation_placeholders = {"zone": str(int(zone))}
        self._last_status: str | None = zone_status(device, zone)

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Fire an event when the zone status changes."""
        status = zone_status(self.device, self._zone)
        event_type = event_for(self._last_status, status)
        self._last_status = status
        if event_type is not None:
            program, temperature, minutes = zone_values(self.device, self._zone)
            self._trigger_event(
                event_type,
                {"program": program, "temperature": temperature, "time": minutes},
            )
        super()._handle_coordinator_update()

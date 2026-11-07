# VeSync with Cosori Turbo Tower Pro

[Deutsch](README.md)

Fork of the official Home Assistant **VeSync** integration that adds support for the **Cosori Turbo Tower Pro Smart** (CAF-DC111S-AEU / CAF-DC113S-ADE), a dual-zone air fryer.

> **Unofficial.** Replaces the built-in VeSync integration (same domain `vesync`). Your existing login and devices (e.g. purifiers) are kept. The goal is to upstream everything to [pyvesync](https://github.com/webdjoe/pyvesync) and Home Assistant Core, which will make this fork obsolete.

## Added

- Status per zone (off, ready, cooking, paused, waiting, basket out, done)
- Finish time per zone
- Mode (separate, match, sync)
- Faster polling while a zone is active
- Program (dropdown), temperature and time per zone; values come from the device's presets
- Start mode for both zones: separate, sync (finish together), match
- "Confirm start on device" (on by default): the program is only sent, you start it on the fryer
- Buttons: start zone, start both, stop zone, stop all, pause/resume per zone and for all
- Events per zone for automations: ready, started, paused, resumed, basket out, finished, stopped
- Firmware shown for the air fryer

- Actions (services) for recipes and automations:
  - `vesync.start_cook` – one zone or both (independent, sync, match); empty values use the fryer's preset
  - `vesync.stop`, `vesync.pause`, `vesync.resume` – zone 1, 2 or all
  - `vesync.quit_sync` – leave sync
  - `vesync.set_preset`, `vesync.reset_preset` – change/reset program presets in the fryer

Example recipe script:

```yaml
action: vesync.start_cook
data:
  zone: "1"
  program: airfry
  temperature: 200
  duration: 18
```

## Fixes on top of pyvesync 3.5.0

Applied only while pyvesync still needs them:

- Unsupported devices in the account no longer stop other devices from being discovered ([#589](https://github.com/webdjoe/pyvesync/pull/589))
- Cook end (`cookEnd`) is recognized ([#590](https://github.com/webdjoe/pyvesync/pull/590))
- Bake from 80 °C as in the manual ([#598](https://github.com/webdjoe/pyvesync/issues/598))
- Air fryer firmware is checked too

## Installation

1. In the Marketplace (HACS), add this repository as a custom repository of type *Integration*.
2. Install "VeSync (Turbo Tower)" and confirm replacing the built-in integration.
3. Restart Home Assistant.

To go back to the official integration, remove it in the Marketplace and restart.

## License

Apache-2.0, like Home Assistant Core. Based on `homeassistant/components/vesync` from home-assistant/core (see `custom_components/vesync/UPSTREAM.md`).

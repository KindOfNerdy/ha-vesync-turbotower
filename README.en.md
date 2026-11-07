# VeSync with Cosori Turbo Tower Pro

[Deutsch](README.md)

Fork of the official Home Assistant **VeSync** integration that adds support for the **Cosori Turbo Tower Pro Smart** (CAF-DC111S-AEU / CAF-DC113S-ADE), a dual-zone air fryer.

> **Unofficial.** Replaces the built-in VeSync integration (same domain `vesync`). Your existing login and devices (e.g. purifiers) are kept. The goal is to upstream everything to [pyvesync](https://github.com/webdjoe/pyvesync) and Home Assistant Core, which will make this fork obsolete.

## Added

- Status per zone (off, ready, cooking, paused, waiting, basket out, done)
- Finish time per zone
- Mode (separate, match, sync)
- Faster polling while a zone is active

In progress: program, temperature and time per zone, start/stop/pause, services for recipes.

## Fixes on top of pyvesync 3.5.0

Applied only while pyvesync still needs them:

- Unsupported devices in the account no longer stop other devices from being discovered ([#589](https://github.com/webdjoe/pyvesync/pull/589))
- Cook end (`cookEnd`) is recognized ([#590](https://github.com/webdjoe/pyvesync/pull/590))
- Bake from 80 °C as in the manual ([#598](https://github.com/webdjoe/pyvesync/issues/598))

## Installation

1. In the Marketplace (HACS), add this repository as a custom repository of type *Integration*.
2. Install "VeSync (Turbo Tower)" and confirm replacing the built-in integration.
3. Restart Home Assistant.

To go back to the official integration, remove it in the Marketplace and restart.

## License

Apache-2.0, like Home Assistant Core. Based on `homeassistant/components/vesync` from home-assistant/core (see `custom_components/vesync/UPSTREAM.md`).

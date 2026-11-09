# VeSync with Cosori Turbo Tower Pro

[Deutsch](README.md)

Fork of the official Home Assistant **VeSync** integration that adds support for the **Cosori Turbo Tower Pro Smart** (CAF-DC111S-AEU / CAF-DC113S-ADE), a dual-basket air fryer.

> **Unofficial.** Replaces the built-in VeSync integration (same domain `vesync`). Your existing login and devices (e.g. purifiers) are kept. The goal is to upstream everything to [pyvesync](https://github.com/webdjoe/pyvesync) and Home Assistant Core, which will make this fork obsolete.

## Safety

> [!WARNING]
> **Remote start is at your own risk.** *Start* and `vesync.start_cook` start heating immediately, without anyone at the appliance. In the EU, the VeSync app asks you to start cooking with the Start/Pause button on the appliance (IEC/EN 60335-1, IEC/EN 60335-2-9). To do that, use *Send to appliance* (`send_only: true`): the settings are transferred, and cooking starts when you press the button. Never leave the appliance unattended while cooking.
>
> This integration is provided as is, without warranty or liability, as stated in the [license](LICENSE).

## Added

Built like the Core integrations for ovens (Home Connect, Miele) and on Core's per-basket model ([home-assistant/core#191014](https://github.com/home-assistant/core/pull/191014)), so it can move into Core later without big changes.

- Sensors per basket as in Core: cooking status, set temperature and time, current temperature, plus **finish time**
- A program chosen on the fryer but not started stays visible (status "Standby" with its values)
- Faster polling while a basket is active
- Program (dropdown), temperature and time per basket; values come from the fryer's presets
- Buttons per basket: **Start** (starts right away), **Send to fryer** (start with the button on the fryer), Pause, Resume, Stop
- For both baskets: start mode (Separate, Sync = finish together, Match), Start both, Send both to fryer, Pause all, Resume all, Stop all, Leave Sync
- Events per basket for automations: ready, started, paused, resumed, basket out, finished, stopped
- Firmware shown for the air fryer
- Actions for recipes:
  - `vesync.start_cook` – one basket or both (separate, Sync, Match); empty values = fryer preset; `send_only: true` = only send to the fryer
  - `vesync.set_preset`, `vesync.reset_preset` – change/reset the fryer's program presets

Good to know: a program chosen on the control panel but not started can only be cancelled on the fryer – the cloud refuses to stop it. Anything sent from Home Assistant can be stopped.

Example recipe script:

```yaml
action: vesync.start_cook
data:
  basket: "1"
  program: airfry
  temperature: 200
  duration: 18
```

### Card and recipes

For a ready-made dashboard there is a separate card, [VeSync Air Fryer Card](https://github.com/KindOfNerdy/vesync-airfryer-card): status, controls for both baskets and a recipe list in one card, installable from the Marketplace. The same repository has a script blueprint ("Turbo Tower recipe") that creates recipes like the example above without writing YAML.

### Upgrading from 0.3.x

Version 0.4.0 renames "zone" to "basket" and replaces entities: new entity IDs, the "Direct start" switch is gone (use the "Send to fryer" buttons), pause and resume are separate buttons, the actions `stop`, `pause`, `resume` and `quit_sync` are gone (use the buttons). In `start_cook`, `zone` is now `basket` and `direct_start` became `send_only`. Remove the old entities under *Settings → Devices* and update dashboards/automations.

## Fixes on top of pyvesync 3.5.1

Based on pyvesync 3.5.1 (which now includes pause/resume, Sync/Match, `cookEnd` and the crash fix from our contributions). Only applied while pyvesync still needs them:

- Bake from 80 °C as in the manual ([#598](https://github.com/webdjoe/pyvesync/issues/598))
- Air fryer firmware is checked too ([#601](https://github.com/webdjoe/pyvesync/pull/601))
- A program chosen on the control panel but not started keeps its values (instead of looking like "off")

## Installation

1. In the Marketplace (HACS), add this repository as a custom repository of type *Integration*.
2. Install "VeSync (Turbo Tower)" and confirm replacing the built-in integration.
3. Restart Home Assistant.

To go back to the official integration, remove it in the Marketplace and restart.

## License

Apache-2.0, like Home Assistant Core. Based on `homeassistant/components/vesync` from home-assistant/core (see `custom_components/vesync/UPSTREAM.md`).

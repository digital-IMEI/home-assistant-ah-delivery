# Albert Heijn Delivery for Home Assistant

Unofficial Home Assistant custom integration that exposes the next Albert Heijn home delivery, Track & Trace information and live arrival windows when Albert Heijn makes them available.

> [!WARNING]
> This integration uses Albert Heijn's private mobile API. It is not affiliated with or supported by Albert Heijn, and API changes may break it.

## Install with HACS

1. Open **HACS → Integrations**.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/digital-IMEI/home-assistant-ah-delivery` as category **Integration**.
4. Install **Albert Heijn Delivery**.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration** and add **Albert Heijn Delivery**.

Requires Home Assistant **2026.8.2 or newer**.

## Dashboard-oriented entities

- **Next delivery** — best available timestamp, with planned window and Track & Trace attributes.
- **Track & Trace message** — the human-readable live message from Albert Heijn. This entity is intentionally retained as a stable dashboard input.
- **Track & Trace status** — e.g. `UNDERWAY` or `UNDERWAY_EARLY` when supplied by Albert Heijn.
- **Delivery today** — binary sensor that is `on` when the currently selected next delivery is scheduled for today, otherwise `off`.

Additional diagnostic entities expose delivery windows, ETA bounds, status and API diagnostics.

## Adaptive polling

Version 1.0.0 reduces unnecessary API traffic when a delivery is still far away:

- more than 7 days away: every 6 hours
- 2–7 days away: every 3 hours
- 24–48 hours away: every hour
- within 24 hours: every 15 minutes
- within 3 hours or with active live ETA / Track & Trace: every 3 minutes
- no open delivery: every 3 hours

The separate Track & Trace request is only made on the actual delivery day.

## Release notes

### 1.0.0

- First stable release.
- Keeps `sensor.ah_track_trace_message` as an essential dashboard data source.
- Adds a **Delivery today** binary sensor for Lovelace visibility conditions and automations.
- Adds adaptive polling to greatly reduce API traffic for deliveries that are still days away.
- Only probes Track & Trace on the delivery day.
- Recognises `UNDERWAY*` Track & Trace states as active live delivery data.

### 0.1.4

- Adds explicit logo assets in addition to the integration icons for HACS and Home Assistant.

### 0.1.3

- Moved the integration to its dedicated GitHub repository.
- Updated HACS, documentation and issue links.
- Kept the official Albert Heijn logo for HACS and Home Assistant.

### 0.1.2

- Replaced all custom artwork with the official Albert Heijn logo.
- Added standard and high-resolution icons for HACS and Home Assistant.

### 0.1.1

- Added HACS support.
- Added local Home Assistant and HACS icons.
- Lowered the minimum supported Home Assistant version to 2026.8.2.

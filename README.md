# Albert Heijn Delivery for Home Assistant

Unofficial Home Assistant custom integration that exposes the next Albert Heijn delivery window and, when available, a live ETA.

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

## Sensors

- Next delivery
- Delivery window start
- Delivery window end
- Live ETA
- Delivery status

Diagnostic sensors may be disabled by default. ETA support depends on the fields currently returned by the Albert Heijn API; the integration falls back to the booked delivery window when live ETA data is unavailable.

## Release notes

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

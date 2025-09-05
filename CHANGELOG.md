# Changelog

## [1.0.21] - $(date +%Y-%m-%d)

### Fixed
- Fixed schema format issues for Home Assistant add-on store compatibility
- Corrected repository configuration to ensure proper add-on discovery

### Added
- Support for `--plan-name` option to override plan name for tariff updates
- New `plan_name` configuration field in Home Assistant UI


## [1.0.20] - $(date +%Y-%m-%d)

### Added
- Support for `--plan-name` option to override plan name for tariff updates
- New `plan_name` configuration field in Home Assistant UI

### Changed
- Enhanced CLI flag building to support optional plan name parameter


## [1.0.3] - 2025-09-04

### Added

- Small fix for mqtt

## [1.0.2] - 2025-09-04

### Added

- Add in-UI documentation (DOCS.md synced from README).
- Add configuration help text via translations.
- Interval restricted to 5 or 30 minutes.

### Fixed

- Dockerfile: venv + Alpine toolchain only during build.
- GHCR manifest creation via `buildx imagetools`.
- README cleanup (removed stray citation markers).

### Changed

- Clone upstream from your fork by default (`starlit-rocketship/amber2sigen`).

## 1.0.0 — 2025-09-04

- feat: initial Home Assistant add-on wrapper around Talie5in/amber2sigen
- feat: optional MQTT status sensor (running/valid/failed)
- docs: README with install/config instructions
- ci: GitHub Actions multi-arch build & manifest

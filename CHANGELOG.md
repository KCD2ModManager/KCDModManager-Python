# Changelog

All notable changes are listed here, newest first. Each release tag `vX.Y.Z` needs a matching
`## [X.Y.Z]` section: the release workflow publishes it as the GitHub release notes and as the
changelog on both Nexus Mods pages, and refuses to release without it.

Write plain bullet points under `### Added`, `### Changed`, `### Fixed` or `### Removed`.
Nexus Mods receives the text without Markdown formatting, so avoid tables and images.

## [Unreleased]

## [5.0.0]

### Changed

- Completely rewritten in Python with a new interface; runs on Windows and Linux.
- New Windows 11 style design with light and dark theme, a navigation sidebar and a redesigned settings window.

### Added

- Linux builds (AppImage and tarball).
- Windows installer with per-user installation, no admin rights needed.
- Existing settings, profiles and categories are taken over from the previous version.

# Changelog

Newest first. Each release tag `vX.Y.Z` needs a matching `## [X.Y.Z]` section: the release
workflow publishes it as the GitHub release notes and as the changelog on both Nexus Mods pages,
and refuses to release without it.

Write one bullet per change. Nexus Mods receives one line per bullet, without the bullet,
headings, links or formatting, matching the existing changelog on the mod pages.

## [Unreleased]

## [5.2.0]

- New compact view: one slim line per mod with the category next to the version, switchable above the mod list or in the settings
- Dragging a mod to the top or bottom edge of the list scrolls again, faster the closer you get to the edge
- Update notifications now check the new release page, so new versions of the manager are announced again
- After regular use, the manager asks once whether you want to endorse it on Nexus Mods

## [5.1.0]

- Added Simplified Chinese localization
- On the first start the manager uses your system language if it is supported (English, German, French or Chinese)
- New app icon

## [5.0.0]

- Completely rewritten from scratch in Python with a new interface; runs on Windows and Linux
- New Windows 11 style design with light and dark theme, navigation sidebar and card-based mod list
- Redesigned settings window with pages for general, mods, conflicts, game, language and backups
- Linux builds (AppImage and tarball) are now available
- New Windows installer that installs per user without admin rights; if you used the old MSI installer, uninstall that version first
- Settings, profiles, categories, highlights and mod notes from version 4.x are taken over automatically

## [4.3]

- Conflict detector now supports “Only enabled mods” toggle for more accurate results
- Added ability to ignore conflicts for specific mods
- Added per-mod background highlight colors with full Dark/Light mode support
- Highlight colors are theme-aware and safely stored in user_mod_data.json
- Added “Move to top”, “Move to bottom”, and “Move to position” options in the three-dots menu
- Added drag-and-hold auto-scroll for easier long-distance mod reordering
- Improved conflict window refresh behavior after toggling ignore settings
- Fixed “Change mod name” incorrectly modifying modId
- Updated Select Game dialog to correctly request the game executable instead of the folder
- Improved validation for game executable selection
- Separator visibility improvements and UI refinements
- Various UI polish improvements
- Multiple bug fixes and stability improvements

## [4.2]

- Fixed an issue where Steam Workshop mods were not saved correctly in profiles.
- Workshop mods are now properly written to mod_order.txt, ensuring they stay activated after profile reloads.
- Automatically generates a stable mod ID for Workshop mods if none is present.
- Workshop mods no longer need to be moved into the main mods folder to work correctly.
- Improved reliability of profile save/load when Workshop mods are installed.

## [4.1]

- Fixed: game path selection not working
- Improved dialog ownership

## [4.0]

- Added a Conflict Detector — scans installed mods (.pak contents) and reports overlapping game files with a dedicated conflicts window and badge indicator.
- Added Categories & Separators — create, rename, delete, reorder categories and assign mods; sort/group by category and persist assignments.
- Added French localization (fr).
- Added separator/category UI (MO2-style) for grouping and organizing mods.
- Added Steam Workshop support — workshop mods are detected, visually marked, and treated specially (configurable).
- Workshop mods: certain actions are hidden by default (visit website, endorse, change mod number, toggle/check updates, override version) — setting to re-enable available (not recommended).
- Fixed rename logic so underscores (_) and hyphens (-) are preserved (no longer removed) to avoid breaking mods.
- Fixed “Change mod name” so custom names persist (saved to manifest/metadata and survive reloads/sorts).
- Improved “source file not found” handling — clearer error dialog with Locate / Skip / Retry and better logging.
- Fixed Game Selection dialog issues (GOG/Steam exe detection, setup loop and crash); removed stray German text in English UI.
- Improved Steam Workshop scanning and integration (workshop folder detection across Steam libraries).
- Various other bug fixes and stability improvements (metadata handling, backup reliability, UI polish).

## [3.0]

- Completely redesigned user interface for improved clarity and consistency (colors, buttons, layout, scrollbars).
- Added full profile management (create, load, save, delete, duplicate). Profiles store mod states, order and settings.
- Added support for Kingdom Come Deliverance 1 alongside KCD2.
- Added bulk toggle for mod activation: enable or disable all mods at once.
- Added option to start the game without any mods active.
- Localization system added; German translation included.
- Added feature to update supported game versions in manifests (single or bulk update).
- Mod metadata and notes handling improved and standardized.
- Converted application to standalone distribution for easier installation and portability.
- Improved game installation detection
- Added a button to manually check a mod for updates

## [2.2]

- Fixes an error where you couldn't change the game path

## [2.1]

- Added a new settings menu
- Dark mode is now fully compatible with all windows
- The manager now comes with an installer
- Windows Defender False Positive Fix (Work in Progress): Initial work has been done to reduce false positive detections by Windows Defender

## [2.0]

- Added Nexus Mods API support – Premium users can now update mods directly from the manager (Note: This is a Nexus Mods restriction, not mine)
- Mod endorsement – You can now endorse your favorite mods directly from the manager
- New login option – Sign in via the settings menu to enable API features.
- Added an option to disable update checks – Toggle this setting in the menu (three dots at the end of the mod entry)
- New setting to disable mod_order.txt creation – The mod order is still preserved, and switching the setting back restores the saved order.

## [1.10]

- Fixed an issue where underscores were being removed from mod IDs and folder names, causing some mods to break. This issue has now been resolved
- The mod manager now includes update detection. To enable it, refer to the article: "How to Enable Update Checks for Installed Mods"
- Settings have been divided into two categories: Regular Settings and Backup Settings for better organization
- The manager now creates multiple backups instead of overwriting the same folder. Each backup includes a date in its name
- A backup limit has been introduced, which can be adjusted in the new Backup Settings
- You can now rename mods directly from the context menu (three dots at the end of the mod entry)
- A new option allows you to add or modify notes for each mod
- If a mod has an associated Nexus Mods page number, you can open its webpage directly
- You can now manually change a mod’s number (see article for details)

## [1.9]

- Fixed an issue where mod notes wouldn't save properly
- Mod notes are now saved in a JSON file located in the "mods" folder

## [1.8]

- Update Notifications (This feature can be enabled or disabled in the settings - Default is enabled)
- Search Bar

## [1.7]

- Automatic Mods Folder Backup. The backup is saved in the game's root directory. Can be turned of in "Settings" (default is on)
- Fixed Critical Bug with Non-English Characters where the Mods folder could be accidentally deleted if the name tag contained special characters, non-English characters (e.g., Chinese, Japanese, Korean), or symbols.
- Smarter Naming for Mods Without Manifest

## [1.6]

- Fixed a bug that prevented some mods from loading with the new version.
- The status label has been moved to the bottom right corner for improved visibility.

## [1.5]

- Window Position & Size Saved (still some minor issues with this feature)
- Added an explore button that allows you to open the Mod folder directly from the KCD2 Mod Manager
- You can now install mods that do not have a mod.manifest file (folder/archive must contain .pak files with a folder structure with data or/and localisation)
- Minor fixes related to mod_order.txt

## [1.4]

- Fixed a bug where the mod order would ignore disabled mods on startup

## [1.3]

- DevMode Launch Option (available in the settings)

## [1.2]

- MOD Arrangement Color Interleaving
- Folder Selection Support (only works with file drop for now)
- Multiple Archive Selection (via "Add Mod" button)
- Sorting Options (name and load order)
- Dark Mode
- Removed the game path field from the window

## [1.1]

- Fixed a error with the mod order file

## [1.0]

- Initial release of KCD2 Mod Manager
- Features included: automatic mod detection, mod installation, mod enabling/disabling, and basic mod organization
- Supports mod formats: .zip, .rar, .7z

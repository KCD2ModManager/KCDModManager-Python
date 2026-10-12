# Migrating from the WPF KCD Mod Manager

The Python edition reads and writes the **same files** as the WPF manager. Nothing is moved,
renamed or deleted during migration, and the WPF installation can stay installed side by side.

> Do not run both managers at the same time: both write the same files.

## Where data lives

| Data | Location | Shared with WPF? |
| --- | --- | --- |
| Profiles | `<data>/profiles/<KCD1\|KCD2>/<name>/profile.json` + `mod_order.txt` | yes |
| Custom names/versions/notes, categories per mod, highlights | `<data>/user_mod_data.json` | yes |
| Categories | `<data>/categories.json` | yes |
| Load order | `<game>/Mods/mod_order.txt` (or `mod_order_backup.txt` when disabled) | yes |
| Nexus mod numbers, update-check flags | `<game>/Mods/mod_versions.json` | yes |
| Notes | `<game>/Mods/mod_notes.json` | yes |
| Per-mod category sidecar | `<mod folder>/mod.meta.json` | yes |
| App settings | `<data>/settings.json` | **no** (new) |
| Logs | `<data>/logs/kcd-mod-manager.log` (daily, 14 days kept) | no |
| Safety copies | `<data>/safety-backups/` | no |
| Mods backups | `<game>/Mods_Backup/Mods_Backup_<timestamp>/` | yes |

`<data>` is `%APPDATA%\KCDModManager` on Windows and `$XDG_CONFIG_HOME/KCDModManager`
(usually `~/.config/KCDModManager`) on Linux. It can be overridden with `KCDMM_DATA_DIR` or `--data-dir`.

JSON is written in the WPF format: PascalCase keys and .NET `"O"` timestamps. It is read
case-insensitively, and keys the Python edition does not know are written back unchanged.

## Migration steps

1. Close the WPF manager.
2. Optional but recommended: copy `%APPDATA%\KCDModManager` and your game's `Mods` folder somewhere safe.
3. Start the Python edition. On the first start it:
   - imports your settings **read-only** from the newest
     `%LOCALAPPDATA%\KCD2_mod_manager\<exe>_<hash>\<version>\user.config` (theme, language, game
     paths, backup and conflict options, Nexus account name, …) and saves them to `<data>/settings.json`;
   - moves the Nexus API token from that file into the OS keyring (Windows Credential Manager,
     Secret Service/KWallet on Linux). If no keyring is available it falls back to
     `<data>/nexus_api_key` with user-only permissions, and the app warns about this. The token is never written
     to `settings.json` or the logs. The WPF `user.config` itself is not modified.
4. Your profiles, categories, notes and load order appear unchanged.

The import runs once, on the first start without `settings.json`. To repeat it, delete `<data>/settings.json`.
On Linux there is no WPF configuration, so the app starts with defaults.

## Data safety rules

- Every write is atomic: a temp file, fsync, then rename.
- An unreadable JSON file is copied to `<file>.corrupt-<timestamp>` before anything replaces it.
  Defaults are never silently written over data that failed to parse.
- Mod installs and updates extract to a staging folder and swap folders. The previous copy is
  restored if anything fails.
- Before a stale `mod_order.txt` is removed, it is copied to `<data>/safety-backups/`.
- Steam Workshop folders are never written to.

## Deliberate behaviour changes (bug fixes)

| Area | WPF behaviour | Python edition |
| --- | --- | --- |
| Installing | Flattened nested folders in some archives | Preserves the archive's folder structure |
| Installing over an existing mod | Deleted the old folder, then copied | Stages, then swaps; the old copy survives failures |
| Rename collision on load | Could delete a folder | Never deletes; logs and keeps both |
| Workshop mods | Wrote `modid`/sidecar files into Workshop folders | Workshop folders are read-only; ids stay in memory, metadata goes to `user_mod_data.json` |
| Workshop mods in load order | Not part of `mod_order.txt` ordering | Ordered like other mods |
| Change mod number | Not always persisted | Saved to `mod_versions.json` |
| Clearing a custom version | Kept the old override | Reverts to the detected version |
| Duplicate profile | Could change the live load order | Copies files only |
| Renaming a mod id | Mod lost its position in other profiles | All profiles, notes and versions are updated |
| Last used profile | Not remembered per game | Remembered per game |
| Category change | Lost the sidecar's Workshop flag | Flag kept |
| Compatibility warning | Not derived from the manifest | Computed from `mod.manifest` `gameVersion` |
| Temporarily missing game folder (unplugged drive) | Saved path was cleared | Path kept; detection retried next start |
| Premium update | Could reset enabled state and mod number | Both kept |
| Delete/install while a profile is active | Saved only the game order file | Also saves the active profile |
| Newly installed mod | Position inconsistent | Appended at the end, disabled |
| Creating a profile with an existing name | Overwrote it | Rejected |
| Update check of all mods | Continued after HTTP 429 | Stops and reports the rate limit |

## Additions

- **Game launch arguments** can be edited in Settings. The WPF version had the setting but no UI for it.
- Install from a folder via its own button; drag & drop accepts archives and folders.
- Tools menu: open the Mods, data and log folders; check all mod updates on demand.
- Linux support (detection, Proton launch via Steam, desktop integration).

## Feature checklist

| Feature | Status | Verified by |
| --- | --- | --- |
| Game detection (Steam/GOG/standard paths/manual exe) | ported | `test_platform_and_detection.py`, `test_session.py::test_manual_install_selection` |
| Game selection dialog, switch game | ported | `test_main_window.py` (startup), manual smoke screenshot |
| Mod loading, manifest parsing/generation, `modid` handling, renaming setting | ported | `test_library.py`, `test_manifest.py` |
| Install archives (zip/7z/rar) and folders, invalid-manifest prompt | ported | `test_library.py`, `test_main_window.py::test_install_archive_and_delete` |
| Delete mod with confirmation / "don't ask again" | ported | `test_session.py::test_delete_mod`, UI test |
| Enable/disable, enable all/disable all | ported | `test_session.py`, UI tests |
| Load order: up/down, drag & drop, top/bottom/position, only in load-order sort | ported | `test_domain.py`, UI tests |
| `mod_order.txt` / backup-file switching and startup repair | ported | `test_persistence.py`, `test_migration.py` |
| Profiles: create/duplicate/delete/save/load, Default creation | ported | `test_session.py`, `test_migration.py`, UI test |
| Categories: manage, assign, set/clear, filter, sort, delete with reassignment | ported | `test_session.py::test_categories_assign_and_delete`, `test_persistence.py` |
| Search, sort modes | ported | `test_domain.py`, UI test |
| Notes, custom name, custom version, mod number, update-check toggle | ported | `test_session.py`, `test_migration.py`, UI test |
| Highlight colours, separators | ported | `test_session.py`, UI test |
| Conflict detector, ignore list, only-enabled option, cancel | ported | `test_session.py::test_conflict_scan`, UI startup test |
| Update manifest gameVersion (selected/all) | ported | `test_session.py::test_update_manifest_game_version` |
| Backups (startup/on demand, max count) | ported | `test_library.py::test_backup_and_prune`, `test_session.py::test_startup_backup` |
| Nexus SSO login/logout, premium badge | ported | `test_nexus.py` (HTTP mocked; SSO protocol not exercised against the live server) |
| Update checks (single/all), premium download+install, non-premium opens page | ported | `test_nexus.py`, `test_migration.py::test_update_install_keeps_enabled_state_and_mod_number` |
| Endorse, visit website | ported | `test_nexus.py::test_endorse_uses_post` |
| App update notification | ported | `test_nexus.py::test_app_update_check` |
| Start game (dev mode, launch args) | ported | `test_platform_and_detection.py::test_build_arguments` (no real launch in tests) |
| Settings window (all WPF toggles, language restart, ignored conflicts, backups) | ported | `test_main_window.py::test_settings_dialog_applies_changes` |
| Dark/light theme | ported | UI test + screenshots |
| English/German/French | ported | `test_i18n.py` |
| Window size/position persistence | ported (Qt geometry) | `test_main_window.py::test_geometry_is_saved_on_close` |

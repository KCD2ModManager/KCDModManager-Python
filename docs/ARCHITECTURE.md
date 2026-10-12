# Architecture

The design is MVVM-inspired with four layers. Dependencies only point downwards, and nothing
below `ui` imports Qt.

```
ui/              PySide6 widgets, item model + delegate, dialogs, theme, background tasks
application/     ManagerSession (all user operations), ModLibrary, NexusAccount, AppSettings
infrastructure/  files, JSON stores, archives, Steam/GOG detection, Nexus HTTP/SSO, OS actions
domain/          pure data + rules: models, load order, manifests, versions, categories, profiles
```

`bootstrap.py` is the composition root. It builds the object graph without Qt, so tests (and any
future CLI) can use the same wiring.

## Modules

| Module | Responsibility |
| --- | --- |
| `domain/models.py` | `Mod`, `ModProfile`, `ModCategory`, `UserModData`, `GameInstall`, `GameType` … |
| `domain/mod_order.py` | `mod_order.txt` parse/serialize, renumbering, scoped moves |
| `domain/manifest.py` | `mod.manifest` parse/generate/update (comments and BOM preserved) |
| `domain/versioning.py` | .NET `System.Version`-compatible comparison, game-version compatibility |
| `domain/library_view.py` | search, category filter, sort modes |
| `infrastructure/fs.py` | atomic writes, corrupt-file preservation, safe tree removal |
| `infrastructure/repositories.py` | `mod_versions.json`, `mod_notes.json`, `user_mod_data.json` |
| `infrastructure/profiles_store.py`, `categories_store.py`, `settings_store.py` | other persisted files |
| `infrastructure/order_files.py` | `mod_order.txt` / `mod_order_backup.txt` switching and repair |
| `infrastructure/archives.py` | zip (zip-slip safe), 7z (py7zr), rar (rarfile + external tool) |
| `infrastructure/steam.py`, `game_detection.py`, `pe_version.py` | finding games and their version |
| `infrastructure/conflict_scanner.py` | `.pak` listing cache and overlap detection |
| `infrastructure/nexus.py`, `nexus_sso.py`, `app_updates.py` | Nexus v1 API, SSO websocket, GitHub release check |
| `infrastructure/credentials.py` | keyring storage with a 0600 file fallback |
| `infrastructure/platform_actions.py` | open folders/URLs, launch the game (direct on Windows, Steam on Linux) |
| `infrastructure/legacy_import.py` | one-time, read-only import of the WPF `user.config` |
| `application/session.py` | the current game, mods, profiles, categories and every user operation |
| `application/library.py` | loading mods, installing/updating/deleting, backups |
| `ui/main_window.py` | main window (navigation sidebar, mods page, footer bar), row actions, startup flow |
| `ui/mod_list.py` | `ModListModel` (drag & drop) and the painted `ModDelegate` (one card per mod) |
| `ui/theme.py` | light/dark palettes (values from the WPF theme dictionaries) and the QSS |
| `ui/icons.py` | bundled Fluent UI System Icons (MIT, `resources/icons`) recoloured per theme |
| `ui/widgets.py` | WPF-style controls: toggle switch, icon buttons, pills, search box, rounded menus, footer bar |
| `ui/settings_dialog.py`, `ui/dialogs.py` | settings window (sidebar pages) and the other dialogs, all built as title + cards + footer bar |
| `ui/tasks.py` | `TaskRunner` (serial pool for mutations, parallel pool for network/scans), `GuiInvoker` |
| `i18n.py` | JSON translations converted from the original `.resx` files |

## Threading

Quick operations (toggle, move, metadata edits) run synchronously on the GUI thread. Slow ones
(loading, installing, updating, backups) run on the single-thread **serial** pool, and the UI is
disabled while they run, so the session is never mutated concurrently. Conflict scans and Nexus
requests use the parallel pool; they only read the mod list or set display flags. A worker that
needs user input (the "retry file move?" prompt) blocks on `GuiInvoker`.

## Platform notes

- Paths are handled with `pathlib`. Lookups of game files (`KingdomCome.exe`, `Mods`, `mod.manifest`,
  `steamapps`) are case-insensitive, so they work on case-sensitive Linux filesystems.
- No registry is required. On Windows it is only used as an optional hint for the Steam location.
- Linux launches the game through `steam -applaunch <appid>` because the game runs under Proton.

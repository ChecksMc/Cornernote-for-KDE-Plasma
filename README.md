# CornerNote

A slim GTK quick-note overlay for KDE Plasma on Wayland — peek, type, and save to your Obsidian vault without leaving your flow.

![version](https://img.shields.io/github/v/release/ChecksMc/Cornernote-for-KDE-Plasma)
![license](https://img.shields.io/github/license/ChecksMc/Cornernote-for-KDE-Plasma)
![platform](https://img.shields.io/badge/platform-KDE%20Plasma%20Wayland-blue)



## Features

- **Slide-in overlay**: hovers from any screen edge, collapses out of the way
- **Live theming**: follows your KDE/Plasma palette or Pywal colors automatically
- **History browser**: search and read the last 500 vault notes without leaving the overlay
- **Markdown preview**: renders bold, italic, lists, code, and more while you edit
- **Keyboard shortcuts**: full shortcut coverage, bindable KDE global shortcut (e.g. Meta+N)
- **Multi-monitor support**: pick your screen and position in settings

> **Platform:** KDE Plasma 5.x / 6.x, Wayland session with `wlr-layer-shell`.  
> Does not support GNOME, X11, or non-layer-shell compositors.


[![CornerNote demo](docs/showcase.gif)](docs/showcase.gif)

## Requirements

- KDE Plasma running a Wayland session with layer-shell support
- Python 3, PyGObject, GTK 3, Cairo, and gtk-layer-shell
- An Obsidian vault writable by your user

`install.sh` detects APT, DNF, Pacman, or Zypper and installs missing system
dependencies with that package manager (using `sudo` when needed). On systems
with other package managers, install the equivalent packages manually first.
To install them manually on Fedora:

```sh
sudo dnf install python3 python3-gobject python3-cairo gtk-layer-shell
```

The overlay cannot run as a layer-shell surface on X11. Check with
`printf '%s\n' "$XDG_SESSION_TYPE"` and use a Wayland Plasma session.

CornerNote uses the layer-shell **top** layer so it stays above normal windows
while panels can appear in front of it. KWin's `wlr-layer-shell` implementation
has known quirks around fullscreen windows, and behavior may differ between
Plasma 5.x and 6.x. Check the [KDE bug tracker query for
`wlr-layer-shell`](https://bugs.kde.org/buglist.cgi?quicksearch=wlr-layer-shell)
for the current status.

## Install

```sh
./install.sh
```

The installer installs missing dependencies when it recognizes your package
manager, then installs a user-level launcher and starts CornerNote through a
systemd user service when available, or KDE's login autostart otherwise. It
copies `config.example.json` to
`~/.config/cornernote/config.json` if no config exists, and enables the service
for the graphical session when systemd is available. Start the service with
`systemctl --user start cornernote` or run `~/.local/bin/cornernote-daemon` when
using login autostart. The daemon uses the current checkout, so keep this
repository in place after installing.

Remove the service and launchers with `./uninstall.sh`. This preserves your
settings by default; use `./uninstall.sh --purge-config` to delete them too.

Use `corner-note toggle` to open or close CornerNote. To bind a KDE global
shortcut, open **System Settings → Shortcuts → Add New → Command or URL** and
set the command to `corner-note toggle` with a shortcut such as Meta+N or F12.
This manual route works across Plasma versions.

## Updates

Open settings and expand **Updates**. Choose **Check for updates**, then
**Install update** when a newer revision is available. Checks and installation
run in the background so the editor stays responsive.

To enable automatic installation, select **Install updates automatically** and
click **Save settings**. This saves `"auto_update": true` in the config and
checks immediately, on subsequent daemon starts, and every six hours while
the daemon runs. Available updates are installed automatically. The setting is
off by default; no background network checks run while it is disabled. Manual
checks remain available.

The command-line client can also check and install updates while the daemon
is stopped:

```sh
corner-note check-update
corner-note update
```

Updates require Git and a CornerNote Git checkout on a branch with a configured
upstream. The updater fetches that branch's upstream and installs only a
fast-forward update. Installation refuses local changes, untracked files,
local commits ahead of upstream, divergent history, or an unfinished Git
operation. It never forces a reset and does not edit settings or vault files
outside the checkout. ZIP installations cannot use the built-in updater;
download the latest source and rerun `install.sh`, or switch to a Git clone.

After installation, CornerNote keeps running with your current draft. To use
the new version, save your note, then restart the daemon:

```sh
systemctl --user restart cornernote
```

For KDE login autostart installations, save your note, then log out and back
in. Updates never restart the daemon automatically; restarting clears any
unsaved in-memory draft.

## Use

- Hover the exposed paper tab to open it. Moving the pointer away collapses it.
- Press Meta+N (or your configured shortcut) to open and focus the note. The
  shortcut toggles the forced-open state.
- Enter in the title field moves focus to the note body.
- Submit normally to append a dated heading and draft to the configured
  quick-notes file. To append to another Markdown file, enter its path as the
  title or enable **Append mode**. A title ending in `.md` automatically
  selects append mode. Relative append paths resolve inside the configured
  vault; absolute `.md` paths are also accepted.
- Choose **No date** to omit the date from the saved heading. Typing `none` in
  the date field does the same. Custom dates such as `tomorrow` or `14.10` are
  still supported.
- Ctrl+Enter submits using the active mode.
- Ctrl+D toggles between a date and no date. Ctrl+Shift+D opens the date menu.
- Ctrl+Shift+A toggles append mode. Ctrl+Shift+F opens a Markdown-only picker
  to search for and append to an existing note in the vault.
- Ctrl+S toggles settings. The gear button also closes settings and returns to
  the editor. Settings collapse when the pointer leaves the overlay.
- **History** (Ctrl+H) browses the vault's latest 500 Markdown files, newest
  first. Search by filename or relative path, then select a file to read its
  formatted contents, including all appended entries. **Refresh** rescans the
  vault. Escape returns from a file to the list, then to your draft; the
  **Draft** button or Ctrl+H also returns to the editor. Browsing preserves
  unfinished text and submission options, and works across restarts.
- In the note body, Ctrl+1 inserts a level-one heading, Ctrl+B wraps text in
  bold markers, Ctrl+I wraps text in italic markers, and Ctrl+U wraps text in
  an HTML underline tag. The H1/B/I/U toolbar applies the same formatting.
  Headings, bold, italic, and underline appear styled while editing. Choose
  **Preview** (Ctrl+P) for a rendered view with the Markdown markers hidden;
  toggle it again to keep editing. Saving always preserves the Markdown.
  Preview also renders lists, quotes, links, strikethrough, and fenced/inline
  code. Other HTML and unsupported Markdown stay as text.
- Escape opens an inline discard confirmation. Confirm with Y/Yes or cancel
  with N/No/Escape.
- The gear button toggles between the editor and settings for the vault,
  filename/date format, timing, tab peek, appearance, and updates. Appearance
  changes are saved with **Apply style**; **Save settings** saves the other
  settings and returns to the editor.

Collapsing the overlay never clears a draft. A draft is cleared only after a
successful write or a confirmed discard. Write failures remain visible in the
overlay and preserve the text for retry.

## Configuration

Open the overlay and press the gear button for the in-app settings page, or
edit `${XDG_CONFIG_HOME:-~/.config}/cornernote/config.json` (normally
`~/.config/cornernote/config.json`). If `CORNERNOTE_CONFIG` is set, that file
is used instead. Settings are written atomically. The full template and
defaults are in [`config.example.json`](config.example.json). `note_filename` supports
`{date}` and `{title}` substitutions, for example `QuickNotes.md` or
`{date}.md`. Date tags accept `today`, `tomorrow`, weekday names, `in N days`,
and common numeric date forms. Position uses `position_horizontal` and
`position_vertical` (`left`/`center`/`right` and `top`/`center`/`bottom`);
`offset_x` and `offset_y` tune that reference point in pixels. Positive X
moves right and positive Y moves down. For top and bottom positions, the
outward Y offset is limited by the idle tab size so at least one pixel remains
visible when the note is collapsed. `monitor` selects `primary` or a
connected screen by its zero-based GDK display index; the settings page labels
each screen with its manufacturer, model, resolution, and desktop position,
truncating long labels with an ellipsis to keep the overlay width fixed.
The settings page also includes a folder chooser; under Plasma, GTK uses the
available KDE file chooser portal.

The default vault path is `~/Documents`. Change it in settings to the root of
your own Obsidian vault before saving notes.

Settings are grouped into display and position, vault and files, animation,
appearance, and updates sections. Expand **Appearance and style** to open the
embedded editor. It previews the style and offers Plasma colors, Pywal colors, ten
built-in palettes, editable custom colors, installed font families and font
size, a local image backdrop, and rounded paper corners. The selected style is
saved to `config.json` and applied to the overlay. By default, colors follow
Plasma's `kdeglobals` palette, which CornerNote watches for changes. Text
contrast is corrected when a selected palette would make note text hard to
read. Settings also include independent note width and height controls. The
configured dimensions stay fixed when fonts change; smaller notes scroll to
keep oversized controls accessible. Applying a style or saving dimensions
resizes the current overlay immediately, without restarting the daemon.
The hide delay and slide duration are adjustable; defaults are 700 ms and 320 ms.

## Files

- `src/main.py` — GTK layer-shell overlay and daemon entry point
- `src/state.py` — draft buffer and note interaction state machine
- `src/style.py` — config, Pywal/KDE palette loading, and GTK CSS
- `src/style_editor.py` — standalone appearance editor and live preview
- `src/ipc.py` — GLib-integrated Unix socket server and CLI client
- `src/obsidian.py` — safe Markdown path selection and append writer
- `src/markdown_render.py` — Markdown text and formatting ranges
- `src/markdown_view.py` — GTK formatting for the editor and rendered views
- `src/history.py` — saved vault note discovery and bounded read-only loading
- `src/history_view.py` — searchable saved-note browser and formatted viewer
- `src/updater.py` — Git upstream checks and fast-forward-only source updates
- `src/update_view.py` — manual update controls and opt-in automatic installation
- `corner-note` — IPC command-line client and standalone update commands
- `install.sh` — multi-distro dependency and user installation
- `uninstall.sh` — removes startup entries and launchers, optionally config
- `packaging/bundle.py` — builds a distributable `CornerNote.zip`

## Development and troubleshooting

Run `python3 src/main.py` from the checkout to see errors in a terminal. In a
second terminal use `./corner-note toggle`. Inspect service logs with
`journalctl --user -u cornernote -f`. The socket defaults to
`$XDG_RUNTIME_DIR/cornernote.sock`, which is private to the login session.

CornerNote does not use the higher overlay layer, allowing panels above it to
cover the note while it slides. Fullscreen handling still depends on KWin's
layer-shell policy; the app does not poll KWin state or promise fullscreen
suppression.

CornerNote listens for systemd-logind sleep and wake notifications. On resume it
recreates the Wayland layer surface and reapplies the selected screen and
position, keeping the in-memory draft intact. If the system bus is unavailable,
the overlay continues to run normally but cannot perform this resume recovery.

## Roadmap / Known Limitations

GTK 3 is in maintenance mode. A port to GTK 4 or Qt is a long-term consideration.

## Known Issues

**Overlay disappears after suspend/resume**
On some systems the layer-shell surface is not automatically recreated after
waking from suspend. The service continues running normally but the overlay
is no longer visible. Workaround until this is resolved:

```bash
    systemctl --user restart cornernote
```

This is a Wayland compositor surface lifecycle issue and may affect other
layer-shell applications on the same setup. Multi-monitor and hybrid GPU
configurations appear more likely to trigger it.


#!/usr/bin/env python3
"""CornerNote GTK 3 / gtk-layer-shell daemon for KDE Plasma on Wayland."""

from __future__ import annotations

import datetime as dt
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell as LayerShell, Pango
except (ImportError, ValueError) as exc:
    print("CornerNote requires PyGObject GTK 3 and gtk-layer-shell. "
          "On Fedora install python3-gobject python3-cairo gtk-layer-shell.",
          file=sys.stderr)
    raise SystemExit(1) from exc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ipc import start_server
from obsidian import append_to_file, write_note
from state import Mode, NoteState
from style import CONFIG_PATH, build_css, load_config, save_config
from style_editor import StyleEditor
from update_view import UpdatePanel

Config = dict[str, Any]


class CornerNote(Gtk.Window):
    """Single overlay window; GTK owns all event and animation scheduling."""

    def __init__(self, config: Config) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config = config
        self.config_path = Path(os.environ.get("CORNERNOTE_CONFIG", CONFIG_PATH))
        self.state = NoteState()
        self.pointer_inside = False
        self.dropdown_open = False
        self.file_chooser_open = False
        self.expanded = False
        self.animation_source: int | None = None
        self.collapse_source: int | None = None
        self.theme_refresh_source: int | None = None
        self.resume_source: int | None = None
        self.sleep_subscription: int | None = None
        self.system_bus: Gio.DBusConnection | None = None
        self.animation_start = 0.0
        self.animation_from = 0
        self.animation_to = 0
        self.position_vertical_edge = LayerShell.Edge.TOP
        self.position_vertical_base = 0
        self.active_monitor: Any | None = None
        self._updating_append_controls = False
        self._title_was_filepath = False

        self.set_title("CornerNote")
        self.set_name("cornernote")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(config["width"], config["height"])
        self.set_size_request(config["width"], config["height"])
        self.set_app_paintable(True)

        LayerShell.init_for_window(self)
        LayerShell.set_namespace(self, "cornernote")
        LayerShell.set_layer(self, LayerShell.Layer.TOP)
        self._apply_position(initial=True)
        LayerShell.set_keyboard_interactivity(self, False)

        self._build_ui()
        self._install_accelerators()
        self._install_css()
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("key-press-event", self._on_key)
        self.connect("delete-event", self._on_delete)
        self.connect("realize", lambda *_: self._refresh_clock())
        display = Gdk.Display.get_default()
        if display is not None:
            display.connect("monitor-added", self._on_monitors_changed)
            display.connect("monitor-removed", self._on_monitors_changed)
        self.show_all()
        self.dialog_box.hide()
        self.status_label.hide()
        self._watch_theme_files()
        self._clock_source = GLib.timeout_add_seconds(30, self._refresh_clock)
        self.update_panel.configure(self.config.get("auto_update", False))

    def watch_suspend_resume(self) -> None:
        """Subscribe to logind sleep notifications and restore the layer surface."""
        try:
            self.system_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self.sleep_subscription = self.system_bus.signal_subscribe(
                "org.freedesktop.login1",
                "org.freedesktop.login1.Manager",
                "PrepareForSleep",
                "/org/freedesktop/login1",
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_prepare_for_sleep,
            )
        except (GLib.Error, OSError) as exc:
            print(f"[cornernote] suspend notifications unavailable: {exc}", file=sys.stderr)

    def _on_prepare_for_sleep(self, _connection: Gio.DBusConnection,
                              _sender: str, _path: str, _interface: str,
                              _signal: str, parameters: GLib.Variant,
                              _user_data: Any = None) -> None:
        """Prepare the overlay before sleep and schedule restoration after wake."""
        sleeping = bool(parameters.unpack()[0])
        print(f"[cornernote] sleep notification: {'suspending' if sleeping else 'resuming'}", file=sys.stderr, flush=True)
        if sleeping:
            self._cancel_collapse()
            self._stop_animation()
            self.pointer_inside = False
            self.expanded = self.state.forced_open
            LayerShell.set_keyboard_interactivity(self, self.expanded)
            return
        if self.resume_source is not None:
            GLib.source_remove(self.resume_source)
        self.resume_source = GLib.timeout_add(800, self._restore_after_resume)

    def _restore_after_resume(self) -> bool:
        """Recreate the layer-shell surface after the compositor resumes."""
        print("[cornernote] restoring overlay after resume", file=sys.stderr, flush=True)
        self.resume_source = None
        self._cancel_collapse()
        self._stop_animation()
        self.pointer_inside = False
        self.expanded = self.state.forced_open
        self.dropdown_open = False
        self.file_chooser_open = False
        self.hide()
        LayerShell.set_namespace(self, "cornernote")
        LayerShell.set_layer(self, LayerShell.Layer.TOP)
        LayerShell.set_keyboard_interactivity(self, self.expanded)
        self.active_monitor = None
        self._apply_position(initial=True)
        self.show()
        if self.state.forced_open:
            self.present()
            self._animate_to(self.position_vertical_base)
        self._refresh_clock()
        return GLib.SOURCE_REMOVE

    def _on_monitors_changed(self, _display: Gdk.Display, _monitor: Gdk.Monitor) -> None:
        """Re-evaluate the configured screen once GDK updates its monitor list."""
        GLib.idle_add(self._refresh_monitor)

    def _refresh_monitor(self) -> bool:
        _display, monitor, _index = self._monitor_selection()
        if monitor is not None and monitor != self.active_monitor:
            self._apply_position()
        return GLib.SOURCE_REMOVE

    def idle_margin(self) -> int:
        """Return the layer-shell margin that leaves the configured tab visible."""
        peek = round(self.config["height"] * self.config["idle_fraction"])
        return self.position_vertical_base - (self.config["height"] - peek)

    def _monitor_selection(self) -> tuple[Any | None, Any | None, int]:
        """Resolve the configured display and return its GDK index."""
        display = Gdk.Display.get_default()
        if display is None:
            return None, None, -1
        count = display.get_n_monitors()
        primary = display.get_primary_monitor()
        selected = self.config.get("monitor", "primary")
        if selected == "primary":
            monitor = primary or (display.get_monitor(0) if count else None)
        else:
            try:
                monitor = display.get_monitor(int(selected))
            except (TypeError, ValueError):
                monitor = None
            if monitor is None:
                monitor = primary or (display.get_monitor(0) if count else None)
        index = next((i for i in range(count) if display.get_monitor(i) == monitor), -1)
        return display, monitor, index

    def _populate_monitor_choices(self) -> None:
        """Refresh the settings list with currently connected displays."""
        combo = self.setting_widgets.get("monitor")
        if combo is None:
            return
        combo.remove_all()
        for renderer in combo.get_cells():
            if isinstance(renderer, Gtk.CellRendererText):
                renderer.set_property("max-width-chars", 28)
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
        display = Gdk.Display.get_default()
        if display is None:
            combo.append("primary", "Primary display")
            return
        count = display.get_n_monitors()
        for index in range(count):
            monitor = display.get_monitor(index)
            if monitor is None:
                continue
            manufacturer = monitor.get_manufacturer() or ""
            model = monitor.get_model() or ""
            monitor_name = " ".join(part.strip() for part in (manufacturer, model)
                                    if part.strip()) or "Display"
            geometry = monitor.get_geometry()
            primary = monitor.is_primary()
            label = (f"Screen {index + 1}: {monitor_name} — "
                     f"{geometry.width}×{geometry.height} at "
                     f"{geometry.x},{geometry.y}")
            if primary:
                label += " (primary)"
            combo.append(str(index), label)
        if count == 0:
            combo.append("primary", "Primary display")

    def _apply_position(self, initial: bool = False) -> None:
        """Anchor to a 3x3 screen reference, then apply signed pixel offsets."""
        if hasattr(self, "animation_source"):
            self._stop_animation()
        display, monitor, _monitor_index = self._monitor_selection()
        if monitor is not None:
            if initial or monitor != self.active_monitor:
                LayerShell.set_monitor(self, monitor)
                self.active_monitor = monitor
            geometry = monitor.get_geometry()
            screen_width, screen_height = geometry.width, geometry.height
        else:
            screen = Gdk.Screen.get_default()
            screen_width = screen.get_width() if screen else self.config["width"]
            screen_height = screen.get_height() if screen else self.config["height"]

        edges = (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                 LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT)
        for edge in edges:
            LayerShell.set_anchor(self, edge, False)
            LayerShell.set_margin(self, edge, 0)

        horizontal = self.config.get("position_horizontal", "right")
        if horizontal == "left":
            x_edge = LayerShell.Edge.LEFT
            x_margin = self.config.get("offset_x", 0)
        elif horizontal == "center":
            x_edge = LayerShell.Edge.LEFT
            x_margin = round((screen_width - self.config["width"]) / 2) + self.config.get("offset_x", 0)
        else:
            x_edge = LayerShell.Edge.RIGHT
            x_margin = self.config.get("margin_right", 20) - self.config.get("offset_x", 0)
        LayerShell.set_anchor(self, x_edge, True)
        LayerShell.set_margin(self, x_edge, int(x_margin))

        vertical = self.config.get("position_vertical", "top")
        offset_y = self.config.get("offset_y", 0)
        visible_tab = max(1, round(self.config["height"] * self.config["idle_fraction"]))
        if vertical == "top":
            y_edge = LayerShell.Edge.TOP
            y_margin = max(offset_y, 1 - visible_tab)
        elif vertical == "center":
            y_edge = LayerShell.Edge.TOP
            y_margin = round((screen_height - self.config["height"]) / 2) + offset_y
        else:
            y_edge = LayerShell.Edge.BOTTOM
            y_margin = -min(offset_y, visible_tab - 1)
        LayerShell.set_anchor(self, y_edge, True)
        self.position_vertical_edge = y_edge
        self.position_vertical_base = int(y_margin)
        LayerShell.set_margin(self, y_edge,
                              self.idle_margin() if initial or not self.expanded
                              else self.position_vertical_base)

    def _build_ui(self) -> None:
        """Construct the note editor, status area, and root layout."""
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        root.get_style_context().add_class("corner-note-root")

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.get_style_context().add_class("cn-header")
        self.day_label = Gtk.Label(xalign=0)
        self.day_label.get_style_context().add_class("cn-day")
        header.pack_start(self.day_label, False, False, 2)
        header.pack_start(Gtk.Box(), True, True, 0)
        date_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.date_label = Gtk.Label(xalign=1)
        self.time_label = Gtk.Label(xalign=1)
        self.date_label.get_style_context().add_class("cn-date")
        self.time_label.get_style_context().add_class("cn-time")
        date_box.pack_start(self.date_label, False, False, 0)
        date_box.pack_start(self.time_label, False, False, 0)
        header.pack_end(date_box, False, False, 2)
        self.settings_button = Gtk.Button(label="[ ⚙ ]")
        self.settings_button.set_tooltip_text("CornerNote settings")
        self.settings_button.connect("clicked", lambda *_: self._toggle_settings())
        header.pack_end(self.settings_button, False, False, 4)
        root.pack_start(header, False, False, 0)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.get_style_context().add_class("cn-separator")
        root.pack_start(separator, False, False, 0)

        self.page_stack = Gtk.Stack()
        self.page_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        root.pack_start(self.page_stack, True, True, 0)
        note_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self.title_entry = Gtk.Entry()
        self.title_entry.set_placeholder_text("Title…  (Enter for body)")
        self.title_entry.get_style_context().add_class("cn-title")
        self.title_entry.connect("activate", self._on_title_enter)
        self.title_entry.connect("changed", self._on_title_changed)
        note_page.pack_start(self.title_entry, False, False, 3)

        self.content_buffer = Gtk.TextBuffer()
        self.content_view = Gtk.TextView(buffer=self.content_buffer)
        self.content_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.content_view.set_left_margin(5)
        self.content_view.set_right_margin(5)
        self.content_view.get_style_context().add_class("cn-content")
        self.content_buffer.connect("changed", self._sync_draft)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.content_view)
        note_page.pack_start(scroller, True, True, 2)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.date_mode_combo = Gtk.ComboBoxText()
        self.date_mode_combo.append("date", "Date")
        self.date_mode_combo.append("none", "No date")
        self.date_mode_combo.set_active_id("date")
        self.date_mode_combo.connect("changed", self._on_date_mode_changed)
        self.date_mode_combo.connect("notify::popup-shown", self._on_folder_popup)
        controls.pack_start(self.date_mode_combo, False, False, 0)
        self.date_entry = Gtk.Entry()
        self.date_entry.set_placeholder_text("today / tomorrow / 14.10 / none")
        self.date_entry.get_style_context().add_class("cn-date-entry")
        self.date_entry.connect("changed", self._on_date_entry_changed)
        controls.pack_start(self.date_entry, True, True, 0)
        self.folder_combo = Gtk.ComboBoxText()
        self.folder_combo.get_style_context().add_class("cn-folder")
        self.folder_combo.append_text("(root)")
        vault = Path(self.config["default_vault_path"])
        folders = set(self.config.get("folders", []))
        try:
            folders.update(child.name for child in vault.iterdir() if child.is_dir())
        except OSError:
            pass
        self.available_folders = sorted(
            f for f in folders if Path(f).name == f and f not in (".", ".."))
        for folder in self.available_folders:
            self.folder_combo.append_text(folder)
        self.folder_combo.set_active(0)
        self.folder_combo.connect("changed", self._sync_draft)
        self.folder_combo.connect("notify::popup-shown", self._on_folder_popup)
        controls.pack_start(self.folder_combo, False, False, 0)
        note_page.pack_start(controls, False, False, 1)

        append_options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.append_mode_check = Gtk.CheckButton(label="Append mode")
        self.append_mode_check.set_tooltip_text(
            "Treat the title as a Markdown filepath inside your vault")
        self.append_mode_check.connect("toggled", self._on_append_checkbox_toggled)
        append_options.pack_start(self.append_mode_check, False, False, 0)
        note_page.pack_start(append_options, False, False, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.get_style_context().add_class("cn-status")
        footer.pack_start(self.status_label, True, True, 0)
        self.save_button = Gtk.Button(label="[ Submit · Ctrl+Enter ]")
        self.save_button.get_style_context().add_class("cn-save")
        self.save_button.connect("clicked", lambda *_: self.commit_note())
        footer.pack_end(self.save_button, False, False, 0)
        note_page.pack_start(footer, False, False, 0)

        self.dialog_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dialog_box.get_style_context().add_class("cn-dialog")
        self.dialog_box.pack_start(Gtk.Label(label="Discard draft?"), True, True, 2)
        self.discard_yes = Gtk.Button(label="[ Yes ]")
        no = Gtk.Button(label="[ No ]")
        self.discard_yes.connect("clicked", lambda *_: self._resolve_discard(True))
        no.connect("clicked", lambda *_: self._resolve_discard(False))
        self.dialog_box.pack_end(no, False, False, 0)
        self.dialog_box.pack_end(self.discard_yes, False, False, 0)
        note_page.pack_start(self.dialog_box, False, False, 0)
        self.page_stack.add_named(note_page, "note")
        self._build_settings_page()
        self.add(root)

    def _build_settings_page(self) -> None:
        """Construct the configuration editor page."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        page.get_style_context().add_class("cn-settings")
        heading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading = Gtk.Label(label="CornerNote Settings", xalign=0)
        heading.get_style_context().add_class("cn-day")
        heading_row.pack_start(heading, True, True, 2)
        page.pack_start(heading_row, False, False, 2)
        settings_scroll = Gtk.ScrolledWindow()
        settings_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        settings_scroll.set_propagate_natural_width(False)
        settings_scroll.set_min_content_width(0)
        settings_scroll.set_max_content_width(max(240, int(self.config["width"]) - 16))
        self.settings_scroll = settings_scroll
        self.settings_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.settings_content.set_size_request(max(240, int(self.config["width"]) - 32), -1)
        self.settings_content.set_hexpand(True)
        settings_scroll.add(self.settings_content)
        page.pack_start(settings_scroll, True, True, 0)
        self.setting_widgets: dict[str, Any] = {}

        def make_group(label: str, expanded: bool = False) -> Gtk.Grid:
            """Create an expandable settings group and return its grid."""
            expander = Gtk.Expander(label=label)
            expander.set_expanded(expanded)
            group_grid = Gtk.Grid(column_spacing=8, row_spacing=6)
            expander.add(group_grid)
            self.settings_content.pack_start(expander, False, False, 0)
            return group_grid

        def add_row(group_grid: Gtk.Grid, row: int, label: str,
                    key: str, widget: Any) -> None:
            """Place a setting label above a full-width input control."""
            text = Gtk.Label(label=label, xalign=0)
            text.set_halign(Gtk.Align.START)
            widget.set_hexpand(True)
            widget.set_halign(Gtk.Align.FILL)
            group_grid.attach(text, 0, row * 2, 2, 1)
            group_grid.attach(widget, 0, row * 2 + 1, 2, 1)
            self.setting_widgets[key] = widget

        display_grid = make_group("Display and position", True)
        monitor_choice = Gtk.ComboBoxText()
        monitor_choice.get_style_context().add_class("cn-folder")
        monitor_choice.connect("notify::popup-shown", self._on_folder_popup)
        add_row(display_grid, 0, "Screen", "monitor", monitor_choice)
        horizontal = Gtk.ComboBoxText()
        horizontal.get_style_context().add_class("cn-folder")
        horizontal.connect("notify::popup-shown", self._on_folder_popup)
        for value, label in (("left", "Left"), ("center", "Center"), ("right", "Right")):
            horizontal.append(value, label)
        add_row(display_grid, 1, "Horizontal", "position_horizontal", horizontal)
        vertical = Gtk.ComboBoxText()
        vertical.get_style_context().add_class("cn-folder")
        vertical.connect("notify::popup-shown", self._on_folder_popup)
        for value, label in (("top", "Top"), ("center", "Center"), ("bottom", "Bottom")):
            vertical.append(value, label)
        add_row(display_grid, 2, "Vertical", "position_vertical", vertical)
        offset_x = Gtk.SpinButton.new_with_range(-5000, 5000, 10)
        offset_x.set_numeric(True)
        add_row(display_grid, 3, "X offset (px)", "offset_x", offset_x)
        offset_y = Gtk.SpinButton.new_with_range(-5000, 5000, 10)
        offset_y.set_numeric(True)
        offset_y.set_tooltip_text(
            "The offset is limited near the top or bottom edge so the idle tab stays visible.")
        add_row(display_grid, 4, "Y offset (px)", "offset_y", offset_y)
        width = Gtk.SpinButton.new_with_range(240, 1600, 20)
        width.set_numeric(True)
        add_row(display_grid, 5, "Width (px)", "width", width)
        height = Gtk.SpinButton.new_with_range(180, 1200, 20)
        height.set_numeric(True)
        add_row(display_grid, 6, "Height (px)", "height", height)
        peek = Gtk.SpinButton.new_with_range(1, 50, 1)
        peek.set_numeric(True)
        add_row(display_grid, 7, "Idle tab (%)", "idle_percent", peek)
        vertical.connect("changed", lambda *_: self._update_y_offset_limits())
        height.connect("value-changed", lambda *_: self._update_y_offset_limits())
        peek.connect("value-changed", lambda *_: self._update_y_offset_limits())

        vault_grid = make_group("Vault and files")
        vault_entry = Gtk.Entry()
        vault_entry.set_placeholder_text("Path to your Obsidian vault")
        add_row(vault_grid, 0, "Obsidian vault", "default_vault_path", vault_entry)
        filename_entry = Gtk.Entry()
        add_row(vault_grid, 1, "Markdown filename", "note_filename", filename_entry)
        date_entry = Gtk.Entry()
        add_row(vault_grid, 2, "Date format", "date_format", date_entry)

        behavior_grid = make_group("Animation")
        animation = Gtk.SpinButton.new_with_range(100, 1200, 50)
        animation.set_numeric(True)
        add_row(behavior_grid, 0, "Slide speed (ms)", "anim_ms", animation)
        delay = Gtk.SpinButton.new_with_range(0, 3000, 100)
        delay.set_numeric(True)
        add_row(behavior_grid, 1, "Hide delay (ms)", "collapse_delay_ms", delay)

        self.appearance_expander = Gtk.Expander(label="Appearance and style")
        self.style_editor = StyleEditor(self.config, self._apply_style_config,
                                        self._on_folder_popup,
                                        self._on_style_chooser_changed)
        self.appearance_expander.add(self.style_editor)
        self.settings_content.pack_start(self.appearance_expander, False, False, 0)

        updates = Gtk.Expander(label="Updates")
        self.update_panel = UpdatePanel(self._show_status)
        updates.add(self.update_panel)
        self.settings_content.pack_start(updates, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.settings_status = Gtk.Label(xalign=0)
        self.settings_status.get_style_context().add_class("cn-status")
        actions.pack_start(self.settings_status, True, True, 0)
        cancel = Gtk.Button(label="[ Cancel ]")
        cancel.connect("clicked", lambda *_: self._show_note_page())
        save = Gtk.Button(label="[ Save settings ]")
        save.get_style_context().add_class("cn-save")
        save.connect("clicked", lambda *_: self._save_settings())
        actions.pack_end(cancel, False, False, 0)
        actions.pack_end(save, False, False, 0)
        self.select_vault_button = Gtk.Button(label="[ Select vault folder… ]")
        self.select_vault_button.connect("clicked", lambda *_: self._choose_vault_folder())
        page.pack_end(self.select_vault_button, False, False, 0)
        page.pack_end(actions, False, False, 0)
        self.page_stack.add_named(page, "settings")

    def _show_settings(self) -> None:
        """Populate setting controls from the active configuration."""
        self.style_editor.set_config(self.config)
        fields = self.setting_widgets
        self._populate_monitor_choices()
        _display, _monitor, monitor_index = self._monitor_selection()
        fields["monitor"].set_active_id(str(monitor_index) if monitor_index >= 0 else "primary")
        fields["default_vault_path"].set_text(self.config["default_vault_path"])
        fields["note_filename"].set_text(self.config["note_filename"])
        fields["date_format"].set_text(self.config["date_format"])
        fields["anim_ms"].set_value(self.config["anim_ms"])
        fields["collapse_delay_ms"].set_value(self.config["collapse_delay_ms"])
        fields["idle_percent"].set_value(round(self.config["idle_fraction"] * 100))
        fields["position_horizontal"].set_active_id(
            self.config.get("position_horizontal", "right"))
        fields["position_vertical"].set_active_id(
            self.config.get("position_vertical", "top"))
        fields["offset_x"].set_value(self.config.get("offset_x", 0))
        fields["offset_y"].set_value(self.config.get("offset_y", 0))
        fields["width"].set_value(self.config["width"])
        fields["height"].set_value(self.config["height"])
        self.update_panel.auto_install.set_active(self.config.get("auto_update", False))
        self._update_y_offset_limits()
        self.settings_status.set_text("")
        self.page_stack.set_visible_child_name("settings")
        fields["default_vault_path"].grab_focus()

    def _toggle_settings(self) -> None:
        """Switch between settings and the note editor from the header button."""
        if self.page_stack.get_visible_child_name() == "settings":
            self._show_note_page()
        else:
            self._show_settings()

    def _update_y_offset_limits(self) -> None:
        """Limit outward vertical adjustment so an idle tab remains visible."""
        fields = getattr(self, "setting_widgets", {})
        offset = fields.get("offset_y")
        height = fields.get("height")
        peek_percent = fields.get("idle_percent")
        vertical = fields.get("position_vertical")
        if any(widget is None for widget in (offset, height, peek_percent, vertical)):
            return
        visible_tab = max(1, round(height.get_value_as_int()
                                   * peek_percent.get_value_as_int() / 100))
        position = vertical.get_active_id()
        if position == "top":
            offset.set_range(1 - visible_tab, 5000)
        elif position == "bottom":
            offset.set_range(-5000, visible_tab - 1)
        else:
            offset.set_range(-5000, 5000)

    def _show_note_page(self) -> None:
        """Return to the note editor and restore the active editing focus."""
        self.page_stack.set_visible_child_name("note")
        (self.content_view if self.state.mode == Mode.CONTENT else self.title_entry).grab_focus()

    def _save_settings(self) -> bool:
        """Validate, persist, and close settings after a successful save."""
        fields = self.setting_widgets
        new_config = dict(self.config)
        new_config["default_vault_path"] = os.path.expanduser(
            fields["default_vault_path"].get_text().strip())
        new_config["note_filename"] = fields["note_filename"].get_text().strip()
        new_config["date_format"] = fields["date_format"].get_text().strip()
        new_config["anim_ms"] = fields["anim_ms"].get_value_as_int()
        new_config["collapse_delay_ms"] = fields["collapse_delay_ms"].get_value_as_int()
        new_config["idle_fraction"] = fields["idle_percent"].get_value_as_int() / 100.0
        new_config["position_horizontal"] = fields["position_horizontal"].get_active_id() or "right"
        new_config["position_vertical"] = fields["position_vertical"].get_active_id() or "top"
        new_config["offset_x"] = fields["offset_x"].get_value_as_int()
        new_config["offset_y"] = fields["offset_y"].get_value_as_int()
        new_config["width"] = fields["width"].get_value_as_int()
        new_config["height"] = fields["height"].get_value_as_int()
        new_config["auto_update"] = self.update_panel.auto_install.get_active()
        new_config["monitor"] = fields["monitor"].get_active_id() or "primary"
        if not new_config["default_vault_path"] or not new_config["note_filename"].endswith(".md"):
            self.settings_status.set_text("Enter a vault path and a .md filename.")
            return False
        try:
            save_config(new_config, self.config_path)
        except OSError as exc:
            self.settings_status.set_text(f"Could not save settings: {exc}")
            return False
        self.config.update(new_config)
        self.update_panel.configure(new_config["auto_update"])
        self.set_default_size(new_config["width"], new_config["height"])
        self.set_size_request(new_config["width"], new_config["height"])
        self.resize(new_config["width"], new_config["height"])
        self.settings_content.set_size_request(max(240, new_config["width"] - 32), -1)
        self.settings_scroll.set_max_content_width(max(240, new_config["width"] - 16))
        self._apply_position()
        self._refresh_folder_choices()
        self._refresh_css()
        self.settings_status.set_text("Settings saved.")
        self._show_note_page()
        return True

    def _apply_style_config(self, updated: Config) -> None:
        """Persist appearance settings and refresh the overlay stylesheet."""
        save_config(updated, self.config_path)
        self.config.update(updated)
        self._refresh_css()

    def _choose_vault_folder(self) -> None:
        """Use GTK's native folder chooser; Plasma routes it through its KDE portal."""
        dialog = Gtk.FileChooserNative.new(
            "Select Obsidian vault folder", self, Gtk.FileChooserAction.SELECT_FOLDER,
            "Select", "Cancel")
        current = self.setting_widgets["default_vault_path"].get_text().strip()
        if current and Path(current).is_dir():
            dialog.set_current_folder(current)
        self.file_chooser_open = True

        def response(native: Any, result: int) -> None:
            self.file_chooser_open = False
            if result == Gtk.ResponseType.ACCEPT:
                selected = native.get_filename()
                if selected:
                    self.setting_widgets["default_vault_path"].set_text(selected)
            native.destroy()
            if not self.pointer_inside and not self.state.forced_open:
                self._schedule_collapse()

        dialog.connect("response", response)
        self.active_folder_chooser = dialog
        dialog.show()

    def _on_style_chooser_changed(self, opened: bool) -> None:
        """Prevent pointer-leave collapse while the appearance picker is open."""
        self.file_chooser_open = opened
        if opened:
            self._cancel_collapse()
        elif not self.pointer_inside and not self.state.forced_open:
            self._schedule_collapse()

    def _refresh_folder_choices(self) -> None:
        """Refresh the optional direct-child vault folder selector."""
        active = self.folder_combo.get_active_text() or "(root)"
        model = self.folder_combo.get_model()
        model.clear()
        self.folder_combo.append_text("(root)")
        vault = Path(self.config["default_vault_path"])
        folders = set(self.config.get("folders", []))
        try:
            folders.update(child.name for child in vault.iterdir() if child.is_dir())
        except OSError:
            pass
        self.available_folders = sorted(
            f for f in folders if Path(f).name == f and f not in (".", ".."))
        for folder in self.available_folders:
            self.folder_combo.append_text(folder)
        self.folder_combo.set_active(0)
        for index, name in enumerate(["(root)"] + self.available_folders):
            if name == active:
                self.folder_combo.set_active(index)
                break

    def _on_folder_popup(self, combo: Any, _property: Any) -> None:
        """Keep the overlay open while a native combo menu is active."""
        self.dropdown_open = bool(combo.get_property("popup-shown"))
        if self.dropdown_open:
            self._cancel_collapse()
        elif not self.pointer_inside and not self.state.forced_open:
            self._schedule_collapse()

    def _watch_theme_files(self) -> None:
        """Watch KDE and Pywal palette files without polling."""
        self.theme_monitors: list[Any] = []
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        for directory in (config_home, cache_home / "wal"):
            if not directory.is_dir():
                continue
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None)
                monitor.connect("changed", self._on_theme_file_changed)
                self.theme_monitors.append(monitor)
            except GLib.Error:
                pass

    def _on_theme_file_changed(self, _monitor: Any, file: Any, *_args: Any) -> None:
        """Schedule a coalesced style refresh after a palette change."""
        if file and file.get_basename() in ("kdeglobals", "colors.json"):
            if getattr(self, "theme_refresh_source", None):
                GLib.source_remove(self.theme_refresh_source)
            self.theme_refresh_source = GLib.timeout_add(180, self._refresh_css_debounced)

    def _refresh_css_debounced(self) -> bool:
        """Refresh CSS once after a short palette-write debounce."""
        self.theme_refresh_source = None
        self._refresh_css()
        return GLib.SOURCE_REMOVE

    def _refresh_css(self) -> bool:
        """Rebuild CSS from current theme configuration."""
        self.css_provider.load_from_data(build_css(self.config).encode("utf-8"))
        return GLib.SOURCE_REMOVE

    def _install_css(self) -> None:
        """Install the initial theme on the default GDK screen."""
        self.css_provider = Gtk.CssProvider()
        self.css_provider.load_from_data(build_css(self.config).encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _refresh_clock(self) -> bool:
        """Update the compact local date and time labels."""
        now = dt.datetime.now()
        self.day_label.set_text(now.strftime("%a"))
        self.date_label.set_text(now.strftime("%d.%m.%y"))
        self.time_label.set_text(now.strftime("%H:%M"))
        return GLib.SOURCE_CONTINUE

    def _sync_draft(self, *_args: Any) -> None:
        """Copy the editable GTK controls into persistent in-memory state."""
        draft = self.state.draft
        draft.title = self.title_entry.get_text()
        start, end = self.content_buffer.get_bounds()
        draft.content = self.content_buffer.get_text(start, end, True)
        draft.date_tag = self.date_entry.get_text()
        draft.folder = self.folder_combo.get_active_text() or "(root)"
        draft.append_mode = (self.append_mode_check.get_active()
                             or self._is_filepath_title(draft.title))
        self.status_label.hide()

    def _is_filepath_title(self, title: str) -> bool:
        """Recognize Markdown file paths entered in the title field."""
        return Path(os.path.expandvars(os.path.expanduser(title.strip()))).suffix.lower() == ".md"

    def _on_title_changed(self, _entry: Gtk.Entry) -> None:
        """Automatically enable append mode when the title is a Markdown path."""
        is_filepath = self._is_filepath_title(self.title_entry.get_text())
        if is_filepath:
            self._set_append_mode(True)
        elif self._title_was_filepath:
            self._set_append_mode(False)
        self._title_was_filepath = is_filepath
        self._sync_draft()

    def _set_append_mode(self, enabled: bool) -> None:
        """Set the single append-mode control and synchronize the draft."""
        self._updating_append_controls = True
        self.append_mode_check.set_active(enabled)
        self._updating_append_controls = False
        self._sync_draft()

    def _on_append_checkbox_toggled(self, _button: Gtk.CheckButton) -> None:
        """Mirror checkbox changes in the submit mode selector."""
        if not self._updating_append_controls:
            self._set_append_mode(self.append_mode_check.get_active())

    def _on_date_mode_changed(self, combo: Gtk.ComboBoxText) -> None:
        """Set the date field to an explicit date or the no-date value."""
        no_date = combo.get_active_id() == "none"
        self.date_entry.set_sensitive(not no_date)
        expected = "none" if no_date else "today"
        current = self.date_entry.get_text().strip().casefold()
        if (current in ("none", "no date")) != no_date:
            self.date_entry.set_text(expected)
        self._sync_draft()

    def _on_date_entry_changed(self, _entry: Gtk.Entry) -> None:
        """Keep the date selector aligned when users type `none`."""
        value = self.date_entry.get_text().strip().casefold()
        expected = "none" if value in ("none", "no date") else "date"
        if self.date_mode_combo.get_active_id() != expected:
            self.date_mode_combo.set_active_id(expected)
        self._sync_draft()

    def _clear_editor(self) -> None:
        """Clear controls and return submission options to their defaults."""
        self.title_entry.set_text("")
        self.content_buffer.set_text("")
        self.date_mode_combo.set_active_id("date")
        self.date_entry.set_text("")
        self.folder_combo.set_active(0)
        self._set_append_mode(False)

    def _on_title_enter(self, _entry: Any) -> None:
        """Move focus from title to body when Enter is pressed."""
        self.state.begin_content()
        self.content_view.grab_focus()

    def _on_enter(self, _widget: Any, event: Any) -> bool:
        """Expand the note when the pointer enters its layer surface."""
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.pointer_inside = True
        self._cancel_collapse()
        self.expand(focus=not self.expanded)
        return False

    def _on_leave(self, _widget: Any, event: Any) -> bool:
        """Schedule collapse after pointer and transient menus leave."""
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.pointer_inside = False
        if (not self.dropdown_open and not self.file_chooser_open and not self.state.forced_open
                and self.state.mode != Mode.DISCARD_CONFIRM):
            self._schedule_collapse()
        return False

    def _animate_to(self, target: int) -> None:
        """Animate the active edge margin using GTK timeout callbacks."""
        self._stop_animation()
        edge = self.position_vertical_edge
        current = LayerShell.get_margin(self, edge)
        self.animation_from = current
        self.animation_to = target
        self.animation_start = time.monotonic()
        duration = max(1, self.config["anim_ms"]) / 1000.0

        def frame() -> bool:
            """Advance one animation frame and stop at the final position."""
            progress = min(1.0, (time.monotonic() - self.animation_start) / duration)
            eased = 1.0 - (1.0 - progress) ** 3
            value = round(self.animation_from + (self.animation_to - self.animation_from) * eased)
            LayerShell.set_margin(self, edge, value)
            if progress >= 1.0:
                self.animation_source = None
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        self.animation_source = GLib.timeout_add(16, frame)

    def _stop_animation(self) -> None:
        """Cancel a running margin animation if one exists."""
        if self.animation_source is not None:
            GLib.source_remove(self.animation_source)
            self.animation_source = None

    def _cancel_collapse(self) -> None:
        """Cancel a pending hide callback."""
        if self.collapse_source is not None:
            GLib.source_remove(self.collapse_source)
            self.collapse_source = None

    def _schedule_collapse(self) -> None:
        """Schedule a deferred collapse after pointer leave."""
        self._cancel_collapse()

        def finish() -> bool:
            """Collapse only if no pointer or forced-open state prevents it."""
            self.collapse_source = None
            if (not self.pointer_inside and not self.dropdown_open
                    and not self.file_chooser_open and not self.state.forced_open):
                self.collapse()
            return GLib.SOURCE_REMOVE

        delay = int(self.config.get("collapse_delay_ms", 700))
        if delay <= 0:
            finish()
        else:
            self.collapse_source = GLib.timeout_add(delay, finish)

    def expand(self, focus: bool = False) -> None:
        """Reveal the overlay and optionally focus the active editor."""
        self.expanded = True
        LayerShell.set_keyboard_interactivity(self, True)
        self._animate_to(self.position_vertical_base)
        if not focus or self.page_stack.get_visible_child_name() == "settings":
            return
        if self.state.mode == Mode.CONTENT:
            self.content_view.grab_focus()
        elif self.state.mode != Mode.DISCARD_CONFIRM:
            self.title_entry.grab_focus()

    def collapse(self) -> None:
        """Hide the overlay to its idle tab without changing the draft."""
        if self.dropdown_open:
            return
        self._cancel_collapse()
        self.expanded = False
        LayerShell.set_keyboard_interactivity(self, False)
        self._animate_to(self.idle_margin())

    def force_open(self) -> None:
        """Open the overlay and retain it until toggled closed."""
        self.state.forced_open = True
        LayerShell.set_keyboard_interactivity(self, True)
        self.present()
        self.expand(focus=True)

    def force_close(self) -> None:
        """Clear forced-open mode and collapse when the pointer is outside."""
        self.state.forced_open = False
        if not self.pointer_inside:
            self.collapse()

    def toggle(self) -> None:
        """Toggle the forced-open state for IPC commands."""
        self.force_close() if self.state.forced_open else self.force_open()

    def _on_key(self, _widget: Any, event: Any) -> bool:
        """Handle shortcuts directly when GTK does not activate an accelerator."""
        key = event.keyval
        control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if self.state.mode == Mode.DISCARD_CONFIRM:
            if key in (Gdk.KEY_y, Gdk.KEY_Y):
                self._resolve_discard(True)
            elif key in (Gdk.KEY_n, Gdk.KEY_N, Gdk.KEY_Escape):
                self._resolve_discard(False)
            return True
        if control and key in (Gdk.KEY_s, Gdk.KEY_S):
            self._toggle_settings()
            return True
        if control and shift and key in (Gdk.KEY_f, Gdk.KEY_F):
            self._open_search_mode()
            return True
        if control and shift and key in (Gdk.KEY_d, Gdk.KEY_D):
            self._open_date_menu()
            return True
        if control and shift and key in (Gdk.KEY_a, Gdk.KEY_A):
            self._toggle_append_mode()
            return True
        if control and key in (Gdk.KEY_d, Gdk.KEY_D):
            self._toggle_date_mode()
            return True
        if control and key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self.page_stack.get_visible_child_name() == "note":
                self.commit_note()
                return True
        if control and key in (Gdk.KEY_1, Gdk.KEY_KP_1):
            if self._body_has_focus():
                self._insert_heading_marker()
                return True
        if control and key in (Gdk.KEY_b, Gdk.KEY_B):
            self._wrap_if_editing("**")
            return self._body_has_focus()
        if control and key in (Gdk.KEY_i, Gdk.KEY_I):
            self._wrap_if_editing("*")
            return self._body_has_focus()
        if control and key in (Gdk.KEY_u, Gdk.KEY_U):
            self._wrap_if_editing("<u>", "</u>")
            return self._body_has_focus()
        if key == Gdk.KEY_Escape:
            self._open_discard_prompt()
            return True
        return False

    def _install_accelerators(self) -> None:
        """Register Ctrl shortcuts before focused GTK inputs process key events."""
        self.accel_group = Gtk.AccelGroup()
        self.add_accel_group(self.accel_group)
        control = Gdk.ModifierType.CONTROL_MASK
        shift = Gdk.ModifierType.SHIFT_MASK
        bindings: tuple[tuple[int, Gdk.ModifierType, Any], ...] = (
            (Gdk.KEY_s, control, self._toggle_settings),
            (Gdk.KEY_F, control | shift, self._open_search_mode),
            (Gdk.KEY_D, control | shift, self._open_date_menu),
            (Gdk.KEY_A, control | shift, self._toggle_append_mode),
            (Gdk.KEY_d, control, self._toggle_date_mode),
            (Gdk.KEY_Return, control, self.commit_note),
            (Gdk.KEY_KP_Enter, control, self.commit_note),
            (Gdk.KEY_1, control, self._insert_heading_if_editing),
            (Gdk.KEY_b, control, lambda: self._wrap_if_editing("**")),
            (Gdk.KEY_i, control, lambda: self._wrap_if_editing("*")),
            (Gdk.KEY_u, control, lambda: self._wrap_if_editing("<u>", "</u>")),
        )
        for keyval, modifiers, callback in bindings:
            self.accel_group.connect(
                keyval, modifiers, Gtk.AccelFlags.VISIBLE,
                self._accelerator_callback(callback))

    def _accelerator_callback(self, callback: Any) -> Any:
        """Adapt a no-argument action to the GTK accelerator closure signature."""
        def activate(*_args: Any) -> bool:
            callback()
            return True

        return activate

    def _open_date_menu(self) -> None:
        """Focus and open the date selection menu."""
        self.date_mode_combo.grab_focus()
        self.date_mode_combo.popup()

    def _toggle_append_mode(self) -> None:
        """Toggle append mode from its keyboard shortcut."""
        self._set_append_mode(not self.append_mode_check.get_active())

    def _toggle_date_mode(self) -> None:
        """Toggle between today's date and no date."""
        set_no_date = self.date_mode_combo.get_active_id() != "none"
        self.date_mode_combo.set_active_id("none" if set_no_date else "date")
        if not set_no_date and self.date_entry.get_text().strip().casefold() == "none":
            self.date_entry.set_text("today")

    def _body_has_focus(self) -> bool:
        """Return whether body-formatting shortcuts have a valid target."""
        return (self.page_stack.get_visible_child_name() == "note"
                and self.get_focus() == self.content_view)

    def _wrap_if_editing(self, prefix: str, suffix: str | None = None) -> None:
        """Apply Markdown delimiters only while the note body has focus."""
        if self._body_has_focus():
            self._wrap_selection(prefix, suffix)

    def _insert_heading_if_editing(self) -> None:
        """Insert a heading marker only while the note body has focus."""
        if self._body_has_focus():
            self._insert_heading_marker()

    def _open_search_mode(self) -> None:
        """Show a Markdown-only picker for selecting an existing vault note."""
        vault = Path(self.config["default_vault_path"]).expanduser()
        dialog = Gtk.FileChooserDialog(
            title="Search Markdown notes", parent=self,
            action=Gtk.FileChooserAction.OPEN,
            buttons=("Cancel", Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.ACCEPT))
        dialog.set_modal(True)
        if vault.is_dir():
            dialog.set_current_folder(str(vault))
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Markdown notes (*.md)")
        file_filter.add_pattern("*.md")
        file_filter.add_pattern("*.MD")
        dialog.add_filter(file_filter)
        self.file_chooser_open = True

        def response(chooser: Gtk.FileChooserDialog, result: int) -> None:
            """Use the selected vault note as the append destination."""
            self.file_chooser_open = False
            filename = chooser.get_filename() if result == Gtk.ResponseType.ACCEPT else None
            if filename:
                selected = Path(filename)
                try:
                    title = selected.relative_to(vault).as_posix()
                except ValueError:
                    title = str(selected)
                self.title_entry.set_text(title)
                self._set_append_mode(True)
                self.state.begin_content()
                self.content_view.grab_focus()
            chooser.destroy()
            if not self.pointer_inside and not self.state.forced_open:
                self._schedule_collapse()

        dialog.connect("response", response)
        self.active_search_dialog = dialog
        dialog.show_all()

    def _wrap_selection(self, prefix: str, suffix: str | None = None) -> None:
        """Wrap selected Markdown body text or place the cursor between markers."""
        closing = suffix if suffix is not None else prefix
        selection = self.content_buffer.get_selection_bounds()
        if selection:
            start, end = selection
            selected = self.content_buffer.get_text(start, end, True)
            self.content_buffer.delete(start, end)
            self.content_buffer.insert(start, f"{prefix}{selected}{closing}")
            self.content_buffer.place_cursor(start)
            return
        self.content_buffer.insert_at_cursor(f"{prefix}{closing}")
        cursor = self.content_buffer.get_iter_at_mark(self.content_buffer.get_insert())
        cursor.backward_chars(len(closing))
        self.content_buffer.place_cursor(cursor)

    def _insert_heading_marker(self) -> None:
        """Prefix the current body line with a level-one Markdown heading."""
        cursor = self.content_buffer.get_iter_at_mark(self.content_buffer.get_insert())
        line_start = cursor.copy()
        line_start.set_line_offset(0)
        line_end = line_start.copy()
        line_end.forward_to_line_end()
        line = self.content_buffer.get_text(line_start, line_end, True)
        if not line.startswith("# "):
            self.content_buffer.insert(line_start, "# ")

    def _open_discard_prompt(self) -> None:
        """Ask for confirmation before clearing a nonempty draft."""
        self._sync_draft()
        if not self.state.ask_discard():
            self.force_close()
            return
        self.dialog_box.show_all()
        self.discard_yes.grab_focus()

    def _resolve_discard(self, discard: bool) -> None:
        """Apply the chosen discard response and restore editor focus."""
        if discard:
            self.state.confirm_discard()
            self._clear_editor()
            self.force_close()
        else:
            self.state.cancel_discard()
            if self.state.mode == Mode.CONTENT:
                self.content_view.grab_focus()
            else:
                self.title_entry.grab_focus()
        self.dialog_box.hide()

    def commit_note(self) -> None:
        """Persist the current draft and clear it only after success."""
        self._sync_draft()
        draft = self.state.draft
        if not draft.has_content():
            self._show_status("Nothing to save.")
            return
        try:
            if draft.append_mode:
                destination = append_to_file(self.config, draft.title, draft.content,
                                              draft.date_tag, draft.folder)
            else:
                destination = write_note(self.config, draft.title, draft.content,
                                         draft.date_tag, draft.folder)
        except (OSError, ValueError, KeyError) as exc:
            self._show_status(f"Save failed: {exc}")
            print(f"[cornernote] save failed: {exc}", file=sys.stderr)
            return
        print(f"[cornernote] saved {destination}")
        self.state.committed()
        self._clear_editor()
        self.force_close()

    def _show_status(self, message: str) -> None:
        """Show an inline save result in the note footer."""
        self.status_label.set_text(message)
        self.status_label.show()

    def _on_delete(self, *_args: Any) -> bool:
        """Hide the persistent overlay instead of terminating the daemon."""
        self.force_close()
        return True


def main() -> int:
    """Start the GTK daemon and run its event loop."""
    if os.environ.get("XDG_SESSION_TYPE") not in (None, "wayland"):
        print("CornerNote requires a Wayland session (gtk-layer-shell).", file=sys.stderr)
        return 1
    try:
        config = load_config(os.environ.get("CORNERNOTE_CONFIG", CONFIG_PATH))
        window = CornerNote(config)
        window.watch_suspend_resume()
        socket_server = start_server(config["socket_path"], window.toggle)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[cornernote] startup failed: {exc}", file=sys.stderr)
        return 1

    def shutdown(*_args: Any) -> bool:
        """Release IPC resources and stop GTK on process termination."""
        if window.system_bus is not None and window.sleep_subscription is not None:
            window.system_bus.signal_unsubscribe(window.sleep_subscription)
            window.sleep_subscription = None
        if window.resume_source is not None:
            GLib.source_remove(window.resume_source)
            window.resume_source = None
        try:
            socket_server.close()
            path = Path(config["socket_path"])
            if path.is_socket():
                path.unlink()
        except OSError:
            pass
        Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, shutdown)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

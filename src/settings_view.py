"""GTK settings page for display, vault, appearance, and update controls."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from gi.repository import Gdk, Gtk, Pango

from style import Config
from style_editor import StyleEditor
from update_view import UpdatePanel


class SettingsPage(Gtk.Box):
    """Edit configuration while the window owns persistence and application."""

    def __init__(
        self,
        config: Config,
        on_save: Callable[[], Any],
        on_cancel: Callable[[], Any],
        on_style_apply: Callable[[Config], None],
        on_status: Callable[[str], None],
        on_popup: Callable[[Any, Any], None],
        on_chooser_changed: Callable[[bool], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.get_style_context().add_class("cn-settings")
        self.fields: dict[str, Any] = {}
        self.on_chooser_changed = on_chooser_changed

        heading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        heading = Gtk.Label(label="CornerNote Settings", xalign=0)
        heading.get_style_context().add_class("cn-day")
        heading_row.pack_start(heading, True, True, 2)
        self.pack_start(heading_row, False, False, 2)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_width(False)
        self.scroll.set_min_content_width(0)
        self.scroll.set_max_content_width(max(240, int(config["width"]) - 16))
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.content.set_hexpand(True)
        self.scroll.add(self.content)
        self.pack_start(self.scroll, True, True, 0)

        display = self._make_group("Display and position", True)
        for row, (key, label, options) in enumerate(
            (
                ("monitor", "Screen", ()),
                (
                    "position_horizontal",
                    "Horizontal",
                    (("left", "Left"), ("center", "Center"), ("right", "Right")),
                ),
                (
                    "position_vertical",
                    "Vertical",
                    (("top", "Top"), ("center", "Center"), ("bottom", "Bottom")),
                ),
            )
        ):
            combo = Gtk.ComboBoxText()
            combo.get_style_context().add_class("cn-folder")
            combo.connect("notify::popup-shown", on_popup)
            for value, text in options:
                combo.append(value, text)
            self._add_row(display, row, label, key, combo)
        for row, (key, label, minimum, maximum, step) in enumerate(
            (
                ("offset_x", "X offset (px)", -5000, 5000, 10),
                ("offset_y", "Y offset (px)", -5000, 5000, 10),
                ("width", "Width (px)", 240, 1600, 20),
                ("height", "Height (px)", 180, 1200, 20),
                ("idle_percent", "Idle tab (%)", 1, 50, 1),
            ),
            start=3,
        ):
            self._add_spin(display, row, label, key, minimum, maximum, step)
        self.fields["offset_y"].set_tooltip_text(
            "The offset is limited near the top or bottom edge so the idle tab stays visible."
        )
        self.fields["position_vertical"].connect(
            "changed", self._update_y_offset_limits
        )
        for key in ("height", "idle_percent"):
            self.fields[key].connect("value-changed", self._update_y_offset_limits)

        vault = self._make_group("Vault and files")
        for row, (key, label) in enumerate(
            (
                ("default_vault_path", "Obsidian vault"),
                ("note_filename", "Markdown filename"),
                ("date_format", "Date format"),
            )
        ):
            self._add_row(vault, row, label, key, Gtk.Entry())
        self.fields["default_vault_path"].set_placeholder_text(
            "Path to your Obsidian vault"
        )

        animation = self._make_group("Animation")
        self._add_spin(animation, 0, "Slide speed (ms)", "anim_ms", 100, 1200, 50)
        self._add_spin(
            animation, 1, "Hide delay (ms)", "collapse_delay_ms", 0, 3000, 100
        )

        self.appearance_expander = Gtk.Expander(label="Appearance and style")
        self.style_editor = StyleEditor(
            config, on_style_apply, on_popup, on_chooser_changed
        )
        self.appearance_expander.add(self.style_editor)
        self.content.pack_start(self.appearance_expander, False, False, 0)

        updates = Gtk.Expander(label="Updates")
        self.update_panel = UpdatePanel(on_status)
        updates.add(self.update_panel)
        self.content.pack_start(updates, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("cn-status")
        actions.pack_start(self.status, True, True, 0)
        cancel = Gtk.Button(label="[ Cancel ]")
        cancel.connect("clicked", lambda *_: on_cancel())
        save = Gtk.Button(label="[ Save settings ]")
        save.get_style_context().add_class("cn-save")
        save.connect("clicked", lambda *_: on_save())
        actions.pack_end(cancel, False, False, 0)
        actions.pack_end(save, False, False, 0)
        self.select_vault_button = Gtk.Button(label="[ Select vault folder… ]")
        self.select_vault_button.connect(
            "clicked", lambda *_: self.choose_vault_folder()
        )
        self.pack_end(self.select_vault_button, False, False, 0)
        self.pack_end(actions, False, False, 0)

    def _make_group(self, label: str, expanded: bool = False) -> Gtk.Grid:
        expander = Gtk.Expander(label=label)
        expander.set_expanded(expanded)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        expander.add(grid)
        self.content.pack_start(expander, False, False, 0)
        return grid

    def _add_row(
        self, grid: Gtk.Grid, row: int, label: str, key: str, widget: Gtk.Widget
    ) -> None:
        """Place a setting label above a full-width input control."""
        text = Gtk.Label(label=label, xalign=0)
        text.set_halign(Gtk.Align.START)
        widget.set_hexpand(True)
        widget.set_halign(Gtk.Align.FILL)
        grid.attach(text, 0, row * 2, 2, 1)
        grid.attach(widget, 0, row * 2 + 1, 2, 1)
        self.fields[key] = widget

    def _add_spin(
        self,
        grid: Gtk.Grid,
        row: int,
        label: str,
        key: str,
        minimum: int,
        maximum: int,
        step: int,
    ) -> None:
        widget = Gtk.SpinButton.new_with_range(minimum, maximum, step)
        widget.set_numeric(True)
        self._add_row(grid, row, label, key, widget)

    def set_config(self, config: Config, monitor_index: int) -> None:
        """Populate controls from the active configuration when opening settings."""
        self.style_editor.set_config(config)
        fields = self.fields
        self.populate_monitor_choices()
        fields["monitor"].set_active_id(
            str(monitor_index) if monitor_index >= 0 else "primary"
        )
        for key in ("default_vault_path", "note_filename", "date_format"):
            fields[key].set_text(config[key])
        for key in ("anim_ms", "collapse_delay_ms"):
            fields[key].set_value(config[key])
        fields["idle_percent"].set_value(round(config["idle_fraction"] * 100))
        fields["position_horizontal"].set_active_id(
            config.get("position_horizontal", "right")
        )
        fields["position_vertical"].set_active_id(
            config.get("position_vertical", "top")
        )
        fields["offset_x"].set_value(config.get("offset_x", 0))
        fields["offset_y"].set_value(config.get("offset_y", 0))
        fields["width"].set_value(config["width"])
        fields["height"].set_value(config["height"])
        self.update_panel.auto_install.set_active(config.get("auto_update", False))
        self._update_y_offset_limits()
        self.status.set_text("")

    def read_config(self, config: Config) -> Config:
        """Return edited values without persisting or applying the configuration."""
        updated = dict(config)
        fields = self.fields
        updated["default_vault_path"] = os.path.expanduser(
            fields["default_vault_path"].get_text().strip()
        )
        for key in ("note_filename", "date_format"):
            updated[key] = fields[key].get_text().strip()
        for key in (
            "anim_ms",
            "collapse_delay_ms",
            "offset_x",
            "offset_y",
            "width",
            "height",
        ):
            updated[key] = fields[key].get_value_as_int()
        updated["idle_fraction"] = fields["idle_percent"].get_value_as_int() / 100.0
        updated["position_horizontal"] = (
            fields["position_horizontal"].get_active_id() or "right"
        )
        updated["position_vertical"] = (
            fields["position_vertical"].get_active_id() or "top"
        )
        updated["auto_update"] = self.update_panel.auto_install.get_active()
        updated["monitor"] = fields["monitor"].get_active_id() or "primary"
        return updated

    def set_width(self, width: int) -> None:
        """Keep settings controls within the newly configured window width."""
        self.content.set_size_request(max(240, width - 32), -1)
        self.scroll.set_max_content_width(max(240, width - 16))

    def _update_y_offset_limits(self, *_args: Any) -> None:
        """Limit outward vertical adjustment so an idle tab remains visible."""
        fields = self.fields
        visible_tab = max(
            1,
            round(
                fields["height"].get_value_as_int()
                * fields["idle_percent"].get_value_as_int()
                / 100
            ),
        )
        position = fields["position_vertical"].get_active_id()
        if position == "top":
            fields["offset_y"].set_range(1 - visible_tab, 5000)
        elif position == "bottom":
            fields["offset_y"].set_range(-5000, visible_tab - 1)
        else:
            fields["offset_y"].set_range(-5000, 5000)

    def populate_monitor_choices(self) -> None:
        """Refresh the screen selector with currently connected displays."""
        combo = self.fields["monitor"]
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
            name = (
                " ".join(part.strip() for part in (manufacturer, model) if part.strip())
                or "Display"
            )
            geometry = monitor.get_geometry()
            label = (
                f"Screen {index + 1}: {name} — "
                f"{geometry.width}×{geometry.height} at "
                f"{geometry.x},{geometry.y}"
            )
            if monitor.is_primary():
                label += " (primary)"
            combo.append(str(index), label)
        if count == 0:
            combo.append("primary", "Primary display")

    def choose_vault_folder(self) -> None:
        """Use the desktop's native folder chooser to select an Obsidian vault."""
        dialog = Gtk.FileChooserNative.new(
            "Select Obsidian vault folder",
            self.get_toplevel(),
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Select",
            "Cancel",
        )
        current = self.fields["default_vault_path"].get_text().strip()
        if current and Path(current).is_dir():
            dialog.set_current_folder(current)
        self.on_chooser_changed(True)

        def response(native: Any, result: int) -> None:
            if result == Gtk.ResponseType.ACCEPT:
                selected = native.get_filename()
                if selected:
                    self.fields["default_vault_path"].set_text(selected)
            native.destroy()
            self.on_chooser_changed(False)

        dialog.connect("response", response)
        self.active_folder_chooser = dialog
        dialog.show()

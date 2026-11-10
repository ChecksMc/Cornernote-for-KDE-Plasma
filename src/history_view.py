"""Asynchronous, read-only browsing of saved vault notes."""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

from gi.repository import GLib, Gtk, Pango

from history import DEFAULT_HISTORY_LIMIT, SavedNote, list_notes, read_note
from markdown_render import RenderedMarkdown, render_markdown
from markdown_view import make_view, show_markdown


class HistoryPage(Gtk.Box):
    """List and preview saved files without touching the current draft."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.config: dict[str, Any] = {}
        self.loading = False
        self.reading = False
        self._generation = 0
        self._destroyed = False
        self._load_error = ""
        self.connect("destroy", self._on_destroy)
        self.stack = Gtk.Stack()
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.pack_start(self.stack, True, True, 0)

        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search saved filenames…")
        self.search_entry.set_width_chars(1)
        self.search_entry.connect("search-changed", self._filter_changed)
        actions.pack_start(self.search_entry, True, True, 0)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_: self.refresh())
        actions.pack_end(refresh, False, False, 0)
        listing.pack_start(actions, False, False, 0)
        hint = Gtk.Label(label=f"Latest {DEFAULT_HISTORY_LIMIT} Markdown files · newest first",
                         xalign=0)
        hint.set_line_wrap(True)
        listing.pack_start(hint, False, False, 0)
        self.list_status = Gtk.Label(xalign=0)
        self.list_status.set_line_wrap(True)
        self.list_status.set_no_show_all(True)
        listing.pack_start(self.list_status, False, False, 0)
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.set_filter_func(self._filter_row)
        self.list_box.connect("row-activated", self._on_row_activated)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list_box)
        listing.pack_start(scroll, True, True, 0)
        self.stack.add_named(listing, "list")

        detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        detail_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        back = Gtk.Button(label="← Back")
        back.connect("clicked", lambda *_: self.go_back())
        detail_actions.pack_start(back, False, False, 0)
        self.note_title = self._short_label("")
        detail_actions.pack_start(self.note_title, True, True, 0)
        detail.pack_start(detail_actions, False, False, 0)
        self.detail_status = Gtk.Label(xalign=0)
        self.detail_status.set_line_wrap(True)
        self.detail_status.set_no_show_all(True)
        detail.pack_start(self.detail_status, False, False, 0)
        self.viewer = make_view()
        viewer_scroll = Gtk.ScrolledWindow()
        viewer_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        viewer_scroll.add(self.viewer)
        detail.pack_start(viewer_scroll, True, True, 0)
        self.stack.add_named(detail, "detail")

    @staticmethod
    def _short_label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(1)
        label.set_hexpand(True)
        return label

    def open(self, config: dict[str, Any]) -> None:
        """Reload the vault snapshot when the overlay opens history."""
        self.config = dict(config)
        self.search_entry.set_text("")
        self.refresh()

    def refresh(self) -> None:
        """Scan file metadata off the GTK main loop."""
        self._generation += 1
        generation, config = self._generation, dict(self.config)
        self.loading, self.reading = True, False
        self._load_error = ""
        self.stack.set_visible_child_name("list")
        for row in self.list_box.get_children():
            self.list_box.remove(row)
        self.list_status.set_text("Loading saved notes…")
        self.list_status.show()

        def work() -> None:
            notes, error = [], ""
            try:
                notes = list_notes(config)
            except (OSError, ValueError) as exc:
                error = f"Could not load saved notes: {exc}"
            GLib.idle_add(self._finish_loading, generation, notes, error)

        threading.Thread(target=work, daemon=True).start()

    def _finish_loading(self, generation: int, notes: list[SavedNote],
                        error: str) -> bool:
        if self._destroyed or generation != self._generation:
            return GLib.SOURCE_REMOVE
        self.loading = False
        for note in notes:
            row = Gtk.ListBoxRow()
            row.note = note
            row.set_tooltip_text(note.path.as_posix())
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            content.set_border_width(5)
            content.pack_start(self._short_label(note.title), False, False, 0)
            date = dt.datetime.fromtimestamp(note.modified_ns / 1e9).strftime("%Y-%m-%d %H:%M")
            content.pack_start(self._short_label(f"{note.path.as_posix()} · {date}"),
                               False, False, 0)
            row.add(content)
            self.list_box.add(row)
        self.list_box.show_all()
        self._load_error = error
        self.list_box.invalidate_filter()
        self._update_list_status()
        return GLib.SOURCE_REMOVE

    def _filter_changed(self, *_: Any) -> None:
        self.list_box.invalidate_filter()
        self._update_list_status()

    def _update_list_status(self) -> None:
        if self.loading:
            return
        rows = self.list_box.get_children()
        message = self._load_error
        if not message and not rows:
            message = "No saved Markdown notes in this vault."
        elif not message and not any(row.get_child_visible() for row in rows):
            message = "No saved filenames match your search."
        self.list_status.set_text(message)
        self.list_status.set_visible(bool(message))

    def _filter_row(self, row: Gtk.ListBoxRow) -> bool:
        return self.search_entry.get_text().casefold() in row.note.path.as_posix().casefold()

    def _on_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self._open_note(row.note)

    def _open_note(self, note: SavedNote) -> None:
        self._generation += 1
        generation, config = self._generation, dict(self.config)
        self.loading, self.reading = False, True
        self.note_title.set_text(note.path.as_posix())
        self.note_title.set_tooltip_text(note.path.as_posix())
        self.viewer.get_buffer().set_text("")
        self.detail_status.set_text("Loading note…")
        self.detail_status.show()
        self.stack.set_visible_child_name("detail")

        def work() -> None:
            source, rendered, error = "", None, ""
            try:
                source = read_note(config, note)
                rendered = render_markdown(source)
            except (OSError, ValueError, UnicodeError) as exc:
                error = f"Could not open note: {exc}"
            GLib.idle_add(self._finish_reading, generation, source, rendered, error)

        threading.Thread(target=work, daemon=True).start()

    def _finish_reading(self, generation: int, source: str,
                        rendered: RenderedMarkdown | None, error: str) -> bool:
        if self._destroyed or generation != self._generation:
            return GLib.SOURCE_REMOVE
        self.reading = False
        if not error:
            show_markdown(self.viewer.get_buffer(), source, rendered)
            self.viewer.scroll_to_iter(self.viewer.get_buffer().get_start_iter(), 0, False, 0, 0)
        self.detail_status.set_text(error)
        self.detail_status.set_visible(bool(error))
        return GLib.SOURCE_REMOVE

    def go_back(self) -> bool:
        """Return to the file list, invalidating an unfinished preview."""
        if self.stack.get_visible_child_name() != "detail":
            return False
        self._generation += 1
        self.reading = False
        self.stack.set_visible_child_name("list")
        self.search_entry.grab_focus()
        return True

    def _on_destroy(self, *_: Any) -> None:
        self._destroyed = True
        self._generation += 1

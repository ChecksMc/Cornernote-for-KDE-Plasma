"""Manual updates and opt-in automatic installation without restarting GTK."""

from __future__ import annotations

import threading
from typing import Any, Callable

from gi.repository import GLib, Gtk, Pango

from updater import UpdateError, UpdateInfo, check_for_updates, install_update

AUTO_UPDATE_INTERVAL_SECONDS = 6 * 60 * 60


class UpdatePanel(Gtk.Box):
    """Run Git operations outside GTK's main loop and keep drafts in memory."""

    def __init__(self, notify: Callable[[str], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.notify = notify
        self.busy = False
        self.restart_required = False
        self.info: UpdateInfo | None = None
        self._auto_enabled = False
        self._timer: int | None = None
        self._startup: int | None = None
        self._destroyed = False
        self.connect("destroy", self._on_destroy)

        self.auto_install = Gtk.CheckButton(label="Install updates automatically")
        self.pack_start(self.auto_install, False, False, 0)
        hint = Gtk.Label(label="When enabled, checks at startup and every six hours. "
                         "Save this setting with Save settings. Restart after installation.",
                         xalign=0)
        hint.set_line_wrap(True)
        hint.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        hint.set_max_width_chars(1)
        self.pack_start(hint, False, False, 0)
        # Stack buttons vertically so they fit narrow overlays and large fonts.
        self.check_button = Gtk.Button(label="Check for updates")
        self.check_button.connect("clicked", lambda *_: self.check())
        self.pack_start(self.check_button, False, False, 0)
        self.install_button = Gtk.Button(label="Install update")
        self.install_button.set_sensitive(False)
        self.install_button.connect("clicked", lambda *_: self.install())
        self.pack_start(self.install_button, False, False, 0)
        self.status = Gtk.Label(label="Updates use this checkout's tracked Git branch.", xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status.set_max_width_chars(1)
        self.status.set_selectable(True)
        self.pack_start(self.status, False, False, 0)

    def configure(self, enabled: bool) -> None:
        """Apply the saved preference, starting or stopping periodic checks."""
        if enabled == self._auto_enabled:
            return
        self._auto_enabled = enabled
        for source in (self._timer, self._startup):
            if source is not None:
                GLib.source_remove(source)
        self._timer = self._startup = None
        if enabled:
            self._startup = GLib.idle_add(self._startup_check)
            self._timer = GLib.timeout_add_seconds(
                AUTO_UPDATE_INTERVAL_SECONDS, self._automatic_check)

    def _startup_check(self) -> bool:
        self._startup = None
        self._automatic_check()
        return GLib.SOURCE_REMOVE

    def _automatic_check(self) -> bool:
        if not self._destroyed and self._auto_enabled:
            self.check(automatic=True)
        return GLib.SOURCE_CONTINUE

    def _set_busy(self, message: str) -> None:
        self.busy = True
        self.check_button.set_sensitive(False)
        self.install_button.set_sensitive(False)
        self.status.set_text(message)

    def check(self, automatic: bool = False) -> None:
        """Fetch the current upstream once; overlapping requests are ignored."""
        if self._destroyed or self.busy or self.restart_required:
            return
        self.info = None
        self._set_busy("Checking for updates…")

        def work() -> None:
            info, error = None, ""
            try:
                info = check_for_updates()
            except (UpdateError, OSError, ValueError) as exc:
                error = f"Could not check for updates: {exc}"
            GLib.idle_add(self._checked, info, error, automatic)

        # Let an in-flight Git operation finish if the daemon is shut down.
        threading.Thread(target=work).start()

    def _checked(self, info: UpdateInfo | None, error: str, automatic: bool) -> bool:
        if self._destroyed:
            return GLib.SOURCE_REMOVE
        self.busy = False
        self.info = info
        self.check_button.set_sensitive(True)
        if error:
            self.status.set_text(error)
        elif info is not None and info.available:
            self.status.set_text(f"Update available on {info.branch}: "
                                 f"{info.current_revision[:8]} → {info.target_revision[:8]}.")
            self.install_button.set_sensitive(True)
            if automatic and self._auto_enabled:
                self.install()
        elif info is not None:
            self.status.set_text(f"Up to date on {info.branch} ({info.current_revision[:8]}).")
        return GLib.SOURCE_REMOVE

    def install(self) -> None:
        """Install only the revision shown by the completed check."""
        if self._destroyed or self.busy or self.restart_required or self.info is None:
            return
        info = self.info
        if not info.available:
            return
        self._set_busy("Installing update…")

        def work() -> None:
            error = ""
            try:
                install_update(info)
            except (UpdateError, OSError, ValueError) as exc:
                error = f"Could not install update: {exc}"
            GLib.idle_add(self._installed, error)

        threading.Thread(target=work).start()

    def _installed(self, error: str) -> bool:
        if self._destroyed:
            return GLib.SOURCE_REMOVE
        self.busy = False
        self.info = None
        self.restart_required = not bool(error)
        self.check_button.set_sensitive(bool(error))
        message = error or ("Update installed. Save your draft, then restart CornerNote "
                            "to use the new version.")
        self.status.set_text(message)
        self.notify(message)
        return GLib.SOURCE_REMOVE

    def _on_destroy(self, *_: Any) -> None:
        self._destroyed = True
        for source in (self._timer, self._startup):
            if source is not None:
                GLib.source_remove(source)
        self._timer = self._startup = None

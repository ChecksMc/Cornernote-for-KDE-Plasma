#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/cornernote"
APP_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
UNIT_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"

echo "CornerNote source: ${PROJECT_DIR}"
if [[ "${XDG_SESSION_TYPE:-}" != "wayland" ]]; then
  echo "CornerNote requires a Wayland session with layer-shell support." >&2
  echo "Log into KDE Plasma Wayland and run this installer again." >&2
  exit 1
fi
if [[ "${XDG_CURRENT_DESKTOP:-}" != *KDE* && "${KDE_FULL_SESSION:-}" != true \
      && -z "${KDE_SESSION_VERSION:-}" ]]; then
  echo "Warning: CornerNote is designed for KDE Plasma Wayland."
fi

dependencies_available() {
  command -v python3 >/dev/null 2>&1 && python3 -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("GtkLayerShell", "0.1"); from gi.repository import Gtk, GtkLayerShell' >/dev/null 2>&1
}

install_packages() {
  if ((EUID == 0)); then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "Installing system packages requires root or sudo." >&2
    return 1
  fi
}

if ! dependencies_available; then
  echo "Installing GTK 3, PyGObject, Cairo, and gtk-layer-shell dependencies."
  if command -v apt-get >/dev/null 2>&1; then
    install_packages apt-get install -y python3 python3-gi python3-cairo \
      gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1
  elif command -v rpm-ostree >/dev/null 2>&1; then
    install_packages rpm-ostree install \
      python3 python3-gobject python3-cairo gtk-layer-shell
    echo "System packages are layered. Reboot, then run install.sh again." >&2
    exit 0
  elif command -v dnf >/dev/null 2>&1; then
    install_packages dnf install -y python3 python3-gobject python3-cairo gtk-layer-shell
  elif command -v pacman >/dev/null 2>&1; then
    install_packages pacman --needed --noconfirm -S \
      python python-gobject python-cairo gtk-layer-shell
  elif command -v zypper >/dev/null 2>&1; then
    install_packages zypper --non-interactive install \
      python3 python3-gobject python3-cairo libgtk-layer-shell0 \
      typelib-1_0-GtkLayerShell-0_1
  else
    echo "Could not identify a supported package manager." >&2
    echo "Install Python 3, PyGObject, GTK 3, Cairo, and gtk-layer-shell manually, then rerun install.sh." >&2
    exit 1
  fi
fi

if ! dependencies_available; then
  echo "Required GTK or gtk-layer-shell introspection modules are still unavailable." >&2
  echo "Check your distribution's package names and repositories, then rerun install.sh." >&2
  exit 1
fi

mkdir -p "${BIN_DIR}" "${CONFIG_DIR}" "${APP_DIR}"
if [[ ! -e "${CONFIG_DIR}/config.json" ]]; then
  install -m 0644 "${PROJECT_DIR}/config.example.json" "${CONFIG_DIR}/config.json"
fi
# Only restore missing execute bits (e.g. after extracting a ZIP). Changing
# modes Git already tracks would make the built-in updater see local changes.
for executable in corner-note install.sh uninstall.sh src/main.py; do
  [[ -x "${PROJECT_DIR}/${executable}" ]] || chmod 0755 "${PROJECT_DIR}/${executable}"
done
ln -sfn "${PROJECT_DIR}/corner-note" "${BIN_DIR}/corner-note"
printf -v MAIN_SCRIPT '%q' "${PROJECT_DIR}/src/main.py"
cat > "${BIN_DIR}/cornernote-daemon" <<EOF
#!/usr/bin/env bash
export CORNERNOTE_CONFIG="\${XDG_CONFIG_HOME:-\${HOME}/.config}/cornernote/config.json"
exec /usr/bin/env python3 ${MAIN_SCRIPT}
EOF
chmod 0755 "${BIN_DIR}/cornernote-daemon"

# Quote the launcher so desktop entries work when the path contains spaces.
while IFS= read -r line; do
  if [[ "${line}" == Exec=* ]]; then
    printf 'Exec="%s" toggle\n' "${BIN_DIR}/corner-note"
  else
    printf '%s\n' "${line}"
  fi
done < "${PROJECT_DIR}/cornernote.desktop" > "${APP_DIR}/cornernote.desktop"
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  mkdir -p "${UNIT_DIR}"
  cat > "${UNIT_DIR}/cornernote.service" <<EOF
[Unit]
Description=CornerNote quick-note overlay
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart="${BIN_DIR}/cornernote-daemon"
Restart=on-failure
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=graphical-session.target
EOF
  rm -f "${AUTOSTART_DIR}/cornernote-daemon.desktop"
  systemctl --user daemon-reload
  systemctl --user enable cornernote.service
  if systemctl --user is-active --quiet cornernote.service; then
    # Never restart automatically: that would discard an unsaved draft.
    START_INSTRUCTIONS="systemctl --user restart cornernote  (save any open draft first)"
  else
    START_INSTRUCTIONS="systemctl --user start cornernote"
  fi
else
  mkdir -p "${AUTOSTART_DIR}"
  cat > "${AUTOSTART_DIR}/cornernote-daemon.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CornerNote daemon
Comment=Start the CornerNote quick-note overlay at login
Exec="${BIN_DIR}/cornernote-daemon"
Terminal=false
NoDisplay=true
X-KDE-StartupNotify=false
EOF
  START_INSTRUCTIONS="Log out and back in, or run ${BIN_DIR}/cornernote-daemon"
fi

echo
echo "Installed. Start it with: ${START_INSTRUCTIONS}"
echo "Bind a global shortcut in System Settings → Shortcuts → Add New → Command or URL"
echo "Command: ${BIN_DIR}/corner-note toggle"
echo "Uninstall with: ${PROJECT_DIR}/uninstall.sh"

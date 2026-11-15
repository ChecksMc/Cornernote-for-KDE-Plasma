"""Configuration loading and compact pixel-art GTK styling."""

from __future__ import annotations

import configparser
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

Config = dict[str, Any]
Palette = dict[str, str]

CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cornernote"
)
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULTS: Config = {
    "width": 380,
    "height": 340,
    "idle_fraction": 0.04,
    "margin_right": 20,
    "position_horizontal": "right",
    "position_vertical": "top",
    "offset_x": 0,
    "offset_y": 0,
    "monitor": "primary",
    "socket_path": "${XDG_RUNTIME_DIR}/cornernote.sock",
    "default_vault_path": "~/Documents",
    "note_filename": "QuickNotes.md",
    "date_format": "%Y-%m-%d",
    "font_family": "Monospace",
    "font_size": 11,
    "anim_ms": 320,
    "collapse_delay_ms": 700,
    "theme_source": "plasma",
    "theme_fallback": "catppuccin_mocha",
    "background_image": "",
    "rounded_corners": False,
    "auto_update": False,
    "custom_palette": {
        "background": "#1e1e2e",
        "foreground": "#cdd6f4",
        "accent": "#89b4fa",
        "muted": "#6c7086",
        "card": "#313244",
    },
    "folders": [],
}
PALETTE_LABELS: dict[str, str] = {
    "catppuccin_mocha": "Catppuccin Mocha",
    "catppuccin_latte": "Catppuccin Latte",
    "dracula": "Dracula",
    "gruvbox_dark": "Gruvbox Dark",
    "gruvbox_light": "Gruvbox Light",
    "nord": "Nord",
    "retro_green": "Retro Green",
    "solarized_dark": "Solarized Dark",
    "solarized_light": "Solarized Light",
    "tokyo_night": "Tokyo Night",
}
PALETTES: dict[str, Palette] = {
    "catppuccin_mocha": {
        "background": "#1e1e2e",
        "foreground": "#cdd6f4",
        "accent": "#89b4fa",
        "muted": "#6c7086",
        "card": "#313244",
    },
    "catppuccin_latte": {
        "background": "#eff1f5",
        "foreground": "#4c4f69",
        "accent": "#1e66f5",
        "muted": "#7c7f93",
        "card": "#e6e9ef",
    },
    "dracula": {
        "background": "#282a36",
        "foreground": "#f8f8f2",
        "accent": "#bd93f9",
        "muted": "#6272a4",
        "card": "#343746",
    },
    "gruvbox_dark": {
        "background": "#282828",
        "foreground": "#ebdbb2",
        "accent": "#fabd2f",
        "muted": "#928374",
        "card": "#3c3836",
    },
    "gruvbox_light": {
        "background": "#fbf1c7",
        "foreground": "#3c3836",
        "accent": "#af3a03",
        "muted": "#7c6f64",
        "card": "#f2e5bc",
    },
    "nord": {
        "background": "#2e3440",
        "foreground": "#eceff4",
        "accent": "#88c0d0",
        "muted": "#7b88a1",
        "card": "#3b4252",
    },
    "retro_green": {
        "background": "#0a0f0a",
        "foreground": "#b8ffb8",
        "accent": "#42e66c",
        "muted": "#73a17b",
        "card": "#101b12",
    },
    "solarized_dark": {
        "background": "#002b36",
        "foreground": "#eee8d5",
        "accent": "#b58900",
        "muted": "#839496",
        "card": "#073642",
    },
    "solarized_light": {
        "background": "#fdf6e3",
        "foreground": "#586e75",
        "accent": "#268bd2",
        "muted": "#839496",
        "card": "#eee8d5",
    },
    "tokyo_night": {
        "background": "#1a1b26",
        "foreground": "#c0caf5",
        "accent": "#7aa2f7",
        "muted": "#565f89",
        "card": "#24283b",
    },
}


def _expand(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if "${XDG_RUNTIME_DIR}" in value and not os.environ.get("XDG_RUNTIME_DIR"):
        value = value.replace("${XDG_RUNTIME_DIR}", f"/tmp/cornernote-{os.getuid()}")
    return os.path.expandvars(os.path.expanduser(value))


def load_config(path: str | Path | None = None) -> Config:
    config = dict(DEFAULTS)
    path = Path(path or CONFIG_PATH)
    supplied: Config = {}
    try:
        with path.open(encoding="utf-8") as stream:
            supplied = json.load(stream)
        if not isinstance(supplied, dict):
            raise ValueError("configuration root must be a JSON object")
        config.update(supplied)
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise ValueError(f"Cannot read configuration {path}: {exc}") from exc
    if "collapse_delay_ms" not in supplied and config["anim_ms"] == 140:
        config["anim_ms"] = 320
    if "position_horizontal" not in supplied and config["idle_fraction"] == 0.10:
        config["idle_fraction"] = 0.04
    config["socket_path"] = _expand(config["socket_path"])
    config["default_vault_path"] = _expand(config["default_vault_path"])
    config["background_image"] = _expand(config.get("background_image", ""))
    if not isinstance(config["background_image"], str):
        config["background_image"] = ""
    if not isinstance(config.get("rounded_corners"), bool):
        config["rounded_corners"] = False
    if not isinstance(config.get("auto_update"), bool):
        config["auto_update"] = False
    for key in ("width", "height", "font_size", "anim_ms"):
        config[key] = int(config[key])
        if config[key] <= 0:
            raise ValueError(f"{key} must be greater than zero")
    config["idle_fraction"] = min(0.5, max(0.01, float(config["idle_fraction"])))
    if config.get("position_horizontal") not in ("left", "center", "right"):
        config["position_horizontal"] = "right"
    if config.get("position_vertical") not in ("top", "center", "bottom"):
        config["position_vertical"] = "top"
    config["offset_x"] = int(config.get("offset_x", 0))
    config["offset_y"] = int(config.get("offset_y", 0))
    monitor = str(config.get("monitor", "primary")).strip()
    if monitor != "primary":
        try:
            if int(monitor) < 0:
                raise ValueError
        except ValueError:
            monitor = "primary"
    config["monitor"] = monitor
    config["collapse_delay_ms"] = max(0, int(config.get("collapse_delay_ms", 700)))
    if config.get("theme_source") not in ("plasma", "pywal", "fallback", "custom"):
        config["theme_source"] = "plasma"
    if (
        not isinstance(config.get("theme_fallback"), str)
        or config["theme_fallback"] not in PALETTES
    ):
        config["theme_fallback"] = "catppuccin_mocha"
    custom_palette = config.get("custom_palette")
    if not isinstance(custom_palette, dict) or not all(
        _valid_color(custom_palette.get(key)) for key in PALETTES["catppuccin_mocha"]
    ):
        config["custom_palette"] = dict(PALETTES["catppuccin_mocha"])
    config["folders"] = list(config.get("folders") or [])
    return config


def save_config(config: Config, path: str | Path = CONFIG_PATH) -> None:
    """Write settings atomically so a partial write cannot corrupt config.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = {key: value for key, value in config.items() if not key.startswith("_")}
    fd, temporary = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(safe, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _valid_color(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value
        except ValueError:
            return None
    return None


def _image_uri(config: Config) -> str | None:
    """Return a local image URI when the configured backdrop file exists."""
    value = config.get("background_image", "")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        path = Path(os.path.expandvars(os.path.expanduser(value.strip()))).resolve()
        return path.as_uri() if path.is_file() else None
    except (OSError, RuntimeError):
        return None


def palette_options() -> tuple[tuple[str, str], ...]:
    """Return stable IDs and display names for built-in color themes."""
    return tuple(PALETTE_LABELS.items())


def _plasma_palette() -> Palette | None:
    """Read the active Plasma color scheme from kdeglobals."""
    parser = configparser.ConfigParser(interpolation=None)
    kde_path = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kdeglobals"
    )
    try:
        parser.read(kde_path, encoding="utf-8")
        view = parser["Colors:View"]
        window = parser["Colors:Window"]

        def rgb(section: configparser.SectionProxy, key: str, fallback: str) -> str:
            parts = [int(n.strip()) for n in section.get(key, "").split(",")]
            return (
                "#%02x%02x%02x" % tuple(max(0, min(255, n)) for n in parts[:3])
                if len(parts) >= 3
                else fallback
            )

        return {
            "background": rgb(view, "BackgroundNormal", "#1e1e2e"),
            "foreground": rgb(view, "ForegroundNormal", "#cdd6f4"),
            "accent": rgb(window, "DecorationFocus", "#89b4fa"),
            "muted": rgb(view, "ForegroundInactive", "#6c7086"),
            "card": rgb(view, "BackgroundAlternate", "#313244"),
        }
    except (configparser.Error, OSError, KeyError, ValueError):
        return None


def _pywal_palette() -> Palette | None:
    wal_path = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        / "wal/colors.json"
    )
    try:
        data = json.loads(wal_path.read_text(encoding="utf-8"))
        special, colors = data.get("special", {}), data.get("colors", {})
        palette = {
            "background": special.get("background"),
            "foreground": special.get("foreground"),
            "accent": colors.get("color4"),
            "muted": colors.get("color8"),
            "card": colors.get("color0"),
        }
        if all(_valid_color(color) for color in palette.values()):
            return {key: str(color) for key, color in palette.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return None


def get_palette(config: Config) -> Palette:
    source = config.get("theme_source", "plasma")
    if source == "custom":
        custom = config.get("custom_palette", {})
        if isinstance(custom, dict) and all(
            _valid_color(custom.get(key)) for key in PALETTES["catppuccin_mocha"]
        ):
            return {key: str(custom[key]) for key in PALETTES["catppuccin_mocha"]}
        return dict(PALETTES[config.get("theme_fallback", "catppuccin_mocha")])
    order: tuple[Callable[[], Palette | None], ...] = {
        "plasma": (_plasma_palette, _pywal_palette),
        "pywal": (_pywal_palette, _plasma_palette),
        "fallback": (),
    }.get(source, (_plasma_palette, _pywal_palette))
    for loader in order:
        palette = loader()
        if palette:
            return palette
    return dict(
        PALETTES.get(config.get("theme_fallback"), PALETTES["catppuccin_mocha"])
    )


def _contrast_color(color: str, background: str) -> str:
    """Guard text legibility if a Plasma scheme provides an unusual pair."""

    def luminance(value: str) -> float:
        channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
            for c in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    try:
        a, b = luminance(color), luminance(background)
        if (max(a, b) + 0.05) / (min(a, b) + 0.05) >= 4.5:
            return color
        return "#ffffff" if b < 0.45 else "#111111"
    except (TypeError, ValueError):
        return color


def build_css(config: Config) -> str:
    palette = get_palette(config)
    palette = dict(palette)
    palette["foreground"] = _contrast_color(palette["foreground"], palette["card"])
    font = str(config.get("font_family", "Monospace"))
    font = "".join(
        character for character in font if character.isalnum() or character in " _-"
    )
    size = int(config.get("font_size", 11))
    radius = "8px" if config.get("rounded_corners", False) else "0"
    texture = (
        f"linear-gradient(45deg, alpha({palette['foreground']}, 0.025) 25%, transparent 25%, "
        f"transparent 75%, alpha({palette['foreground']}, 0.025) 75%)"
    )
    image_uri = _image_uri(config)
    images = f'{texture}, url("{image_uri}")' if image_uri else texture
    image_sizes = "auto, cover" if image_uri else "auto"
    image_repeats = "repeat, no-repeat" if image_uri else "repeat"
    image_positions = "0 0, center" if image_uri else "0 0"
    return f"""
window, .corner-note-root {{ background-color: {palette['background']}; color: {palette['foreground']};
  font-family: "{font or 'Monospace'}", monospace; font-size: {size}px; border-radius: {radius}; }}
.corner-note-root, .corner-note-root * {{ font-family: "{font or 'Monospace'}", monospace; }}
.corner-note-root {{ border: 3px solid {palette['muted']}; padding: 5px; border-radius: {radius};
  background-image: {images}; background-size: {image_sizes}; background-repeat: {image_repeats};
  background-position: {image_positions}; }}
.cn-header {{ padding: 2px 5px 5px; }}
.cn-day {{ color: {palette['accent']}; font-weight: bold; font-size: {size + 2}px; }}
.cn-date, .cn-time {{ color: {palette['muted']}; font-size: {max(8, size - 2)}px; }}
.cn-separator {{ background-color: {palette['accent']}; min-height: 2px; }}
.cn-title, .cn-date-entry, entry, entry text {{ color: {palette['foreground']}; background-color: {palette['card']}; border: 2px solid {palette['muted']}; border-radius: 0; box-shadow: none; padding: 5px; caret-color: {palette['accent']}; }}
.cn-title {{ font-weight: bold; font-size: {size + 2}px; }}
.cn-content, .cn-content text, textview, textview text {{ color: {palette['foreground']}; background-color: {palette['card']}; caret-color: {palette['accent']}; }}
.cn-folder, .cn-folder menu, .cn-folder menuitem {{ color: {palette['foreground']}; background-color: {palette['card']}; }}
.cn-save {{ background-color: {palette['accent']}; color: {palette['background']}; border: 2px solid {palette['foreground']}; border-radius: 0; font-weight: bold; }}
.cn-muted {{ color: {palette['muted']}; }}
.cn-dialog {{ background-color: {palette['card']}; border: 2px dashed {palette['accent']}; padding: 5px; }}
.cn-status {{ color: {palette['accent']}; padding: 2px 5px; }}
.cn-settings label {{ color: {palette['foreground']}; }}
"""


def build_preview_css(config: Config) -> str:
    """Build uniquely scoped styles for the standalone theme preview."""
    palette = dict(get_palette(config))
    palette["foreground"] = _contrast_color(palette["foreground"], palette["card"])
    font = str(config.get("font_family", "Monospace"))
    font = "".join(
        character for character in font if character.isalnum() or character in " _-"
    )
    size = int(config.get("font_size", 11))
    radius = "8px" if config.get("rounded_corners", False) else "0"
    image_uri = _image_uri(config)
    background = f'url("{image_uri}")' if image_uri else "none"
    return f"""
.cn-style-preview, .cn-style-preview * {{ font-family: "{font or 'Monospace'}", monospace; }}
.cn-style-preview {{ background-color: {palette['background']}; background-image: {background};
  background-size: cover; background-position: center; color: {palette['foreground']};
  font-family: "{font or 'Monospace'}", monospace; font-size: {size}px;
  border: 3px solid {palette['muted']}; border-radius: {radius}; }}
.cn-style-card {{ background-color: {palette['card']}; color: {palette['foreground']};
  border: 2px solid {palette['muted']}; border-radius: {radius}; }}
.cn-style-accent {{ color: {palette['accent']}; font-weight: bold; }}
.cn-style-apply {{ background-color: {palette['accent']}; color: {palette['background']};
  border: 2px solid {palette['foreground']}; border-radius: 0; font-weight: bold; }}
"""

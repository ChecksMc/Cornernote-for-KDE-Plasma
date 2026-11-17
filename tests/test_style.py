"""Headless tests for palette loading, button colors, stacking, and CSS."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import style


class ConfigFileTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        # Keep Plasma/Pywal lookups away from the developer's real theme.
        env = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root),
                                      "XDG_CACHE_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def load(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return style.load_config(self.path)


class ButtonColorTests(ConfigFileTestCase):
    def test_defaults_include_button_colors(self):
        config = style.load_config(self.path)
        self.assertEqual(set(config["custom_palette"]), set(style.PALETTE_KEYS))

    def test_legacy_custom_palette_is_kept_and_completed(self):
        legacy = {"background": "#000000", "foreground": "#ffffff",
                  "accent": "#ff0000", "muted": "#777777", "card": "#222222"}
        config = self.load({"custom_palette": legacy})
        palette = config["custom_palette"]
        for key, value in legacy.items():
            self.assertEqual(palette[key], value)
        self.assertEqual(palette["button"], "#222222")
        self.assertEqual(palette["button_text"], "#ffffff")

    def test_invalid_button_color_falls_back_without_losing_core_colors(self):
        custom = dict(style.PALETTES["nord"], button="red", button_text="#123456")
        palette = self.load({"custom_palette": custom})["custom_palette"]
        self.assertEqual(palette["background"], style.PALETTES["nord"]["background"])
        self.assertEqual(palette["button"], style.PALETTES["nord"]["card"])
        self.assertEqual(palette["button_text"], "#123456")

    def test_every_palette_source_returns_button_colors(self):
        for source in ("plasma", "pywal", "fallback", "custom"):
            with self.subTest(source=source):
                config = dict(style.DEFAULTS, theme_source=source)
                self.assertEqual(set(style.get_palette(config)), set(style.PALETTE_KEYS))

    def test_plasma_button_colors_come_from_kdeglobals(self):
        (self.root / "kdeglobals").write_text(
            "[Colors:View]\nBackgroundNormal=10,10,10\nForegroundNormal=240,240,240\n"
            "ForegroundInactive=128,128,128\nBackgroundAlternate=20,20,20\n"
            "[Colors:Window]\nDecorationFocus=61,174,233\n"
            "[Colors:Button]\nBackgroundNormal=49,54,59\nForegroundNormal=252,252,252\n",
            encoding="utf-8")
        palette = style.get_palette(dict(style.DEFAULTS, theme_source="plasma"))
        self.assertEqual(palette["button"], "#31363b")
        self.assertEqual(palette["button_text"], "#fcfcfc")

    def test_custom_button_colors_reach_overlay_and_preview_css(self):
        custom = dict(style.PALETTES["nord"], button="#abcdef", button_text="#010203")
        config = dict(style.DEFAULTS, theme_source="custom", custom_palette=custom)
        for css in (style.build_css(config), style.build_preview_css(config)):
            self.assertIn("#abcdef", css)
            self.assertIn("button", css)

    def test_unreadable_button_text_is_corrected(self):
        custom = dict(style.PALETTES["nord"], button="#000000", button_text="#010101")
        config = dict(style.DEFAULTS, theme_source="custom", custom_palette=custom)
        self.assertNotIn("#010101", style.build_css(config))


class LayerConfigTests(ConfigFileTestCase):
    def test_stacking_defaults_to_auto_and_rejects_unknown_values(self):
        self.assertEqual(style.load_config(self.path)["layer"], "auto")
        for value in ("auto", "overlay", "top"):
            self.assertEqual(self.load({"layer": value})["layer"], value)
        for value in ("bottom", 3, None):
            self.assertEqual(self.load({"layer": value})["layer"], "auto")

    def test_folders_ignore_non_list_values(self):
        self.assertEqual(self.load({"folders": "Work"})["folders"], [])
        self.assertEqual(self.load({"folders": ["Work", 3]})["folders"], ["Work"])


class ExampleConfigTests(unittest.TestCase):
    def test_example_config_matches_defaults(self):
        example = json.loads((Path(__file__).resolve().parents[1]
                              / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example, style.DEFAULTS)


if __name__ == "__main__":
    unittest.main()

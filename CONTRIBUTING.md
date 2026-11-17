# Contributing

Run CornerNote from a checkout in a supported Wayland session after installing
the dependencies listed in the README:

```sh
python3 src/main.py
```

Run the headless smoke tests with pytest:

```sh
python3 -m pytest tests/
```

GTK update integration tests are optional and use a separate test display.
Start GTK's Broadway backend in one terminal:

```sh
broadwayd --address=127.0.0.1 --port=8085 :5
```

Then run the GTK tests from another terminal:

```sh
GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 CORNERNOTE_GTK_TESTS=1 python3 -m pytest tests/test_gtk_ui.py
```

Alternatively, run them on a virtual X server (as CI does):

```sh
CORNERNOTE_GTK_TESTS=1 xvfb-run -a python3 -m pytest tests/test_gtk_ui.py tests/test_update_gtk.py
```

These tests replace layer-shell calls and exercise GTK sizing, formatting,
stacking, and draft interactions without connecting to the running CornerNote
daemon.

Keep `config.example.json` identical to `DEFAULTS` in `src/style.py`; a test
enforces this. Do not commit large media: keep README images small (the demo
GIF is about 480 px wide) because every clone downloads them.

The source modules are:

- `src/main.py` — GTK layer-shell overlay and daemon entry point.
- `src/state.py` — draft buffer and note interaction state machine.
- `src/obsidian.py` — Markdown path selection and append writer.
- `src/ipc.py` — GLib-integrated Unix socket server and client.
- `src/style.py` — configuration, palette loading, and GTK CSS.
- `src/settings_view.py` — settings controls, monitor choices, and vault folder picker.
- `src/style_editor.py` — appearance editor and live preview.
- `src/history.py`, `src/history_view.py` — saved-note discovery and browser.
- `src/markdown_render.py`, `src/markdown_view.py` — Markdown rendering.
- `src/updater.py`, `src/update_view.py` — Git updates and their controls.

To contribute, fork the repository, create a branch, make and test your
changes, and open a pull request against `main`. Describe the change and how
you tested it; include screenshots for visible interface changes when useful.

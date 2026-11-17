# Unreleased

## Fixed

- The note no longer opens underneath Plasma panels. A new **Stacking**
  setting (`"layer"`) defaults to raising the note above panels while it is
  open and tucking the collapsed tab behind panels and fullscreen windows;
  **Always above panels** and the previous **Below panels** behavior are also
  available.
- Buttons now follow the note's colors instead of the system GTK theme. Custom
  palettes gain **Buttons** and **Button text** colors (#12); Plasma colors use
  the scheme's button colors. Existing custom palettes are kept.
- The README demo GIF was reduced from 13 MB to under 4 MB, and the `docs/`
  folder is excluded from GitHub source archives and the release ZIP (#11).
- The installer quotes paths containing spaces, no longer changes file modes
  Git tracks (which blocked the built-in updater), and reminds you to restart
  an already-running service.

## Added

- An **Updates** settings section with manual checks and installation, plus
  opt-in automatic installation at startup and every six hours. Automatic
  updates are off by default and enabled with **Save settings**. The
  `corner-note check-update` and `corner-note update` commands also work while
  the daemon is stopped. Updates use the current Git branch's configured
  upstream, require a clean checkout, and only fast-forward. The daemon keeps
  running after installation so a draft can be saved before restarting.
- Headless updater regressions using local Git remotes and optional isolated
  GTK update tests; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Limitations

- Built-in updates require Git and a source checkout with a configured upstream;
  ZIP installations need a fresh download and reinstall. Local changes,
  untracked files, or local/divergent commits must be resolved before updating.

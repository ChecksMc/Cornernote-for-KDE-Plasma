# Unreleased

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

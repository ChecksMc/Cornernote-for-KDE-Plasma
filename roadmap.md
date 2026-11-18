# CornerNote Roadmap

This document expands the release roadmap summarized in `README.md`. It covers
the Qt migration, desktop support, note workflows, and the planned Focus mode.
Keep the release milestones and their order aligned between both documents.

## v2.0.0 — Qt and cross-desktop foundations

CornerNote currently uses GTK 3 and `gtk-layer-shell` for its KDE Plasma
Wayland overlay. The Qt port and wider desktop support are related work, but a
toolkit change alone cannot provide the same overlay behavior on every
compositor.

- Port the current KDE interface to Qt while preserving the quick-note
  workflow, keyboard controls, settings, themes, and Obsidian file behavior.
- Separate note state, persistence, configuration, and other core behavior
  from desktop-specific window management and UI code.
- Add platform integrations for overlay placement, stacking, global shortcut
  setup, startup, monitor selection, and theme or portal behavior where each
  desktop supports them.
- Publish a compatibility matrix of tested desktop and window-manager
  combinations. Maintain KDE behavior and add combinations incrementally as
  their integrations are implemented and verified.
- Keep a usable fallback where an environment lacks a layer-shell style
  overlay. Describe which behaviors the fallback supports.
- Preserve existing configuration values and migrate settings safely when
  defaults or platform-specific options change.

## v2.1.0 — Draft tabs and recovery

- Allow multiple independent note drafts and make it easy to switch between
  them in the CornerNote window.
- Keep each draft's title, content, date, folder, append mode, and other
  submission choices independent.
- Add local draft autosave and recovery so drafts survive app restarts and
  crashes. Keep recovered drafts separate from saved vault notes until the user
  explicitly submits them.
- Preserve each draft when moving between tabs, History, Settings, and Focus
  mode. Confirm before discarding a nonempty draft.
- Keep keyboard navigation consistent with the existing editor shortcuts and
  avoid requiring a new desktop-global shortcut for tab switching.

## v3.0.0 — Edit saved files from History

- Turn History from a read-only browser into a way to edit existing Markdown
  files in the configured vault.
- Provide explicit Save and Cancel actions, a visible unsaved-changes state,
  and a clear return path to the note draft and History list.
- Keep edits within the configured vault and apply the same path and symlink
  protections used by History reads.
- Detect when a file changes outside CornerNote after it was opened. Prevent a
  silent overwrite and offer a clear reload or conflict-resolution path.
- Preserve Markdown source text when switching between edit and preview.

## v3.1.0 — Autosave edited files

- Extend autosave to edits of saved vault notes after the explicit editing
  workflow from v3.0.0 is established.
- Use delayed saves so normal typing does not write on every keystroke.
- Write safely and atomically where possible, and retain external-change
  detection so autosave cannot silently replace newer edits from another app.
- Make save state visible and provide recovery for interrupted or failed saves.
- Keep autosave preferences separate from the explicit Submit behavior used
  for quick notes.

## v4.0.0 — Optional Focus mode

Focus mode is a compact workspace for a focus/break timer, a lightweight task
list, and a calendar view for dated tasks. It should complement CornerNote's
quick-note workflow and remain optional.

### Screen and navigation

- Add a Focus page within the existing CornerNote window; keep one app window
  and preserve the quick-note editor as a separate page.
- Provide clear Note, Focus, and History navigation. Switching pages preserves
  note drafts, task state, and the running timer.
- Put the current phase and large countdown at the top, with the focus topic,
  tasks, duration presets, timer controls, and compact calendar or agenda below.
- Reuse the user's theme, font, sizing, and monitor settings. Design for the
  supported desktop matrix instead of fixed screen coordinates or dimensions.
- Keep the timer running when the user switches pages or collapses the overlay.
  Define Focus-session recovery separately from draft autosave: persist the
  active phase and deadline, then offer a clear resume, pause, or reset choice
  when CornerNote restarts.

### Timer behavior

- Support focus, short break, long break, paused, ready, and idle states.
  Track completed focus cycles and offer a long break after a configurable
  number of cycles.
- Include common presets such as 25/5, 45/10, and 50/10, plus custom durations.
  Support start, pause/resume, skip, reset, and a focus-topic label.
- Calculate remaining time from a deadline so display refreshes do not
  accumulate drift. Run a recurring UI update only while a countdown is active;
  idle and paused states need no recurring timer.
- Leave automatic start of the next phase off by default.
- On phase completion, use the standard desktop notification path and optionally
  play a configurable sound. Let users turn notifications and sound off
  independently where supported.
- Show a compact timer indicator outside the Focus page where the target UI and
  compositor support it without changing the existing collapsed-overlay
  behavior.

### Tasks and calendar

- Provide a lightweight task list with completion state and optional due dates.
  Let the user select one task or topic for the current focus session.
- Add a compact month or date navigator and show the tasks due on the selected
  day. Keep this as an agenda aid rather than a full calendar or event-sync
  client.
- Store CornerNote-managed tasks in CornerNote's own user data. Offer an
  optional read-only import from a user-selected Markdown checklist in the
  configured vault. Parse open `- [ ]` items and useful headings or due dates;
  never modify an imported task file.
- Keep import optional so the task list and timer work without an Obsidian vault
  or Markdown source. Missing or unreadable task sources must not block the
  timer or local task list.

### Settings and desktop behavior

- Add backward-compatible settings for focus and break lengths, long-break
  cycle count, task source, sound and notification preferences, and the compact
  timer indicator.
- Keep task and timer state independent of the UI toolkit and desktop backend.
  Unsupported overlay or notification features should not disable the timer or
  local task list.
- Defer keep-awake support until the platform integrations expose a reliable
  capability. Make it opt-in and release any inhibition on pause, break, reset,
  app shutdown, or loss of the owning session.
- Do not require desktop-specific shell commands, status-bar signals, or
  unrelated user services for the core Focus mode.

## v4.1.0 — Focus integrations and polish

- Add optional Focus controls through CornerNote's existing local IPC: status,
  start, pause or resume, skip, and reset. Keep `corner-note toggle` working as
  it does today.
- Add opt-in keep-awake behavior through a platform backend where supported,
  and clearly show when the request is unavailable.
- Refine task import, date navigation, completion notifications, and the
  compact timer indicator based on use across the supported desktop matrix.

## Compatibility principles

- Treat the compatibility matrix as a list of tested combinations, not a claim
  that a toolkit works identically on every desktop or window manager.
- Keep the core timer, task list, and note state independent of desktop-only
  capabilities.
- Preserve existing settings and note data during migrations, and keep optional
  integrations disabled until the user enables them.

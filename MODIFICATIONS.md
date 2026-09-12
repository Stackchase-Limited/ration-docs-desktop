# Stackchase Modifications

## Baseline

Ration Docs Desktop is based on ONLYOFFICE Desktop Editors 9.4.0.

Ration Docs is an independent downstream fork. Fixes land in this tree and are
not submitted upstream. Upstream issue numbers are cited where a change was
prompted by a public ONLYOFFICE report, but the code is ours.

## Modifications

### Branding and versioning (`desktop-apps`)

- Ration Docs document icon set replaces the ONLYOFFICE icons, including the
  OpenDocument Drawing icon.
- About box corrected for Ration Docs copyright, licence and branding, and the
  licence page it opens is now tracked.
- Calendar-scheme version numbering, with the build number shown in About.

### Localization and spell-check (`core`, `sdkjs`, `dictionaries`)

- `yo_NG`, `ig_NG` and `ha_Latn_NG` registered for spell-check in both the C++
  core and the sdkjs language map.
- Affix files and a wordlist builder added for those three languages, with
  wordlists built from open corpora.
- Combining-mark input accepted, not only precomposed spellings.
- English words that had leaked into the Yoruba wordlist removed.

### Stability: crash and data-loss fixes

- **Local save never reports success when the write failed** (`desktop-sdk`).
  `CASCFileConverterFromEditor::ThreadProc()` discarded the result of
  `CLocalFileLocker::SaveFile()`, so a refused write - stale `.~lock` held by
  another process, read-only target, I/O error - was reported as a completed
  save. The temp file was then deleted and sdkjs marked the document clean, so
  the edits were gone with no error shown anywhere. The failure is now
  propagated, the target is left untouched when x2t has already failed, and
  `StartWrite()` is checked so a 0-byte write to an unopenable file is no longer
  counted as a save. Upstream: #2081, #2417, and the mechanism behind #1436.

- **A failing conditional formatting rule no longer disables editing**
  (`sdkjs`). Rule evaluation runs in the style/render path, so an exception
  escaped to `window.onerror`, which reports `EditingError` and forces view
  mode - leaving the document uneditable rather than merely unformatted. A
  throwing rule now degrades to "no formatting" and is logged once per rule.
  Containment only; the underlying exception in upstream #2418 is still
  unidentified.

- **Home key in wrapped cell text** (`sdkjs`). Soft-wrapped lines share a
  character index, and `kBeginOfLine` did not disambiguate it, so Home moved the
  caret to the end of the previous visual line. Upstream: #2082.

## Modification history

- 2026-09-03: Stackchase fork established from ONLYOFFICE Desktop Editors 9.4.0.
- 2026-09-04: macOS build fixes (Homebrew Qt deployment path, qmake version query).
- 2026-09-09: Yoruba, Igbo and Hausa spell-check support added.
- 2026-09-11: Branding, About box and calendar versioning; Yoruba wordlist fixes;
  submodule checkouts pinned.
- 2026-09-12: Stability round - silent local-save failure, conditional
  formatting crash containment, Home key in wrapped cells.

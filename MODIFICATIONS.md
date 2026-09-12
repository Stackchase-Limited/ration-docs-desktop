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
- **Every Spanish locale now reaches the `es_ES` dictionary** (`dictionaries`,
  `core`, `sdkjs`). Only `es-ES` (3082) was mapped, so text tagged Spanish
  (Mexico), (Colombia), (Argentina) and 17 others was never checked at all. A
  locale has to appear in three places to work - the `codes` array in
  `dictionaries/<name>/<name>.json`, the `records.h` generated from it by
  `core/Common/3dParty/hunspell/autogen/generate.py` (the table
  `CSpellChecker::SetLanguage()` keys on), and the hand-maintained
  `spellcheckGetLanguages()` in `sdkjs` - and all three were updated together,
  68 entries to 89. `ru-MO` (2073) was unmapped the same way. Upstream: #459.

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
  The underlying exception in #2418 was subsequently found and fixed too: the
  `Asc.ECfType.expression` branch built its formula parent inside a nested
  function invoked bare, so under `"use strict"` `this` was `undefined` and the
  parent carried no worksheet. The containment does not cover that path - the
  throw is on the dependency-graph notify path inside `calcTree`, outside the
  wrapped style evaluation - and was kept for the path it does guard.
  Upstream: #2418.

- **Home key in wrapped cell text** (`sdkjs`). Soft-wrapped lines share a
  character index, and `kBeginOfLine` did not disambiguate it, so Home moved the
  caret to the end of the previous visual line. Upstream: #2082.

- **Saving with a cell still in edit mode no longer discards the edit**
  (`sdkjs`). `asc_Save` asked whether the document needed saving *before*
  calling `_prepareSave`, which is what closes the cell editor - and the text in
  that editor only becomes a history change when it closes. On an otherwise
  unmodified workbook the test therefore saw no changes, abandoned the save, and
  left the typed value uncommitted, with no error. The close now happens before
  the test. Upstream: #963.

- **A chosen print range of "Active sheets" is no longer discarded** (`sdkjs`).
  `Asc.c_oAscPrintType.ActiveSheets` is `0`, and the print options were read
  under `if (_options["adjustOptions"]["printType"])`, so the chosen range was
  indistinguishable from "not supplied" and silently became Entire workbook.
  `startPageIndex`/`endPageIndex` had the same hazard, page 0 being the first
  page. Upstream: #1333, #1016, #1641.

- **An inserted video keeps its own size** (`sdkjs`). `addMediaCallback`
  discarded the poster frame's real dimensions and hardcoded 50x50 pixels, so
  every video and audio insert became a 50x50 box. Upstream: #2310, #1509.

- **Save As works again on KDE with the desktop portal** (`desktop-apps`). A format
  id with no entry in the file dialog's filter map produced an empty filter name -
  `QMap::value()` returns an empty `QString` for a missing key, silently - and
  xdg-desktop-portal refuses the entire request when it sees one, so no dialog
  appeared and the document could not be saved. Unmapped ids are now skipped, and
  nameless filters are dropped at the portal boundary so no future producer can
  break the dialog the same way. Two use-after-frees in the same code were fixed
  alongside: the filter pattern and the parent window handle were both read from a
  `QByteArray` temporary that had already been freed. Upstream: #2243.

- **A password-protected workbook behind an external reference can now be read**
  (`desktop-sdk` + `sdkjs`). A formula referencing an encrypted workbook showed
  `#REF!` and nothing ever asked for a password. `CConvertFileInEditor` now has an
  `m_sPassword` and emits `<m_sPassword>`, which x2t has always parsed;
  `on_convert_local_file` carries x2t's exit code through to the JS callback, so
  `ExternalDataLoader.js` can finally tell an encrypted file from a missing one
  rather than mapping both to `#REF!`; and `convertFile` takes a password. On exit
  code 90 or 91 the reference is retried once with the password the user already
  gave for this document, which covers the common case of a workbook and its
  reference sharing a password. Prompting for a password specific to the reference
  still needs a `web-apps` dialog. Upstream: #2252.

- **Copying a sheet to a new file copies that sheet, not the whole workbook**
  (`desktop-sdk`). The selected-sheets binary `sdkjs` hands to
  `AscDesktopEditor.OpenWorkbook` was written to disk only when
  `m_sCryptDocumentFolder` was set, which happens only for a cloud-crypto
  document. For an ordinary local file the write was skipped in silence and the
  new tab opened the source document's own `Editor.bin` - the entire original
  workbook. The binding now falls back to `m_sLocalFileFolderWithoutFile`, the
  same recovery directory the browser side copies, and refuses to ask for the new
  tab at all if it has nowhere to write. `OpenCopyAsRecoverFile` no longer falls
  through to that binary during a compare or merge, so a leftover from an earlier
  copy cannot be compared against by mistake. Upstream: #2278.

- **The keyboard layout's LANGID is validated before it becomes the text
  language** (`sdkjs`). The desktop shell reports the OS keyboard layout's LANGID
  and the editors adopted it verbatim, so a custom MSKLC layout - or one like
  "Russian (Ukraine)" that has no LCID of its own - set the text language to
  0x2000 (8192), whose primary-language field is `LANG_NEUTRAL`. No dictionary
  can match that, so spell check silently stopped. `asc_getKeyboardLanguage` now
  passes the value through `AscCommon.checkKeyboardLanguageId`, which accepts
  only a LANGID known to the LCID name table or the installed dictionary map and
  returns `-1` otherwise - the value callers already read as "no keyboard
  language", leaving the document's own language in place. Upstream: #1179, #402.

- **macOS Control+click opens the context menu** (`sdkjs`). The editors suppress
  the DOM `contextmenu` event and raise their own menu from `Button === 2`, but
  `getMouseButton` returned the raw `e.button`, so the macOS secondary-click
  gesture arrived as a left click - and with Control still reported as a held
  modifier, it altered the selection instead. Normalised in `getMouseButton`,
  narrowly: macOS only, and `ctrlKey` without `metaKey`, so Cmd+click and
  Ctrl+click on other platforms are unchanged. Upstream: #2262.

## Modification history

- 2026-09-03: Stackchase fork established from ONLYOFFICE Desktop Editors 9.4.0.
- 2026-09-04: macOS build fixes (Homebrew Qt deployment path, qmake version query).
- 2026-09-09: Yoruba, Igbo and Hausa spell-check support added.
- 2026-09-11: Branding, About box and calendar versioning; Yoruba wordlist fixes;
  submodule checkouts pinned.
- 2026-09-12: Stability round - silent local-save failure, conditional
  formatting crash containment, Home key in wrapped cells.
- 2026-09-12: Second stability round - save with a cell in edit mode, print
  range falsy-zero, inserted video size, Spanish spell-check locales, macOS
  Control+click. 8 upstream issues from 5 fixes; see `UPSTREAM_TRIAGE.md`.
- 2026-09-12: Keyboard-layout LANGID validated before it is adopted as the text
  language (#1179, #402).
- 2026-09-12: Copy-sheet-to-new-file writes its binary for local documents, not
  only cloud-crypto ones (#2278).
- 2026-09-12: Password and converter error code plumbed between the editor and
  x2t, so an encrypted external reference can be read (#2252, partial).
- 2026-09-12: Save As fixed on the KDE desktop portal, plus two use-after-frees in
  the file dialog (#2243).
- 2026-09-12: Help images stored once instead of once per language; desktop payload
  1.8G -> 1.5G.

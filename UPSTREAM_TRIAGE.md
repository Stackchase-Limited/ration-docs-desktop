# Upstream issue triage

Working notes on issues from the ONLYOFFICE Desktop Editors tracker
(<https://github.com/ONLYOFFICE/DesktopEditors/issues?q=is%3Aissue+state%3Aopen+label%3Aconfirmed-bug>),
used as a bug source for this fork. See `UPSTREAM.md` for provenance and
`MODIFICATIONS.md` for what we have changed.

**The point of this file is to make an issue resumable.** Every entry that is
not fixed records what was already examined, what was ruled out, and the next
concrete step, so nobody re-derives it from scratch.

## The verification standard

A fix is not considered done until a test proves it, and proves it *detects the
bug*:

1. Extract the real function(s) from the source by brace-matching and run them
   against stubs - Node for JS, `clang++` for C++, real QtCore for Qt code
   (Qt5 is at `/opt/homebrew/opt/qt@5`).
2. Run the same test against the unpatched baseline (`git show HEAD:<path>`)
   and confirm it **fails** there. A test that passes before and after proves
   nothing.

Tests live in `../fork-fix-tests/`. Worked examples:
`issue-2398-ctrl-home-frozen-test.js` (JS), `issue-2081-2417-save-path/` (plain
C++), `issue-2429-saveas-extension/` (real QtCore).

## Fixed

| Issue | What it was | Where |
|---|---|---|
| #2082 | Home key put the caret on the previous visual line in wrapped cell text | `sdkjs` |
| #2398 | Ctrl+Home selected A1 but did not scroll when panes were frozen | `sdkjs` |
| #2256 | `HYPERLINK()` cells lost their link when copied to another application | `sdkjs` |
| #2081 | Local save reported success when the write had failed - silent data loss | `desktop-sdk` |
| #1720 | File names were interpreted as HTML in the recent-files list (injection) | `desktop-apps` |
| #1669 | An invalid user name silently discarded every other settings change | `desktop-apps` |
| #2429 | Save As PDF kept the `.pptx` name and the write destroyed the original | `desktop-apps` |
| #2129 | "Install plugin manually" opened the marketplace page instead of a picker | `onlyoffice.github.io` |
| #1482 | DATE fields never refreshed on open; auto date/time mixed local date with UTC hour | `sdkjs` |
| #1948 | A custom theme's colours lost to the built-in palette on specificity and source order | `web-apps` |
| #2222 | A `+` in the install path decoded to a space, so the font wasm never loaded | `desktop-sdk` |
| #2266 | GTK dialogs were never told the app's theme, so Save As stayed light | `desktop-apps` |
| #1839 | Exporting the focused sheet to CSV exported whatever sheet was active at open | `core` + `sdkjs` |
| #2418 | A formula-based conditional format rule made the spreadsheet uneditable | `sdkjs` |
| #2155 | A leaked non-Unicode charmap turned accented characters into other glyphs | `core`, native consumers only |
| #1868 | A spreadsheet reopened at A1 instead of where the user left it (scroll only) | `core` + `sdkjs` |

Two defects in our own tooling were fixed alongside: CEF remote debugging was
pinned to a hardcoded port 8080 that could not be overridden, and CEF failures
were silenced by `LOGSEVERITY_DISABLE` (both `desktop-sdk`).

## Root-caused, not fixed

### #1868 - scroll position fixed; the caret still needs a format change

The scroll half is fixed, through the same save-parameter channel #1839 built:
`getAdditionalSaveParams()` ships each sheet's live top-left visible cell as
`topLeftCells` (`"<sheet index>:<A1-ref>"` pairs), x2t lifts it out of
`<m_sJsonParams>` into `fileOptions/@topLeftCells`, and it is applied to each
worksheet's `sheetViews` as `BinaryWorksheetsTableReader::ReadWorksheet` writes
it out. No new bin record, no `Serialize.js` change - the override mutates the
already-parsed in-memory `CSheetView` between reading the bin and writing the
XML, so the **binary format is unchanged**.

Observed end to end: the reporter's case, nothing stored and the user at A1000,
went from `<sheetView workbookViewId="0"/>` to
`<sheetView topLeftCell="A1000" workbookViewId="0"/>`. A stale stored A1000/C50
with the user at A500/B7 now writes A500/B7, and scrolling back to the top
clears the attribute, which is how OOXML spells A1.

**Still open: the caret.** `asc_CSheetViewSettings` has no selection or
active-cell field, and `WriteSheetView` (`sdkjs/cell/model/Serialize.js:5917`)
writes `topLeftCell`, `pane`, zoom and flags only, so the active cell cannot
round-trip without a new field in the bin format plus serializer and reader
changes on both sides. That was deliberately left out of scope.

**Refinement to an earlier claim here.** This file said the only writers of the
model's `topLeftCell` were `Workbook.js:13562`, undo/redo and
`executeWithCurrentTopLeftCell`. That understates it by one caller:
`CHistory.EndTransaction` (`sdkjs/cell/model/History.js:1425`) calls
`wsView.updateTopLeftCell()` with history, so a scroll position *can* reach the
change stream - but only for whichever sheet is active when an edit transaction
ends. A pure scroll with no edit, and any sheet the user merely scrolled, still
recorded nothing, so the conclusion and the fix were unaffected.

### #2418 - resolved, plus a correction about the containment

Fixed. `Workbook.js` is `"use strict"`, and the `Asc.ECfType.expression` branch
of `_updateConditionalFormatting` built its
`CConditionalFormattingFormulaParent` inside a nested `doExpression` invoked
bare, so `this` was `undefined` and the parent carried no worksheet. Editing a
referenced cell then reached `onFormulaEvent`, whose `Change` case calls
`this.ws.setDirtyConditionalFormatting(...)`, and threw. Uncaught that becomes
`EditingError`, and the global handler calls `asc_setViewMode(true)` - the
document going read-only. Every sibling branch builds the same parent from the
method body where `this` is the worksheet, which is why only formula-based rules
broke.

**Correction.** This file previously said the `getSafeCompareFunction` wrapper
meant a throwing rule could no longer disable editing. That was wrong for this
issue: the wrapper guards the style-evaluation path handed to
`setConditionalStyle`, while this exception is raised on the dependency-graph
notify path inside `calcTree`, entirely outside it. The containment never
intercepted this bug. It still guards its own path and was kept.

The stack came from driving a packaged app over CDP with
`harness/repros/2418-conditional-formatting.js` - the first thing that route
has paid for.

### #2155 - fixed for native consumers, still open on the editor canvas

The symptom reading was right - `ü` renders as `¸` (MacRoman 0xFC) and `ß` as the
`fl` ligature (MacRoman 0xDF), so glyphs resolve through a non-Unicode charmap -
but **an earlier version of this file named the wrong function.**

- `CFontFile::SetCMapForCharCode` is benign for Arial, whose charmaps are
  `(0,3) (1,0) (3,1)`, so its loop ends on a Unicode one.
- The real leak is our own harfbuzz patch,
  `core/Common/3dParty/harfbuzz/patch/hb-ft.cc.patch`:
  `hb_ft_get_index_by_unicode` restores the entry charmap only on failure and
  returns without restoring on success. `hb_ft_get_nominal_glyph` resolves code
  points against whichever charmap is selected and only falls back when it
  misses - and **a tab or a newline is enough**, because Arial maps neither in
  its Unicode cmaps but does in `(1,0)`. One tab poisons the cached face for the
  rest of the process: hence "persists until I restart", and hence intermittent.
- Measured against real Arial with real FreeType: `U+00FC` is Unicode GID 129
  but MacRoman GID 220, and `U+00B8` is also 220; `U+00DF` is 137 versus 192,
  and `U+FB02` is 192. After one tab lookup `Begrüßung` shapes to
  `Begr¸ﬂung`, character for character as reported.
- Fixed at all three leaking sites: the harfbuzz patch,
  `DesktopEditor/fontengine/TextShaper.cpp` and
  `DesktopEditor/fontengine/FontFile.cpp` (the latter two do leak for fonts
  listing a non-Unicode cmap last, e.g. `core-fonts/fonts-beng-extra/ani.ttf`).

**Still outstanding.** The editor is a CEF page and loads the font engine as a
**prebuilt `sdkjs/common/libfont/engine/fonts.wasm` checked into `sdkjs`**.
There is no emscripten here and no wasm recipe anywhere in `build_tools`. So
x2t, doctrenderer, PDF and image export and thumbnails are fixed, and **the
editor's own canvas still has this bug until that wasm is rebuilt from these
sources.** Establishing a `fonts.wasm` build is the next step. A JS-only
mitigation (re-probing a Unicode charmap after each shape) was considered and
not shipped: it cannot repair corruption inside a string that contains the
poisoning character.

Note also that `Common/3dParty/harfbuzz/make.py` applies the patch **only on a
fresh clone**, so an existing gitignored `harfbuzz/` checkout does not pick it
up; the local checkout was edited to match.

## Already fixed in our 9.4 baseline - no action

### #1690 - German `ZELLE` gives `#VALUE!` in PDF export
The plumbing exists and is used. `sdkjs/cell/api.js:7061` puts
`AscCommon.cCellFunctionLocal` into the print options as
`spreadsheetLayout.formulaProps.cellFunctionTypeTranslate`; `cCell.Calculate`
reads it with a fallback to the editor locale
(`cell/model/FormulaObjects/informationFunctions.js:224-228`). Both sides
lower-case consistently - the argument at `:198`, the map in
`common/editorscommon.js:1629` onwards. Reported against 8.1.1.

### #1375 - tracked changes accepted when saving in preview mode
Preview really does mutate the document - `CDocument.BeginViewModeInReview`
(`sdkjs/word/Editor/Document.js:23411`) calls `AcceptAllRevisionChanges` and
relies on `Document_Undo()` to put it back - but three guards now stand in the
way of saving that state: `History.Have_Changes` returns false in view mode
(`word/Editor/History.js:898`), `_saveCheck` excludes it (`word/api.js:2842`),
and `getFileAsFromChanges` exits and re-enters preview around serialization
(`common/apiBase.js:4946`). Reported against 7.4.1.

### #1596 - the window has no minimum size

Fixed upstream by `400efc872` ("[win-linux] fix bug 58444", Nov 2024), which is
in our tree and is later than the reporter's 8.0.1.31 - and 58444 is the
internal number the maintainer cited on the issue.
`desktop-apps/win-linux/src/windows/cwindowbase.h:39-40` now defines 520x480,
applied unconditionally in the `CWindowBase` constructor
(`cwindowbase.cpp:80`) and re-applied on DPI change (`cwindowbase.cpp:248`,
which used to be the `setMinimumSize(0,0)` that caused the bug). Escape hatches
were checked: nothing under `windows/platform_linux/` calls `setMinimumSize` or
`setFixedSize`, the only reset is `platform_win/cwindowplatform.cpp:425` on
`WM_DPICHANGED` and it is restored at `:432`, and both Linux decoration modes
honour Qt's `WM_NORMAL_HINTS`. macOS carries its own 518x440 in
`macos/ONLYOFFICE/Base.lproj/Main.storyboard:717`.
If anyone still reproduces it, suspect Wayland client-side decorations: check
`QMainWindow::minimumSize()` at runtime there and set it on the `QWindow` too.

## Deliberate behaviour - product decision, not a defect

### #1568 - highlight and font colour not captured by "update style"
Highlight is stripped on purpose. `Paragraph.prototype.GetStyleFromFormatting`
(`sdkjs/word/Editor/Paragraph.js:15732`) clears `TextPr.HighLight` with the
comment *"В стиль не добавляется HighLight"*. Font colour **is** captured, via
`fill_TextPr` at `:15781` and `:15785`. Diverging from upstream for Word parity
is a call for us to make; the reporter's expectation matches Word.

### #1501 - time formats: durations over 9999 hours, negative times

Three complaints, none of them a defect against Excel.

- **`#VALUE!` above 9999 hours is an entry limit, and Excel's is the same
  (9999:59:59).** `NumFormat.parseDate`'s tokenizer caps a numeric run at four
  digits - `digit: {id: 1, min: 1, max: 4}` at `common/NumFormat.js:4634` - so a
  five-digit hour fails to parse and the entry is stored as text; the reporter's
  own file confirms it, with the offending cells held as shared **strings**, so
  `A1+A2` is text arithmetic. Display of long durations is already fine
  (`[h]:mm:ss` on 20833.33 gives `500000:00:00`). Widening `digit.max` would also
  change date/year token parsing.
- **Negative time rendering as `######` is deliberate.**
  `NumFormat.isInvalidDateValue` (`common/NumFormat.js:2021-2023`) rejects
  negative serials outside the 1904 date system and `format()` emits a repeated
  `#` (`:2126-2132`). Excel behaves identically; LibreOffice is the divergence.
- **The formula bar showing a date-time is not a bug** - Excel shows the same
  underlying value there, and the reporter accepted this and reclassified it.
- **Next step, only if we choose to diverge from Excel:** a time-specific parse
  branch allowing >4-digit hours when the token is followed by a time separator
  and no date component is present (not a change to `digit.max`), plus signed
  date/time formatting and a decision about round-tripping negative serials,
  which Excel cannot read.

## Feature requests, not defects

### #1959 - MyAnimeList XML opens in the document editor
Not a detection bug. The files' root element is `<myanimelist>`.
`core/Common/OfficeFileFormatChecker2.cpp:1683-1700` recognises Word 2003
WordML, SpreadsheetML (`xmlns:ss`), flat ODF, Office packages and HTML, and
anything else falls back to `AVS_OFFICESTUDIO_FILE_DOCUMENT_XML` at `:150` by
design. What is being asked for is arbitrary-XML import into the grid, as
Excel's XML import does - a sizeable feature. Repro files are attached to the
issue.

### #1465 - changing font size does not change indents

The reporter wants a first-line indent expressed **in characters** (the CJK
"indent 2 characters" convention) so it tracks font size; ONLYOFFICE confirmed
on the thread that this is not implemented yet. `CParaInd`
(`sdkjs/word/Editor/Styles.js:15599-15604`) has only absolute `Left`, `Right`
and `FirstLine` in mm, and the ECMA-376 `w:firstLineChars` / `w:leftChars` /
`w:rightChars` attributes appear **nowhere** in `sdkjs`. Not a recalculation
bug: `Ind.FirstLine` is applied correctly at every recalc site, the value simply
has no font-relative unit. A fix spans core/x2t round-trip, a new `CParaInd`
field with history serialization, recalc, and a unit selector in `web-apps`.

### #1857 - Windows High Contrast: text unreadable in spreadsheet

Never implemented rather than broken: `forced-color-adjust`,
`-ms-high-contrast`, `prefers-contrast` and `forced-colors` appear **nowhere**
in `web-apps/apps`. The grid is a canvas painted by sdkjs from the skin
web-apps supplies, and that skin is built purely from CSS custom properties
(`apps/common/main/lib/controller/Themes.js:194`, token list at `:667`), which
Chromium's forced-colors mode does not rewrite - so the reported behaviour
cannot originate in the theme plumbing. Upstream classes it as an improvement
(their bugs 62092, 73934). Adding `forced-color-adjust: none` was considered and
rejected: it would make the UI ignore high contrast, the opposite of the ask.
Resuming means sdkjs sourcing default cell fill and automatic text colour from
the skin, plus a desktop launch-flag decision, before web-apps needs a
`forced-colors` palette at all.

### #1617 - some XLS files open as Word documents
Almost certainly the same content-sniffing-by-design behaviour: Excel itself
warns that the format and extension do not match, so the file is not really an
xls. The reporter's actual ask is an override - "open this in Spreadsheet
anyway". Not investigated in depth.

## Not reproducible or not testable here

### #2417 - macOS: hours of work lost, silently, document left clean
The **silent** half is fixed: a failed write is now reported and the document
stays dirty (#2081). The underlying write failure is still unexplained, and the
reporter could not reproduce it on demand either. Note that on macOS
`CFileLocker::Lock` treats `EACCES`/`EAGAIN` as success
(`desktop-sdk/ChromiumBasedEditors/lib/src/filelocker.cpp:637-640`) and fcntl
locks are advisory, so another process holding a lock does **not** refuse a
write there - a stale `.~lock` will not reproduce it on macOS. The refused-write
path is the Linux GIO one (`g_file_replace`).

### #1436 - files not saving on a Synology NAS
Same family as #2081/#2417 and plausibly the same mechanism, but never verified
against this report specifically. Do not claim it as fixed.

### #2080 - spell check inactive when language detection is automatic
Linux/XKB territory, not testable from macOS. The setting is
`spell-check-input-mode`, read into `m_bIsUseSpellCheckKeyboardInput` in
`desktop-sdk/ChromiumBasedEditors/lib/src/applicationmanager_p.h:2024-2028` and
applied at `:2059` via `m_oKeyboardChecker.SetEnabled`. Next step: look at how
the keyboard checker detects the layout on Linux, especially under Wayland,
and what language it reports when detection fails.

### #1672 - saving a pptx as PDF includes hidden slides
Not localised. The slide visibility flag exists as `nullable_bool show` in
`core/OOXML/PPTXFormat/Slide.h:89`. `sdkjs/slide/api.js:7551` does filter on
`show`, but that is `StartDemonstrationFromBeginning` - the slideshow, not
export. Next step: trace `show` through the binary presentation format into the
PDF writer, and check whether the editor's export path filters slides at all.

### #1641 - cannot export a selected spreadsheet range to PDF

The `web-apps` half is correct in our baseline. Running the real
`resultPrintSettings` and `querySavePrintSettings` against stubs shows all three
range choices propagating on both the print and the PDF path: Active sheets
gives `printType=0, activeSheetsArray=[1]`, Entire workbook `printType=1, null`,
Selection `printType=2, [1]`. Examined
`apps/spreadsheeteditor/main/app/controller/Print.js:175, 298-320, 435, 479, 540`,
`view/PrintSettings.js:90-103, 324-330`, `controller/LeftMenu.js:375-421`
(PDF always routes through the download-settings dialog), and ruled out a
falsy-zero hazard in `ComboBox.js:712-748`. The consumer side also branches
correctly at `sdkjs/cell/view/WorkbookView.js:4173-4199`.
**Next step:** instrument `sdkjs/cell/api.js` `asc_DownloadAs` for
`c_oAscFileType.PDF` in a built app to confirm `calcPagesPrint` is reached with
`adjustPrint`, and check the desktop-local route at
`sdkjs/cell/Local/api.js:291`. This is an sdkjs question, not a web-apps one.

### #1916 - the menu in the formula bar is not scaled

Not a web-apps defect. The screenshot shows Cut/Copy/Paste/Select all in
English inside an otherwise Russian, 200%-scaled UI: it is the **native CEF
context menu**, not a `Common.UI.Menu`. The formula bar is a real `<textarea>`
(`apps/spreadsheeteditor/main/app/template/CellEditor.template:10`) and
`controller/Main.js:3250` deliberately lets the native menu through for inputs
and textareas unless `data-can-copy="false"`, because JS cannot offer Paste;
the same code exists in all four editors and `ComboBox.js:217` /
`InputField.js:286,289` actively manage that attribute. Suppressing it would
remove Paste from every text field.
**Next step:** desktop-sdk. No `CefContextMenuHandler` override exists, so
either implement `OnBeforeContextMenu`/`RunContextMenu` to draw a Qt menu at the
app's scale, or make the browser's device-scale-factor apply to native menus.

### #2031 - the Windows installer ignores the file-association selection

Root-caused in both packages; **no patch**, because neither installer language
can be executed here (no Inno compiler, no Free Pascal, no Advanced Installer,
no Windows, no registry) and Inno's Pascal Script dialect cannot be faithfully
re-hosted - a harness would test a translation rather than the shipped script.

**Correction to earlier notes:** these are not NSIS or WiX, and not under
`win-linux/extras/`. The EXE is **Inno Setup** (`desktop-apps/package/inno/`,
`common.iss` + `_code.iss`) and the MSI is an **Advanced Installer** project
(`desktop-apps/package/advinst/DesktopEditors.aip`). `win-linux/extras/` holds
only `projicons/` and `update-daemon/`.

- **Inno, the decisive defect.** The guard is fine and exists -
  `isAssociateExtension` at `inno/_code.iss:380-387` - but it is consulted at
  exactly one site, `:517`. `DoPostInstall` then calls `AddContextMenuNewItems`
  unconditionally at `:556`, and that procedure's Windows 10/11 branch
  (`:473-477`) writes the **default ProgID** for `.docx`, `.pptx`, `.xlsx` and
  `.pdf` with no reference to the user's choice - exactly the four the reporter
  sees. It also lacks the existing-owner check the gated path has at `:519`,
  which is why PDF ownership is taken from whatever held it.
  The write is not simply deletable: Explorer only shows the New-menu entry
  while `.docx`'s default ProgID is ours (`ShellNew` at `:465-472`), so it must
  be **gated**, not removed. `isAssociateExtension` takes an index into
  `AudioExts` (`:178-256`), so gating needs a small by-extension wrapper.
- **MSI, dead gating for two independent reasons.** Per-extension checkboxes
  bind to `REGISTER_<EXT>` (`:792-936`) feeding the Condition table
  (`:671-732`) against feature levels (`:419-483`). But `INSTALLLEVEL` is never
  authored anywhere, so Advanced Installer's default of 100 makes every
  `Level=4`/`Level=1` feature install regardless; and the dialog never
  re-costs - the Next button fires only `NewDialog` (`:977`), no
  `SetInstallLevel`. So the UI is cosmetic. `REGISTER_*`, `REGISTER_NONE` and
  `NOASSOCHECK` are also missing from `SecureCustomProperties` (`:53`), so they
  do not reach a silent install's server-side sequence. Compare
  `REGISTER_PROTOCOL` (`:412`), which is enforced as a component-level
  `Condition` and therefore does work - that asymmetry is the whole story.
- **`NOASSOCHECK` is unrelated to associations** in both packages: it only
  suppresses the runtime nag (`_code.iss:984-986`; MSI component at `:414`).
  `REGISTER_NONE` exists only in the dead MSI condition at `:673`; the Inno tree
  has no `REGISTER_*` at all.
- **A runtime path must be fixed alongside it.**
  `win-linux/src/platform_win/association.cpp:159-181` seeds its extension map
  by enumerating `HKLM\...\Capabilities\FileAssociations` - every extension,
  regardless of what was chosen at install - then offers to claim each one
  (`:210-232`). So even a corrected installer would re-offer everything on first
  launch. Record the install-time selection in its own key and read that.
- **Next steps, in order.** (1) Gate `_code.iss:473-477` and add an owner check.
  (2) Give Inno a real `/NOASSOC`. (3) In the `.aip`, move `FA_*` gating to
  component-level conditions as `REGISTER_PROTOCOL` already does - or author
  `INSTALLLEVEL` *and* add `SetInstallLevel` to the dialog - plus fix
  `SecureCustomProperties`. (4) Fix `association.cpp`. (5) Verification needs a
  Windows VM: `iscc` plus `reg query HKLM\Software\Classes\.docx` after a
  fresh install, and `msiexec /i ... REGISTER_NONE=1` for the MSI.
- **Two loose ends found in passing.** `inno/help.iss:15` still includes
  `..\..\..\win-linux\package\windows\defines.iss`, a path that no longer
  exists. And the association page creates every checkbox unchecked
  (`_code.iss:346`) while setting `AudioExtEnabled[i] := True` (`:347`), so
  `ChlbAudioClickCheck` (`:265-274`) re-checks every box the first time the user
  picks "Associate selected" - the UI can present a selection nobody made.

## Driving the editor - now working

The harness can drive a packaged app over CDP. Three things that were
misdiagnosed for a while:

- **"The app launches with no window" was never a framework mismatch.**
  `AppDelegate.mm` calls `PFMoveToApplicationsFolderIfNecessary`, which raises a
  **modal** "Move to Applications folder?" alert for any bundle outside an
  Applications folder. On a terminal launch it is never drawn, so the process
  sits alive, foreground and windowless with no CEF browser - `sample <pid>`
  shows it parked in `-[NSAlert runModal]`. Suppress with `defaults write
  com.stackchase.rationdocs moveToApplicationsFolderAlertSuppress -bool YES`.
- **The start window is CEF, not native.** `/json` lists `login/index.html`
  before any document exists, so an empty `/json` means the app has not finished
  starting.
- **A document opens only via `open -a <app> <file>`**; a path on argv does
  nothing. And the editor lives in a **child iframe** CEF does not expose as a
  target, so `editor-eval.js` walks the iframes for the one holding
  `Asc.editor`.

`harness/bin/build-app.sh` packages an app from a payload snapshot - take the
snapshot *before* starting any `build_tools` build, which rewrites
`build_tools/out` underneath you. `harness/README.md` has the procedure and its
limits.

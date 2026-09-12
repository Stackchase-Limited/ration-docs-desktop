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

Two defects in our own tooling were fixed alongside: CEF remote debugging was
pinned to a hardcoded port 8080 that could not be overridden, and CEF failures
were silenced by `LOGSEVERITY_DISABLE` (both `desktop-sdk`).

## Root-caused, not fixed

### #1839 - exporting the focused sheet to CSV exports a different sheet

Data loss in the sense that the user gets the wrong data with no warning.

- **Mechanism.** `Workbook.prototype.setActive` (`sdkjs/cell/model/Workbook.js:3859`)
  assigns `nActive` with no History entry, so switching sheet is pure view
  state and never enters the change stream. The desktop save sends *changes*,
  which x2t applies to the `Editor.bin` written at open time, so the stored
  `activeTab` stays stale. `core/OOXML/Binary/Sheets/Writer/CSVWriter.cpp:143`
  picks the sheet with `GetActiveSheetIndex()`.
- **Proven empirically.** Built two-sheet workbooks differing only in
  `<workbookView activeTab=...>` and converted them with our own x2t:
  `activeTab=0` exported sheet a, `activeTab=1` exported sheet b. So x2t honours
  the flag and the flag is what is stale.
- `ActiveTab` *is* serialised, in `cell/model/Serialize.js:3972`
  (`WriteWorkbookView`), but only when a full binary is produced.
- **Next step.** Either carry the active sheet in the save parameters -
  `sdkjs/cell/Local/api.js` `getAdditionalSaveParams()` already ships
  `adjustOptions.activeSheetsArray` for PDF printing - and honour it in
  `CSVWriter`, or refresh the bin on save. Needs a `core` change plus an x2t
  rebuild to verify, which is why it was left.
- Do **not** "fix" this by recording sheet activation in History: that would
  make switching sheets an undoable action.

### #1868 - the cursor does not return to the cell you left it on

Same root cause as #1839: selection and active cell are view state that never
reaches the saved file. Fixing #1839 properly should fix this too. No separate
investigation needed beyond the above.

### #2418 - formula-based conditional formatting makes the document uneditable

**Contained, not cured.** A throwing rule no longer disables editing
(`sdkjs/cell/model/Workbook.js`, `getSafeCompareFunction` next to
`getCacheFunction`), but the exception itself is unidentified.

- The reported "An error occurred during the work with the document" is
  `Asc.c_oAscError.ID.EditingError`, raised **only** from the global handler in
  `sdkjs/common/apiBase.js:374`, i.e. it is an uncaught JS exception. That
  handler then calls `asc_setViewMode(true)`, which is why the document goes
  read-only.
- Evaluation path examined: `Worksheet.prototype._updateConditionalFormatting`
  (`cell/model/Workbook.js:7531`), `doExpression` (:7713), `getCacheFunction`
  (:7548), `CFormulaCF.getValue`
  (`cell/model/ConditionalFormatting.js:2199`), and consumption in
  `SheetMergedStyles.getStyle` (`cell/model/WorkbookElems.js:5910`).
- Ruled out: `doExpression` returning a boolean rather than a dxf is *correct* -
  `getCacheFunction` maps it via `setFunc(row, col) ? rule.dxf : null`.
- **Next step.** Run the ready-made repro at
  `harness/repros/2418-conditional-formatting.js` against a properly packaged
  build with CDP attached, and read the stack. See the harness limitation below.

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

## Deliberate behaviour - product decision, not a defect

### #1568 - highlight and font colour not captured by "update style"
Highlight is stripped on purpose. `Paragraph.prototype.GetStyleFromFormatting`
(`sdkjs/word/Editor/Paragraph.js:15732`) clears `TextPr.HighLight` with the
comment *"В стиль не добавляется HighLight"*. Font colour **is** captured, via
`fill_TextPr` at `:15781` and `:15785`. Diverging from upstream for Word parity
is a call for us to make; the reporter's expectation matches Word.

## Feature requests, not defects

### #1959 - MyAnimeList XML opens in the document editor
Not a detection bug. The files' root element is `<myanimelist>`.
`core/Common/OfficeFileFormatChecker2.cpp:1683-1700` recognises Word 2003
WordML, SpreadsheetML (`xmlns:ss`), flat ODF, Office packages and HTML, and
anything else falls back to `AVS_OFFICESTUDIO_FILE_DOCUMENT_XML` at `:150` by
design. What is being asked for is arbitrary-XML import into the grid, as
Excel's XML import does - a sizeable feature. Repro files are attached to the
issue.

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

## Tooling limitation worth knowing

The harness in `harness/` can attach to the desktop app over CDP and evaluate
JS in the editor, which is what the #2418 repro needs. Remote debugging works,
but `/json` reports **no page targets**: a CEF browser only exists once a
document is open, and swapping a freshly built framework into an existing app
bundle produces an app that launches with no window at all. Closing this needs
a properly packaged build from `desktop-apps/macos`. Until then, F1 opens
DevTools interactively, and `harness/bin/x2t.sh` converts documents headlessly -
which is how #1839 was proven.

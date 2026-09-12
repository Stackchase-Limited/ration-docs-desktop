# Upstream issue triage

Working notes on issues from the ONLYOFFICE Desktop Editors tracker
(<https://github.com/ONLYOFFICE/DesktopEditors/issues?q=is%3Aissue+state%3Aopen+label%3Aconfirmed-bug>),
used as a bug source for this fork. See `UPSTREAM.md` for provenance and
`MODIFICATIONS.md` for what we have changed.

**The point of this file is to make an issue resumable.** Every entry that is
not fixed records what was already examined, what was ruled out, and the next
concrete step, so nobody re-derives it from scratch.

## Where to resume

Branch `ration/9.4-stability` in the superproject and in every submodule it
bumps. Everything described in this file is committed; nothing is pushed, and no
human has run a build with any of it.

**Next task:** #2110, #2208 and #2148 are all traced below but **none is fixed**,
and none should be attempted without being able to run the app. Each needs an
observation this tree cannot produce by reading. The harness in `../../harness/`
can now launch a real build and drive the editor over CDP, so that is the way in.

The two items left from earlier rounds are both blocked rather than untouched - the
caret half of #1868 needs a format change, and the password *prompt* for #2252
needs a `web-apps` dialog that should wait until the localization question is
settled.

**Build status: everything here compiles and links.** A full
`build_tools/make.py` build was run on 2026-09-12 with all of this session's work
in the tree. Exit 0, 114,388 log lines, zero errors. Four objects rebuilt -
`cefview.o` and `client_renderer_wrapper.o` (the files #2278 and #2252 changed),
plus `filelocker.o` and `spellchecker.o`, which include the headers touched. The
changes are confirmed present in the shipped artifacts, not merely compiled:
`strings` finds the new `convertFile(path, format, callback, password)` shim and
the `on_convert_file_callback(folder, error)` signature in
`ascdocumentscore.framework`, `checkKeyboardLanguageId` is in all four
`sdk-all-min.js` bundles, and `isPasswordConvertError` in cell, word and slide.

Two earlier claims in this file were wrong and are retracted. The first said
`desktop-sdk` could not be compiled because CEF headers were not set up: the CEF
distribution ships in the tree at
`desktop-sdk/ChromiumBasedEditors/lib/src/cef/mac`, and
`../fork-fix-tests/syntax-check-desktop-sdk.sh` type-checks any file we patch
against it in about four seconds, with no CEF binaries, Qt or link step - useful
while iterating, since it is seconds against a full build's minutes. The second is
below, about the wasm smoke test.

What remains true, and is the only honest caveat left: **no human has used the
result.** A build that links and a binary that runs correctly are different
claims, and nothing here has been exercised in a running editor.

**Owed before shipping:** integration smoke testing of the rebuilt
`fonts.wasm`. The list is at the end of the #2155 entry. An earlier note said this
needs a human; that was wrong. `../../harness/` packages a launchable `.app` and
drives the real editor over the Chrome DevTools Protocol - `run-editor.sh` to
launch and send a document, `editor-eval.js` to evaluate inside the editor iframe
- which is how the #2418 stack trace was obtained. Shaping a string through the
rebuilt wasm in the running editor and comparing glyph indices against the values
recorded in the #2155 commit (`Begrüßung` -> 129/137 correct, 220/192 poisoned) is
scriptable. Note the README's warning: packaging reads `build_tools/out` directly,
so take an APFS clone (`cp -Rc`) if a build may run concurrently.

**Loose end, now identified and preserved:** the 158-file, ~170k-insertion
`web-apps` diff is **build output**. `build_tools/make.py` writes those locale
files back into the source tree on every run - the build log says so per locale
(`ar.json done, lost 0 from 482`). Running a full build over the existing output
reproduced it byte-identically apart from incrementing `build` counters, so
nothing was ever at risk. It is committed on the `web-apps` branch
`ration/l10n-build-output` (4372964e93), deliberately not on
`ration/9.4-stability`; the superproject still points at 58d1593b86.

The decision it still needs is not "keep or discard" but **tracked or ignored**:
these files are tracked *and* rewritten by the build, which is why the diff keeps
reappearing. Either regenerate and commit them deliberately, or `.gitignore` them.
Worth weighing separately that the sync puts English text into every RTL locale
(`ar`, `fa`, `he`) - better than a raw key id, but a product call.

## The verification standard

A fix is not considered done until a test proves it, and proves it *detects the
bug*:

1. Extract the real function(s) from the source by brace-matching and run them
   against stubs - Node for JS, `clang++` for C++, real QtCore for Qt code
   (Qt5 is at `/opt/homebrew/opt/qt@5`).
2. Run the same test against the unpatched baseline (`git show HEAD:<path>`)
   and confirm it **fails** there. A test that passes before and after proves
   nothing.
3. For `desktop-sdk`, also type-check the file in place with
   `../fork-fix-tests/syntax-check-desktop-sdk.sh`. Extracting a block into a
   harness proves its logic but stubs away its types, so a wrong signature or a
   misspelled member survives; that script compiles the real translation unit
   against the real CEF headers. Confirm it has teeth the same way as a baseline
   run - break the new line on purpose once and watch it fail.

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
| #2400 | A defined name in a VLOOKUP dependency threw and forced the document read-only | `sdkjs` |
| #2383 | No `.~lock` marker on network shares, so a second user got no warning | `desktop-sdk` |
| #2018 | A synthetic resize event per intermediate size, flashing the grid | `desktop-sdk` |
| #963 | Ctrl+S with a cell in edit mode saved nothing and lost the typed value | `sdkjs` |
| #1333, #1016, #1641 | A truthiness test discarded a print range of `0` (Active sheets) | `sdkjs` |
| #2310, #1509 | An inserted video became a 50x50 box instead of its poster size | `sdkjs` |
| #459 | Spanish spell-check worked only for es-ES; 20 other locales were unmapped | `sdkjs` + `dictionaries` |
| #2262 | macOS Control+click opened no context menu in any editor | `sdkjs` |
| #1179, #402 | A keyboard layout's LANGID became the text language unvalidated; a custom or neutral layout set it to 8192 and spell check stopped | `sdkjs` |
| #2278 | Copying a sheet to a new file opened the whole original workbook; the selected-sheets binary was written only for cloud-crypto documents | `desktop-sdk` |
| #2252 | A reference to a password-protected workbook showed `#REF!`; no password could be supplied and the failure reason never reached JS | `desktop-sdk` + `sdkjs`, partial |
| #2243 | An unmapped format id made a nameless filter, and the portal then refused the whole Save As dialog - the document could not be saved | `desktop-apps` |

Two defects in our own tooling were fixed alongside: CEF remote debugging was
pinned to a hardcoded port 8080 that could not be overridden, and CEF failures
were silenced by `LOGSEVERITY_DISABLE` (both `desktop-sdk`).

**Correction.** An earlier working note said the `codes` arrays in
`dictionaries/<name>/<name>.json` are not read by the desktop build, on the
grounds that `spellchecker.cpp` builds dictionary paths as
`"/" + name + "/" + name + ".aff"` from the JS-supplied name. The path building
is right but the conclusion was wrong. `CSpellChecker::Init`
(`desktop-sdk/.../spellchecker.cpp:683-714`) keys `m_map_dictionaries_files` on
`Dictionaries[i].m_lang` from `core/Common/3dParty/hunspell/autogen/records.h`,
and `SetLanguage(nLang)` returns `NULL` for any LCID absent from it.
`records.h` is generated from exactly those `codes` arrays by
`core/Common/3dParty/hunspell/autogen/generate.py` (checked in, run by hand -
no build step invokes it). So the `codes` arrays **are** the source of truth for
the native side, and a locale needs to appear in three places to work:
that JSON, the regenerated `records.h`, and the hand-maintained
`spellcheckGetLanguages()` in `sdkjs/common/spell/spell.js`. The #459 test
asserts the JS map and the generated table agree, since a mismatch is invisible
at runtime.

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

### #2155 - native consumers fixed; the canvas needs a wasm rebuild, which is now possible

The charmap leak is fixed in `core` (`a980108812`) and proven against real
FreeType: `ü` was resolving through a font's Macintosh cmap to MacRoman 0xFC
and `ß` to the `fl` ligature, because our harfbuzz patch's
`hb_ft_get_index_by_unicode` restores the entry charmap only on failure, and a
single tab or newline is enough to poison a cached face. x2t, doctrenderer, PDF
and image export and thumbnails are correct.

**The canvas half is now built and proven, and the binary shipping today is
confirmed affected.** The deleted emscripten recipe was restored in `core`
(`bf2e06d09a`, `dcbc889a60`) and the wasm's own copy of the shaper fixed
(`5394be5543`).

Three results, each checked independently of the agent that produced them:

1. **Toolchain proof.** With the restored recipe and emsdk 3.1.48, the generated
   glue `fonts.js` is **byte-identical** to the copy checked into `sdkjs` -
   58,721 bytes of body, differing only in the 19-byte 2026 copyright header
   refresh. Export/import tables match at 145 entries. The recipe reproduces
   what upstream shipped.
2. **The fix works.** `fork-fix-tests/issue-2155-canvas-wasm/run.sh both`:
   pre-fix `shape("Begrüßung")` gives `[37,72,74,85,220,192,88,81,74]`,
   which reads `Begr¸ﬂung`; post-fix `[...,129,137,...]`. 12/12 both ways.
3. **The shipping binary has the bug.** Loading the *currently checked-in*
   `sdkjs/common/libfont/engine/fonts.wasm` under that same glue fails 4 of the
   12 assertions with exactly the corrupt GIDs (220, 192). This is what settles
   the entry: the corruption is live in the artefact users get, not merely
   reproducible in a synthetic baseline.

**Scope of the rebuild.** The rebuilt wasm is +802 bytes. Only four files in the
whole wasm-compiled source set differ from what produced the checked-in binary:
`DesktopEditor/fontengine/FontFile.cpp` and `TextShaper.cpp` (+39 lines, the
charmap restore), `Common/3dParty/harfbuzz/patch/hb-ft.cc.patch` (+24, the fix
that actually corrects the canvas) and `languages.h` (+5/-2, the yo/ig/ha
registration) - plus the wasm's own `text.cpp` and upstream's copyright refresh.
Everything else in the module (zlib, the PNG/JPEG/TIFF/PSD/TGA decoders,
EMF/WMF playback, hyphenation) is the same source through the same toolchain,
which the byte-identical glue evidences.

**The `text.cpp` fix specifically is defence in depth, not a separately
observable fix.** The reproduced corruption comes from the harfbuzz leak. A
leaked charmap only corrupts a lookup when the wrong charmap *returns* a glyph,
and no available font has a last-in-list non-Unicode cmap that is also dense
over U+0080-U+00FF - Arial's is dense but not last, `ani.ttf`'s is last but
sparse. Part 4 of the test is therefore an invariant that holds on both builds,
and says so.

**Not done: placing the artefacts.** `wasm-work/place-artifacts.sh` (dry run by
default) writes one tracked file - `sdkjs/common/libfont/engine/fonts.wasm` and
`fonts_ie.js`; `fonts.js` needs no change, its body already matches - plus six
gitignored copies. It preserves each destination's license header, because
`min.py` prepends `core/Common/license/header.license`, still the 2023 text
while `sdkjs` carries the 2026 refresh, so a wholesale copy would silently
revert it. `fonts_ie.js` was rebuilt in the same pass (`libfont.json` has
`"asm": true`); its body differs by +1,258 bytes, consistent with carrying the
same source changes. `drawingfile.wasm` (the PDF canvas) needs no source change
- it compiles the already-fixed `FontFile.cpp` and no harfbuzz at all - but does
need a rebuild, which means staging eight more component trees and 795 TUs.
`build_tools` has no wasm step at all today; `build_js.py` only copies prebuilt
binaries.

**Hazard worth remembering:** the harfbuzz fix reaches the wasm only through the
*gitignored* `Common/3dParty/harfbuzz/harfbuzz/` checkout, patched on fresh
clone from the tracked patch. An existing unpatched checkout silently drops the
fix.

**The editor canvas is not**, because it loads a prebuilt
`sdkjs/common/libfont/engine/fonts.wasm`. That is no longer a dead end:

- **The build recipe exists and upstream deleted it from `core`** - commits
  `2da2866862` "Refactoring" (15 files under `DesktopEditor/fontengine/js/`,
  including the 377-line `libfont.json`) and `b77b3dc7e2` "Remove unused files"
  (47 more, `Common/js/make.py` and `graphics/pro/js/`). Both recoverable from
  `<commit>^`. `make.py` pins emsdk to emscripten **3.1.48**.
- **It has been rebuilt and the artefact proven to be the shipped one.** The
  generated `fonts.js` glue is **byte-identical to the checked-in file past the
  license header - 58,721 bytes**. Export and import tables match exactly. The
  wasm differs by 730 bytes (0.02%), which is source drift in our fork since the
  binary was vendored.
- **The fix was verified inside the wasm**, which no earlier test reached. A/B
  against `a980108812^`, relinked for Node: the baseline returns
  `shape("Begrüßung")` = `[37,72,74,85,220,192,...]` - literally `Begr¸ﬂung` - and the
  fixed build returns `[...,129,137,...]`.
- Working recipe, emsdk and artefacts are outside the repo in
  `../wasm-work/` (1.8 GB, 1.4 GB of it emsdk); entry points
  `build-fonts-wasm.sh` and `relink-node.sh`.

**Two findings that enlarge this issue, both confirmed in the source:**

1. **`a980108812` does not reach the canvas even after a rebuild.**
   `libfont.json` does not compile `fontengine/FontFile.cpp` at all. The wasm
   carries a private copy of the same loop in
   `DesktopEditor/fontengine/js/cpp/text.cpp` (`ASC_FT_SetCMapForCharCode`) with
   no charmap save or restore, whose non-Unicode branch assigns `nCharIndex` and
   keeps iterating - the pre-fix code verbatim. It must be patched before
   shipping a rebuild. (Established by reading the source; not reproduced,
   because the JS surface does not expose `face->charmap` and MacRoman agrees
   with ASCII.)
2. **The PDF viewer has the leak independently.** `drawingfile.json` *does*
   compile `FontFile.cpp`, so `sdkjs/pdf/src/engine/drawingfile.wasm` (10.2 MB)
   needs the same rebuild. Same driver, larger source set.

**Remaining work, roughly 1.5-3 days, mostly not the build:** restore ~80 recipe
files from `2da2866862^`/`b77b3dc7e2^` (note `graphics/pro/js/before.py` mutates
tracked files in place, so stage it outside the tree); patch `cpp/text.cpp`;
decide on the stale asm.js twin `fonts_ie.js`, which `loader.js:100-107` only
reaches when `WebAssembly` is absent; rebuild `drawingfile.wasm`; wire it into
`build_tools` so it is not a laptop ritual; and land the output at **all six
checked-in copies** of `fonts.wasm` (`sdkjs/`, `sdkjs/deploy/`,
`desktop-apps/macos/Vendor/...`, and three under `build_tools/out/`).

**Do not mitigate in JS.** The A/B settles it: corruption appears *within a
single shaping call* on an already-poisoned face, so no post-hoc re-probe can
repair glyph indices already returned. And note the rebuild is reproducible but
**not bit-identical**, so the first ship is a real change to the font engine
rather than a like-for-like swap - it deserves a wider render smoke test than
this issue alone.

### #2148 - PDF print: chain traced end to end, symptom not reproduced

The reporter has Expected and Actual swapped in the issue form; the title is the
claim: objects added in the PDF editor are not printed.

**The changes do reach the printer.** `PDFEditorApi._printDesktop`
(`sdkjs/pdf/api.js:4955`) calls `viewer.Save()` and passes the binary as the third
argument of `AscDesktopEditor.Print`. The renderer binding
(`client_renderer_wrapper.cpp:1836`) writes it to a temp file and puts the path on
the `print` message; `cefview.cpp:2977` stores it as `m_sNativePrintChangesFile`;
`:7364` hands it to `CAscNativePrintDocument::Open`, which calls `EditPdf()` to
build `<recoveryDir>/PdfFileWithChanges.bin`, replays the changes with
`AddToPdfFromBinary()`, and reopens that file to print. So the plumbing is intact
and the obvious hypothesis - "print ignores the edits" - is wrong.

**What is actually wrong there, and is fixed:** `m_sFileWithChanges` was never
assigned, so the destructor's cleanup was unreachable and every such print left a
full copy of the edited document in the recovery directory. Fixed; it is not the
reported symptom.

**Where to look next, in order:**

1. `EditPdf()` failing. The `if (EditPdf(sTempFile))` block is skipped **in
   silence** on failure, and the print then proceeds from the unedited PDF - which
   is exactly the reported symptom. Same silent-skip shape as #2278. Instrument
   that branch first.
2. `bIsNativePrint`. The switch at `cefview.cpp:7322` creates the native printer for
   PDF, PDFA, XPS and DJVU only. `AVS_OFFICESTUDIO_FILE_DOCUMENT_OFORM_PDF` is not
   in it, and the `m_sOriginalFileNameCrossPlatform` override just above replaces
   `sLocalFileSrc` without updating `nLocalFileSrcFormat`. Either could route a
   session down the non-native path at `:7370`.
3. Only then look at the renderer fallback.

`GetPrintPage` is a red herring: it is the print *preview* path
(`word/Drawing/printpreview.js:192`), not printing.

### #2110 - slide PDF export crops the right side

`CPrintData::FitToPage` (`desktop-sdk/.../fileprinter.cpp:499`) is correct - a plain
aspect-preserving fit with centring. Presentations force `pmFit` with
`ZoomEnable` at `:527`, so the suspect is the rotate branch at `:648-677`: when the
slide and the paper disagree on orientation it swaps `fPrintWidthMM` and
`fPrintHeightMM`, calls `FitToPage` in that rotated space, then converts with
`dWidthPix = nPrintDpiX * fFitWidth`, mixing the rotated extent with the unrotated
axis's DPI, and centres against `nPrintWidthPix`/`nPrintHeightPix`, which are also
unrotated. That is consistent with content overflowing one edge.

**Tested by hand, 2026-09-12, and it mostly does not reproduce.** Ademola ran the
export and could not see a problem *except when the content is almost bleeding off
the edge of the slide*. That reframes the issue and lowers its priority:

- `FitToPage` is given the **slide** dimensions (`fPageWidth`/`fPageHeight`), not the
  bounding box of the content. Anything a user has dragged past the slide edge is
  outside the page by definition, and cropping it is what PowerPoint does too. For
  that case this is correct behaviour, not a defect.
- What is left to explain is only the margin: content that sits *just inside* the
  edge and still loses a sliver. That would be a rounding or half-pixel error in the
  mm-to-pixel conversion (`nPrintDpiX * fFitWidth / (10 * ONE_INCH)`, truncating
  toward zero), not the rotate-branch theory above - which remains unproven and is
  now the less likely of the two.

**Before spending more on this, get a file that reproduces it.** Without one, the
honest reading is that #2110 is a near-edge rounding question at worst, and the
rotate branch should not be touched on suspicion alone.

### #2208 - PDF editor replaces barcodes with their value or a black box

Not started beyond reading the report, and it is the least tractable of the three.
The `*VALUE*` with asterisks that the reporter sees is the Code 39 convention: the
barcode is text drawn in a barcode font, and the asterisks are its start/stop
delimiters. So the symptom is font substitution - the embedded barcode font is lost
when the page is converted for editing and a normal face is put in its place, which
makes the digits legible and the barcode meaningless. The black-box case is the same
failure with a font that renders as solid glyphs. This lives in `core` PDF font
handling, not in `sdkjs`. Worth pairing with #2155 and #2406, which are also font
and glyph problems.

### #2252 - plumbing done; an interactive prompt still has no home

The chain now works end to end for the common case, and the layer that could not
act can now act.

`CConvertFileInEditor` has an `m_sPassword` and emits `<m_sPassword>`, which x2t
has always parsed. `on_convert_local_file` carries x2t's exit code, and the
renderer hands it to the JS callback, so `getLocalDesktopPromise` can finally tell
an encrypted workbook from a missing one instead of mapping both to `#REF!`.
`convertFile` takes a password as a fourth argument; retrying through the ordinary
message keeps the converter stateless, so the `_convertFileSetPassword` binding the
earlier note called for was not needed.

**Read the codes as exit codes.** `NSX2T::Convert` returns x2t's *process exit
code*, and `getReturnErrorCode()`
(`core/X2tConverter/src/cextracttools.cpp:72-75`) subtracts both bases from the
`AVS_FILEUTILS_ERROR_*` value. So the numbers on this wire are the offsets: 80 is
`..._CONVERT`, 89 `..._NEED_PARAMS`, 90 `..._CONVERT_DRM`, 91
`..._CONVERT_PASSWORD` - which is why the codes already handled in `cefview.cpp`
are the small 89/90/91 and not full HRESULTs. Anything written here that looks like
a full `AVS_*` value is a bug.

`ExternalDataLoader.js` retries once on 90 or 91 with the password the user already
gave for this document. That fixes the common case outright - a workbook and the
workbook it references are usually protected with the same password - and the
password goes only to the local converter.

**Still open: a prompt for a reference with its own password.** The main document's
channel (`asc_onAdvancedOptions` with `c_oAscAdvancedOptionsID.DRM = 2`,
`common/commonDefines.js:599`) is wired to reopening the main document, so it
cannot be reused for one external reference. This needs a new event plus a dialog
in `web-apps` - which is also where the undecided 158-file localization diff sits,
so that should be settled first. Everything below that dialog is now in place: pass
the collected password as `convertFile`'s fourth argument and the retry already
works.

The community patch attached to the issue is the right shape but not usable:
its braced block orphans the code after an existing `return true;`, it sends a
new process message with no renderer-side handler so the prompt never fires, and
it leaves a commented-out duplicate of the function body behind.


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

### #1837 - inactive main tab wrong in the light theme

Fixed upstream by `54614981a` "[macos] fix titlebar appearance on macOS 10.14+"
(Feb 2026), in our tree and later than the reporter's 8.3.2. It added
`ASCThemesController.isDarkWindowAppearance`
(`desktop-apps/macos/ONLYOFFICE/Code/Controllers/Common/ASCThemesController.m:201-210`)
and replaced `[NSApplication isSystemDarkMode]` at every site driving the
inactive portal tab (`ASCTitleBarController.mm:426, 452, 457, 549`,
`ASCTabs/ASCTabView.m:105`, `ASCTabs/ASCTabViewCell.m:70, 207`). Before it, the
*inactive* tab picked its logo from the **system** appearance while the *active*
one used the **app theme**, so with the system dark and the app forced light it
drew the light logo on a light tab - the reported screenshot. The two remaining
`isSystemDarkMode` calls (`ASCTitleBarController.mm:418, 446`) are legitimate:
they resolve `theme-system` to a default.

Proven rather than asserted: `fork-fix-tests/issue-1837-inactive-main-tab/`
compiles the real methods against real Foundation/AppKit, reads the theme from
real `NSUserDefaults` and the chosen logo back off a real `NSButton`. At
`54614981a^` it is 2 passed / 9 failed; on the current tree 11 / 0. It also
shows the pre-fix code was wrong in both directions.

**Residual divergence, by inspection, not patched:** the asset-catalog tab
colours (`ASCTitleBarController.mm:231-232`, `ASCTabViewCell.m:162-163`) resolve
through `NSAppearance`, and the app never calls `setAppearance:`, so for a user
who does not set `NSRequiresAquaSystemAppearance` the tab *backgrounds* still
follow the system while the logo follows the theme. Not the reported symptom.
Next step if it ever is: route them through
`ASCThemesController currentThemeColor:`, or set an explicit `NSAppearance` from
the theme.


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

### #1894 - documents cannot be saved when saving a pptx

Not a defect in our source: a corrupted installation. The reporter's console
line `Check failed: VerifyChecksum(blob)` is V8's `CHECK` on a **startup
snapshot blob**, which aborts the process and cannot be caught. The only place
we hand V8 an external blob is `CJSContext::Initialize`
(`core/DesktopEditor/doctrenderer/js_internal/v8/v8_base.cpp:191-207`), reading
the shipped `editors/sdkjs/<app>/sdk-all.bin` via `GetSnapshotPath`
(`doctrenderer/editors.cpp:175`). A damaged shipped file therefore aborts rather
than degrading - and the maintainer established on the thread that the
reporter's AppImage sha256 does not match the official 8.3.3 build. The reporter
never confirmed a re-download.

Ruled out: the #2081/#2417 family (that was a write reported as success; this is
a process abort) and a stale V8 code cache (`sdk-all.cache` is version-checked
and rejected gracefully, not `CHECK`ed). No patch: pre-validating the blob would
mean reimplementing V8's private snapshot checksum.

**If anyone reproduces it on a verified-good install:** find which process
aborts, and note that an ordinary desktop bin-to-pptx save is native C++ -
doctrenderer/V8 enters the presentation path only via `apply_changes`
(`core/X2tConverter/src/ASCConverters.cpp:1397`), so V8 aborting during a plain
local save is itself the anomaly.


### #2136 - crash opening a folder containing an emoji (Linux)

Root-caused, with a runnable demonstration; the fix belongs in `core`.

Not really about the Downloads folder: per the thread it needs a folder whose
name is an emoji plus the `segoe-ui-linux` font installed, and the maintainer
reproduced it only after installing that font. It segfaults inside
`libgraphics.so` while the GTK file chooser paints the name.

**Mechanism.** `core/DesktopEditor/graphics/pro/freetype.pri` pins FreeType
2.10.4 and compiles it straight into `libgraphics.so`, and there is **no
`-fvisibility=hidden`, no version script and no `--exclude-libs` anywhere in the
tree**, so every `FT_*` symbol is exported with default visibility (harfbuzz
likewise, and ours is locally patched - see #2155). `desktop-apps` links
`-lgraphics` before the GTK stack, and ELF resolves through one process-wide
scope in load order, so cairo/pango's `FT_*` calls bind to libgraphics' 2.10.4
copy. The overlap is *partial*: the COLRv1 colour-glyph API arrived in FreeType
2.11 and is absent from the bundled tree, so an emoji's colour path falls
through to the system FreeType 2.13, which then reads a face laid out by 2.10.4.
Emoji only, and font-dependent - which is exactly why a clean VM was fine and
the reporter's host was not.

**Demonstrated**, not just argued: `fork-fix-tests/issue-2136-emoji-folder-crash/`
builds a system-FreeType stub with the new layout and COLRv1, a libgraphics stub
with the 2.10.4 layout and no colour API, and a cairo stub, linked flat to get
ELF's rules. As shipped, a plain name exits 0 and an emoji name dies with
**SIGSEGV (139)**; with `FT_*` hidden inside libgraphics both exit 0.

**Ruled out.** Our own GTK code is not on the stack - the crash is inside
`gtk_dialog_run` while GTK lists the folder, and
`platform_linux/gtkfilechooser.cpp:217-244` marshals names with no fixed buffers
or dangling temporaries; a marshalling bug could not depend on an installed
font. Reordering the link line is **not** an alternative: it would make
libgraphics' own engine bind to the system FreeType 2.13 while compiled against
2.10.4 headers - the same fault in the other direction. `--xdg-desktop-portal`
avoids the in-process dialog but is a workaround, and does nothing for other
in-process GTK rendering.

**Next step, owner `core`:** build `libgraphics.so` with `-fvisibility=hidden`
for the bundled FreeType/harfbuzz translation units, or add a version script to
`graphics/pro/graphics.pro` exporting only the `NSFonts`/`Aggplus`/`asc*` API
and localising `FT_*`/`hb_*`. Verify with
`nm -D --defined-only libgraphics.so | grep -c ' T FT_'` (must be 0), then the
reporter's repro. Also revisit
`desktop-apps/win-linux/defaults.pri:194`'s
`-Wl,-unresolved-symbols=ignore-in-shared-libs`, which is what lets seams like
this pass unnoticed at link time.


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

### #1641 - cannot export a selected spreadsheet range to PDF  [FIXED]

Resolved by the falsy-zero fix in `sdkjs/cell/api.js`; see the Fixed table.
The next step recorded here - "this is an sdkjs question, not a web-apps one" -
was right. `web-apps` sends `printType` correctly for all three range choices;
`asc_Print`/`asc_DownloadAs` then dropped it, because "Active sheets" is
`c_oAscPrintType.ActiveSheets === 0` and the option was read under
`if (_options["adjustOptions"]["printType"])`. A chosen range of 0 was
indistinguishable from "not supplied", so it silently fell back to Entire
workbook. Same root cause as #1333 and #1016.

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

## Latent problems found in passing, not yet fixed

Not reported upstream; found while working on something else, and cheap to lose.

- **`CLocalFileLocker` can call through an uninitialised pointer.** Its
  constructor returns early for an empty path
  (`desktop-sdk/.../applicationmanager_p.h:596-597`) leaving `m_pLocker`
  unassigned (declared `:591`, assigned only `:600`); the destructor then calls
  `Unlock()` -> `m_pLocker->Unlock()` on garbage (`:623`). Reachable via the
  `rec.lock` path at `cefview.cpp:1243`. Two lines to fix; no repro to hand.
- **A window *move* dispatches a synthetic resize.** `CCefView::moveEvent()`
  funnels into the same `UpdateSize` as a resize. Splitting them needs care -
  `applicationmanager.cpp:234` deliberately uses `moveEvent()` to re-apply
  `force-scale`, which does need the page notified. Harmless now that the
  injection is debounced (#2018).
- **`fonts_ie.js` will go stale.** It is the asm.js twin of `fonts.wasm`
  (`-s WASM=0`), reached only when `WebAssembly` is absent
  (`sdkjs/common/libfont/loader.js:100-107`), which never happens in CEF. Any
  `fonts.wasm` rebuild should rebuild it in the same pass so the two cannot
  diverge.
- **`-Wl,-unresolved-symbols=ignore-in-shared-libs`**
  (`desktop-apps/win-linux/defaults.pri:194`) suppresses exactly the link-time
  errors that would have surfaced the #2136 symbol collision.


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

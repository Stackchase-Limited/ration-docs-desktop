# Ration Docs Desktop 2026.3.1

A fix release on top of 2026.3.0. It brings in 25 crash, data-loss and security fixes that ONLYOFFICE
has made since our fork point, and fixes two defects of our own. Nothing else changes: there are no
new features and no new options.

## At a glance

- **25 ONLYOFFICE fixes backported** (8 in the file converter, 11 in the editors, 6 in the editor
  interface). We picked them by checking every change ONLYOFFICE has made up to 10.0 and its 9.4.1
  hotfixes, and taking the ones that fix a crash, lost data or a security hole. Each one has a test
  that fails without it.
- **Two defects of our own fixed:** a docbuilder crash (RD-0114) and the Windows installers'
  update service (RD-0113).
- **Tested:** 450 of 463 regression tests pass, including all 23 that run against a document
  server in Docker. The 13 that do not pass test work held back from this release or are still being looked into;
  none of them tests a fix in this release.
- **Still not signed.** See *Known limitations*.

## Security

- **SVG and CSS in documents can no longer crash the converter (ONLYOFFICE 4e3568c926, 3cf5178838,
  4a68bd2470).** A transform with no closing bracket made the converter read past the end of the
  text. On Linux and Windows, a large `@font-face` block or a long `url(data:...)` value overflowed
  the stack and crashed it. These files can arrive inside any Office document. The Linux test
  build confirmed that 2026.3.0 crashes on the two stack cases and 2026.3.1 converts them.
- **Builder scripts are confined to the document's folder (ONLYOFFICE 86a717a42f, 7a9c80e60c).**
  A docbuilder or document-renderer script could read files elsewhere on the disk, and its
  `OpenFile`/`SaveFile` parameters could redirect the converter's input, output and temporary
  paths.
- **Online only: WOPI copy and export restrictions are honoured (ONLYOFFICE dbc71b0951).** A host
  that set `DisableCopy` or `DisableExport` still let users copy and download.
- **Online only: the editor frame no longer grants clipboard-write to the page that embeds it
  (ONLYOFFICE 9c764ad966).** The desktop app keeps it, because it needs it.
- **The Windows installers no longer install ONLYOFFICE's update service (RD-0113).** The service
  started with Windows, although Ration Docs has no update module that
  uses it. Installing 2026.3.1 over an older version removes it and turns update checks off.

## Data loss

- **Inline cell text is kept when saving to `.xlsx` (ONLYOFFICE 60a3e45d01).** Cells holding
  inline strings, common in files from other programs and in `.xlsb` converted to `.xlsx`, were
  saved empty.
- **EMF and WMF pictures keep their vector original (ONLYOFFICE 7d08152895).** On save, the picture
  was replaced by its display preview, so it lost quality for good.
- **Remove Duplicates no longer deletes rows that only look the same (ONLYOFFICE 336a529b85 and
  three follow-ups).** Values were compared as displayed, so 1.001 and 1.002 in a two-decimal column,
  or the number 1 and the text "1", counted as duplicates. Text now matches regardless of case, as in Excel.
- **Workbooks with form controls save to `.xlsx` again (ONLYOFFICE 55851dae87).** A checkbox or
  button made the save fail.
- **Comments survive in two cases where they were lost (ONLYOFFICE 4f4e0fb256, 279413255a).**
  Compare Documents dropped the comments of a document with tracked paragraph deletions. A `.docx`
  whose comment had a duplicated start or end mark lost the comment's range, and the text after it.
- **Pasting a multi-range copy keeps the formula results (ONLYOFFICE 3d96c24b12).**
- **Online only: edits are no longer lost when the server runs out of resources (ONLYOFFICE
  ed424af8e4, d2b7aa7f89).** A newer document server tells the editor it is out of resources; the
  editor now locks editing and says so, instead of letting you type changes that are never saved.

## Crashes

- **Whole-word Find with a `(` no longer drops the spreadsheet to view-only (ONLYOFFICE 88e3c58d5d).**
- **docbuilder no longer aborts on quoted script arguments (RD-0114).** A `SaveFile` call whose
  parameters contained `'` quotes, such as the layout settings for plain-text output, or a call
  with more than four arguments, overflowed a fixed array and the process was killed. ONLYOFFICE
  10 still has this defect.
- **Fixed crashes in the editors:** placing the cursor in an empty hyperlink (52cac5d143), drawing
  or exporting a 3D area chart with an empty series (a85f2f55dd), and an empty presentation with
  the notes focused (9717a00f4f).
- **Fixed errors in the interface:** "Edit chart data" (fe000348f0), View > Macros clicked before
  its dialog loaded (fcd820a9de), and a plugin docked into the PDF editor's right panel
  (3f9b9168e4).
- **Images that finish loading while fonts are still loading no longer trigger an early redraw
  (c0758e150e).**

## Other changes

- The macOS project now records macOS 12 (Monterey) as the minimum. The 2026.3.0 build already
  required it; this makes the source say so.
- Build fixes, not visible in the app: the boost patch needed by Apple clang 21 is now part of the
  normal macOS build, and the Windows dependency check accepts the VC++ runtime when Windows lists
  it as "Microsoft Visual C++ v14".

## Known limitations of this release

- **Not signed.** Like 2026.3.0, this release has no Apple Developer ID, Windows code-signing
  certificate or Linux repository key. Signed builds will follow from the same `v2026.3.1` tag.
- **Platforms.**

  | Platform | Status |
  |---|---|
  | macOS (Apple Silicon) | `RationDocs-2026.3.1-arm64.dmg` built from the tag (801 MB, sha256 `e8e88ac84233df21b8879ff353f292d6a20390899c5dd71e36dfe9732f692e11`). Requires macOS 12 or later. Smoke-tested: About 2026.3.1.1, Home page, typing, bundled conversions |
  | Linux x64 | `ration-docs_2026.3.1-1_amd64.deb` built from the tag (409 MB, sha256 `4573b7b376a6baaf89390e62bc15ab49060374f25bceea47f9e18781bf009235`). Install-tested on Ubuntu 24.04: About 2026.3.1.1, Home page, bundled conversions, and the three crash cases above |
  | Windows | **Not built.** RD-0113 and the VC++ check have not been compiled or run yet |

  Both packages were built from the `v2026.3.1` tag; every source file was checked against it
  before building.
- **Online edition.** All the fixes except RD-0113 can reach the online edition, and four of them
  matter only there. They reach it only once the server is built from this release's trees.
- **Everything else** listed under *Known limitations* for 2026.3.0 still applies.
- **Not included:** the move to libxml2 2.16 is ready on its own branch but is held back for a
  separate decision.

## Fixes in this release

| Fix | Where | Our commit | Test (`fork-fix-tests/`) |
|---|---|---|---|
| RD-0113 | desktop-apps | 54973742e | rd-0113-no-update-service |
| RD-0114 | core | 104f3c7400 | rd-0114-docbuilder-txt-layout-abort |
| ONLYOFFICE 4e3568c926 | core | 036373296a | upstream-4e3568c926-css-transform-oob |
| ONLYOFFICE 3cf5178838 | core | a114b34e22 | upstream-3cf5178838-svg-css-regex-stack-overflow |
| ONLYOFFICE 4a68bd2470 | core | 8b9dbe831b | upstream-3cf5178838-svg-css-regex-stack-overflow |
| ONLYOFFICE ef6efb16b5 | core | a4c93729ec | upstream-3cf5178838-svg-css-regex-stack-overflow |
| ONLYOFFICE 86a717a42f | core | 40bfdac972 | upstream-86a717a42f-builder-file-escape |
| ONLYOFFICE 7a9c80e60c | core | 56e8603427 | upstream-86a717a42f-builder-file-escape |
| ONLYOFFICE 7d08152895 | core | 73083ac6f6 | upstream-7d08152895-emf-saved-as-preview |
| ONLYOFFICE 60a3e45d01 | core | e4e2f8a3c5 | upstream-60a3e45d01-xlsx-inline-string-lost |
| ONLYOFFICE 336a529b85 (+3) | sdkjs | 61decf01d5 | upstream-336a529b85-remove-duplicates-typed-values |
| ONLYOFFICE 55851dae87 | sdkjs | 16fa6276f2 | upstream-55851dae87-xlsx-form-control-save |
| ONLYOFFICE 4f4e0fb256 | sdkjs | b2485712ef | upstream-4f4e0fb256-compare-comments-merged-paras |
| ONLYOFFICE 279413255a | sdkjs | bfadc5f5e4 | upstream-279413255a-docx-duplicate-comment-marks |
| ONLYOFFICE 3d96c24b12 | sdkjs | badb625c83 | upstream-3d96c24b12-multirange-paste-values |
| ONLYOFFICE 88e3c58d5d | sdkjs | 9e2d845cce | upstream-88e3c58d5d-find-escape-regexp |
| ONLYOFFICE 52cac5d143 | sdkjs | ced56176b2 | upstream-52cac5d143-hyperlink-cursor-crash |
| ONLYOFFICE a85f2f55dd | sdkjs | 96ce86fb3d | upstream-a85f2f55dd-area-chart-empty-series |
| ONLYOFFICE 9717a00f4f | sdkjs | 8e32038043 | upstream-9717a00f4f-empty-presentation-notes-focus |
| ONLYOFFICE c0758e150e | sdkjs | 6069981437 | upstream-c0758e150e-image-load-during-font-load |
| ONLYOFFICE d2b7aa7f89 | sdkjs | 685d601fc2 | upstream-d2b7aa7f89-license-not-enough-resources |
| ONLYOFFICE ed424af8e4 | web-apps | 421379f73f | upstream-ed424af8e4-not-enough-resources |
| ONLYOFFICE dbc71b0951 | web-apps | 99feac1f77 | upstream-dbc71b0951-wopi-disable-copy-export |
| ONLYOFFICE 9c764ad966 | web-apps | a8f6d11def | upstream-9c764ad966-iframe-clipboard-write |
| ONLYOFFICE 3f9b9168e4 | web-apps | 1f55eb623e | upstream-3f9b9168e4-pdf-right-panel-plugin |
| ONLYOFFICE fe000348f0 | web-apps | 3cc030467f | upstream-fe000348f0-edit-chart-data |
| ONLYOFFICE fcd820a9de | web-apps | 4b37472c30 | upstream-fcd820a9de-macros-before-load |

## Installing

Same as 2026.3.0 (see below), with `2026.3.1` in the file names:

    xattr -dr com.apple.quarantine "/Applications/Ration Docs.app"   # macOS, after copying the app
    sudo apt install ./ration-docs_2026.3.1-1_amd64.deb              # Linux

Check the SHA-256 against the values above before installing.

---

# Ration Docs Desktop 2026.3.0

The third release of Ration Docs Desktop, a hard fork of ONLYOFFICE Desktop Editors 9.4. It is built
from the same branch as 2026.2.0 and adds fixes, a long list of options you can turn on, and a large
batch of converter hardening.

## At a glance

- **101 more reported upstream issues fixed** since 2026.2.0, and 98 of them have a regression test
  that fails without the fix. The full list is below. The fix registry (`FIXES.md`) now counts 321
  upstream issues in all. That is more than 209 + 101 because it now also credits earlier commits
  that fixed an issue without naming it (see *Credited late* below).
- **68 further defects that we found ourselves** (RD-0020 to RD-0112, with gaps), each with a test.
  Most are converter crashes, hangs and memory errors in old `.doc`, `.ppt` and `.xls` files, found
  by running the converter over thousands of public test documents. Another group (RD-0090 to
  RD-0112) are spreadsheet read and write defects, mostly in `.xlsb`.
- **Most new features are options and are off by default.** Nothing changes until you turn them
  on. See *New options* below.
- **Three security fixes**, plus many memory-safety fixes in the file converter. See *Security*.
- **This release is not signed yet.** See *Known limitations* and *Installing*.

## Security

- **File names can no longer inject script into the editor (RD-0030).** When you dropped a file
  onto the editor, inserted one, or picked a name in the save dialog, the file name was placed into
  the editor's script without escaping. A file with a deliberately crafted name could run script
  inside the editor. Names are now escaped everywhere they are used this way. Upgrade if you open
  files from people or places you don't trust.
- **Copying spreadsheet cells with a link now produces safe clipboard HTML (RD-0052).** A cell with
  an external link was copied as HTML with the link left open and its address and tooltip
  unescaped. Pasting into another application could therefore carry markup the cell never had. The
  link is now closed and its attributes are escaped.
- **Converted presentations no longer reveal a temporary path (RD-0070).** Saving an old `.ppt` as
  `.pptx` wrote embedded OLE objects as *links* to a file in the converter's temporary folder,
  instead of embedding them. The saved file disclosed a local path, and the object was lost once
  the temp folder was cleaned. The objects are now embedded in the `.pptx`.
- **The file converter is much harder to crash with a damaged or hostile file.** More than 40
  defects in the readers for old binary Office formats (`.doc`, `.ppt`, `.xls`, encrypted
  `.doc`/`.xls`, OLE compound files), `.xlsb` and ODF are fixed (RD-0021 to RD-0027, RD-0040 to
  RD-0049, RD-0072 to RD-0096 and RD-0102 to RD-0112).
  - Before, a malformed file could make the converter read or write past the end of a buffer,
    allocate gigabytes, or loop until it was killed.
  - A few of these were heap *writes*, which is the kind of memory error that matters most for
    security.
  - Each reader now trusts only the bytes actually in the file.
- **Saved files no longer carry stray memory.** Several writers put uninitialised bytes into the
  output: `.xlsb` sort conditions, phonetic text, table references and sheet properties, colours,
  and `.doc` pictures. These bytes could include leftover memory from the
  converter process. Output is now fully initialised, and the same input gives the same file every
  time (RD-0096, RD-0106 to RD-0108, RD-0110, RD-0111).
- **A `tel:` link to a phone number now opens your calling app without asking (#603).** This
  relaxes one rule from 2026.2.0, which asked before opening any non-web link. Only links that hold
  a phone number are affected; any other `tel:` text still asks first.

## Behaviour you will notice

- **A new start page.** The Home page has a new layout, with a light version and a dark version.
  The dark version is used with the Dark, Contrast dark and Night themes. The page has a "Home" title,
  a row of Create tiles, one Recent/Recover switch with a count of files that can be recovered, and
  the Inter typeface (SIL Open Font License 1.1, credited in About). Nothing on it was removed.
- **Presentations look more like PowerPoint.** This mostly affects decks made in PowerPoint.
  - **Kerning (#346).** Slide text is now kerned when the deck asks for it, and PowerPoint's
    default styles do. Lines can therefore fit or wrap differently than in 2026.2.0, now as they do
    in PowerPoint.
  - **Kerning is now saved.** Every earlier save silently removed kerning from a deck, and that
    data loss is fixed.
  - **Kerning in Word documents is unchanged.** Body text in Word documents keeps its 2026.2.0
    layout.
  - **Tabs and line heights (#343).** A tab that would run past the right edge of a text box now
    wraps to the next line, as in PowerPoint; before, it was squeezed onto the line.
  - **Large spaces now count towards the height of a line.** Some slides therefore move down a
    little, again to match PowerPoint. Word documents, including their text boxes, are unchanged.
  - **Negative indents (#348).** A paragraph with a negative first-line indent at zero margin no
    longer starts outside its text box.
  - **Videos follow PowerPoint's settings.** Videos set to loop (#2005), hide while not playing
    (#2007) or play full screen (#2008) now do so in the slide show.
  - **Trimmed videos stay trimmed.** A video's trim is now kept when you save (#2002); before, the
    trim was lost.
- **`.xlsb` workbooks.**
  - **Text opens as text (RD-0105).** Text cells of some `.xlsb` files opened as `0`, and they now
    open with their text. This also affects files saved by Excel.
  - **Numbers are saved as numbers (RD-0109).** Earlier builds, including ONLYOFFICE's, saved some
    numbers (for example 25.78) into `.xlsb` as text.
  - **Old `.xlsb` files may show numbers as text.** A file saved by an earlier build still stores
    some numbers as text, and they now show as text (for example `-25.780000000000001`), exactly as
    Excel shows them. To repair them, convert the cells back to numbers once and save.
  - **Colours (RD-0108).** Colours stored without transparency were given a random transparency
    value when written to `.xlsb`/`.xlsx`. They are now solid. A colour that looked faint or wrong
    may now show at full strength. Saved files also change from run to run less: the same workbook
    now gives the same file.
- **Slide sorter (#289) and undo.**
  - **Undo no longer switches views.** Undoing a change made in Normal view no longer jumps you
    from the Slide Sorter back to Normal view. The only view switch undo still makes is between
    master and slide views.
  - **Reordering in the sorter can be undone.**
  - **Ribbon insert commands still target the current slide**, which is hidden while the sorter is
    open.
- **Damaged legacy files are handled more strictly.** This applies to `.doc`, `.ppt` and `.xls`.
  - **What used to happen:** a damaged file could crash the converter, hang it, or open with
    garbage.
  - **What happens now:** it either opens with the unreadable parts left out, or fails with an
    error. Left-out parts include an over-long string, a slide's unreadable records, and tab stops
    past the end of their record.
  - **Undamaged files are unaffected.** Several hundred undamaged files convert byte for byte as
    before.
  - **Some damaged files open with less in them.** If a damaged file used to open with odd content,
    it may now open with less content, or report an error instead.
- **CSV: Ctrl+S keeps the file's delimiter and encoding (#83).** A CSV opened with semicolons or
  a non-UTF-8 code page used to be rewritten with commas and UTF-8 on Ctrl+S. It now keeps the
  options it was opened with. Save As now also offers a semicolon-separated CSV.
- **Move sheet to a new workbook now moves it (#1905).** It used to leave the sheet behind, which
  made it a copy.
- **Copy sheet to a new workbook (RD-0031).** The copy could have edits made to other sheets
  replayed onto it. It now opens clean.
- **Keys:**
  - Alt+Shift+Up/Down (Option+Shift on macOS) now move the selected paragraphs or list items up
    or down (#1203). They used to extend the selection.
  - In context menus, typing a letter now picks the item that starts with it (#1292).
- **Media:** dropping a video or audio file on a slide now inserts it (#2544).
- **Pictures:**
  - A picture copied in Inkscape now pastes as a picture, not as SVG text (#2180).
  - PowerPoint's "Set Transparent Color" on a picture is now shown in the editor (#2484). It is
    still opaque in PDF export and print.
- **Printing:**
  - Spreadsheet cell borders now print without a gap at every vertical border (#2437). Underlines
    and sparkline axes in print move by the same half pixel.
  - On Linux the print dialog's "Pages per side" now works (#1215).
- **Slide shows on three screens (#1548).** A presenter on the middle screen no longer gets the
  slide show over the presenter view.
- **Starting a slide show no longer crashes the app** when the window hangs off the edge of the
  desktop (#1548).
- **Documents:**
  - Document variables (`w:docVars`) are now kept when you save (#100). Before, Word fields that
    read them showed an error after the document was saved here.
  - Hyperlinks on slide shapes and pictures now work in exported PDFs (#1885).
- **Old Word, ODF and RTF files:**
  - A `.doc` header that came and went between opens now always shows (RD-0045).
  - RTF font names keep their spaces (RD-0062).
  - ODP imports keep line breaks, list spacing and outline sizes (#2566).
- **Linux:**
  - With an Azerbaijani, Basque or Malay system locale, the app now starts in that language
    (#1355).
  - A desktop set to greyscale font smoothing no longer gets colour fringes in the interface
    (#2130).
  - fcitx now works in documents on Plasma 6 Wayland (#1522).
  - The distribution's hunspell dictionaries are now also used for spell checking, for languages
    the app ships no dictionary for (#195).
- **Accessibility:** VoiceOver on macOS (#1872) and Orca on Linux (#1828) can now read the
  toolbars, menus and dialogs. The document page itself is still not readable. Nothing changes
  unless a screen reader is running.
- **macOS:** File > Open Recent now lists your recent documents (#69). Window > Move Tab to New
  Window is new (#1814).
- **Windows and Linux:**
  - F11 now toggles full screen for the whole window (#858). On macOS, Ctrl+Cmd+F already did this
    in 2026.2.0.
  - Interface scaling also offers 105-145% in 5% steps (#2342).
- **Links that open your browser now say so** in their tooltip (#1363).

## New options

All of these are **off by default** unless noted, so nothing changes until you turn them on.

**In the start page's Settings** (desktop app):

- "Reopen documents from the last session at start": local files only (#1847).
- "Save changes automatically when closing a document" (#1674).
- "Ctrl+Tab goes to the most recently used tab" (#2139).
- "Colour tabs by document type" (#2436).
- "Built-in plugins can be removed in the Plugin Manager". After a restart, bundled plugins can be
  removed and restored. The app folder is never written to (#2466).
- "Add spelling dictionary..." installs a Hunspell dictionary into your profile (#1438).
- Windows and Linux:
  - "Pinch to zoom (touchpad, touchscreen)" (#1611).
  - "Slideshow screen": Automatic by default (#1548).
- Windows: make Ration Docs the default app for all supported file types again (#1177).
- Linux:
  - "Title bar: Built-in / System (window manager)": Built-in by default (#2504).
  - "Window buttons: Close only" (#1899).
  - "Use the desktop's file dialog (portal)" on X11 (#2321).

**In the editors, File > Advanced settings:**

- **Documents:**
  - "Default font" (#746) and "Default page margins" (#1166) for new blank documents.
  - "Format for new documents": OpenDocument instead of Office Open XML for the first save
    (#517).
  - Smooth scrolling with the mouse wheel (#1925).
  - Break Thai, Lao, Khmer and Myanmar lines between words (#371).
  - "Show the Equation panel in the right sidebar when editing an equation" (#99, also in
    presentations).
  - Offer to continue where you left off when a document is reopened (#1675). Turning it off
    deletes the saved places.
  - "Underline text while an input method composes it" (#2100). This one is **on** by default, so
    behaviour is unchanged unless you turn it off.
  - Numeral "Context": Hindi digits in right-to-left paragraphs (#2160).
- **Presentations:**
  - "Default presentation language" (#527).
  - The Slide Size dialog's "Use this size for new presentations" (#2137).
- **Spreadsheets:**
  - "Highlight active row/column" (#1521).
  - Ctrl+D / Ctrl+R fill down / right (#2258).
  - Ctrl+Shift+V pastes values only (#2020).
- **PDF:** new text boxes take the last text box's style (#1687).
- **All editors:**
  - Shift+mouse wheel scrolls sideways on Windows and Linux (#852).
  - Name the last action in the Undo tooltip (#1064).
  - "Command search (Alt+/)" finds and runs a ribbon command by name (#1801).
  - Allow pinning toolbar buttons to the quick access toolbar (#420).
- AutoCorrect has "Correct TWo INitial CApitals" (#222). It starts unticked.

**New commands that are simply there:**

- **Desktop:**
  - File > Save Copy as (#982).
  - File > Duplicate (#2045).
  - Mail merge on local files (#733).
- **PDF:** "Save pages as new PDF" (#1858).
- **Presentations:**
  - Slide Sorter view (#289).
  - Video trim, mute, loop, rewind and hide in Playback (#2002, #2003, #2005, #2006, #2007).
  - Play/Pause/Stop media animations (#2550).
  - "From clipboard" picture fills (#1969).
- **Spreadsheets:**
  - "Merge and keep content" (#2044).
  - Custom error bars (#278).
- **All editors:**
  - Search in the Comments panel (#322).
  - The Dictionary... list, to remove added words (#630).
  - Odd/even-only printing (#2299), and manual two-sided printing on Windows and Linux (#2422).
- **AI:**
  - Groq as an AI provider (#2225).
  - Hand-entered model names (#2239).
  - An editable grammar-check prompt (#2219).

**For whoever builds the release:**

- `desktop-apps/macos/make_pkg.sh` can build a macOS `.pkg` for MDM (#2477).
- The Linux package can carry one menu entry per editor with `EDITOR_LAUNCHERS=1` (#591).
- Neither is wired into the release build.

## Known limitations of this release

- **Not signed.**
  - 2026.3.0 is published unsigned on every platform: there is no Apple Developer ID, no Windows
    code-signing certificate and no Linux repository key yet.
  - Signed macOS, Windows and Linux builds will follow **from the same `v2026.3.0` tag** once the
    certificates exist. The code will be identical; only the signatures will differ.
  - Until then, the same guidance as 2026.2.0 applies; see *Installing* below.
- **Platforms.**

  | Platform | Status |
  |---|---|
  | macOS (Apple Silicon) | `RationDocs-2026.3.0-arm64.dmg` built from the tag (768 MB, sha256 `680bc06b…2d5afb`). **Requires macOS 12 (Monterey) or later** (was 11). Smoke-tested: new Home page, typing and saving, bundled conversions. About window to be checked by hand |
  | Linux x64 | `ration-docs_2026.3.0-1_amd64.deb` built from the tag (409 MB, sha256 `277459d7…775d925`). Install-tested on Ubuntu 24.04: About 2026.3.0.1, new Home page, bundled conversions. Repository signing tested with a throwaway key only |
  | Windows | **Not built.** Windows code in this release (#34, #1177, #2106 and others) has not been compiled yet |

- **GUI checks pending.**
  - Most new options and dialogs were verified by tests and builds, but not yet by hand in each
    operating system's interface.
  - This includes the slide sorter, mail merge, the Equation panel, the command search, the Linux
    title-bar and file-dialog settings, and the Windows installer associations.
- **Co-editing across versions.** Kerning (#346) is a new property in saved changes. Editing the
  same document live with an older build, or with an online server not built from this release,
  can misread those changes. Keep the server and the desktop app on the same version.
- **Online edition.**
  - Fixes in `core`, `sdkjs` and `web-apps` can reach the online edition: 65 of the 101 issues and
    66 of the 68 defects. That covers all the converter and `.xlsb` fixes, the presentation layout
    changes and the clipboard fix (RD-0052).
  - They reach it only once the server is built from this release's trees. The online server
    currently running is an ONLYOFFICE build with none of our fixes.
  - Some of those 65 appear only in the desktop app, such as Save Copy as, Duplicate, local mail
    merge and the defaults for new documents.
  - The other 36 issues, RD-0030 and RD-0031 are desktop-only, because they are in the desktop
    shell (`desktop-apps`, `desktop-sdk`) or the bundled plugins. Examples are the Settings options,
    F11, the screen-reader support, the slide-show players and the file-name escaping fix.
- **Partial fixes.**
  - #1085 and #220 are covered only by the new "Title bar: System" setting. The built-in title bar
    still has no button-style or left-side-buttons choice.
  - #2484 transparent colours are not yet in PDF export or print.
  - #2566 ODP bullets still wrap left of the bullet text.
- **Held back, not in this release:** #164, #2114, #1347, #1330, #1876, #2391, #564 and #1718 (the
  macOS font-weight change). Work on these exists but is not included in 2026.3.0.

## Credited late

Nine upstream issues were fixed by commits that are **already in 2026.2.0**, but were not counted
there.

- Eight are fixed by commits that do not name them, and are now credited through
  `tools/fix-claims.txt`: #402, #1179, #1509, #2310, #1333, #1016, #626 and #466.
- #73 (Cmd+Up/Down on macOS) shipped in 2026.2.0 but was missing from its notes.

None of the nine is new in 2026.3.0, and none is in the count above.

Likewise, **#858, #1847, #1868 and #2275** were counted in earlier releases and are not counted
again, although this release extends them:

- F11 full screen on Windows and Linux (#858).
- Reopening the last session (#1847).
- A saved workbook now reopens with the cursor where you left it (#1868).
- `&F` in a spreadsheet header no longer prints "null" in a PDF saved from the desktop (#2275).

## Reported issues fixed in 2026.3.0

- On Windows a document dropped on the tab bar or title bar did not open; it now does, and capitalised and macro-enabled file names are accepted ([#34](https://github.com/ONLYOFFICE/DesktopEditors/issues/34))
- File > Open Recent on macOS was hidden and empty; it now lists recent local documents and opens them ([#69](https://github.com/ONLYOFFICE/DesktopEditors/issues/69))
- Ctrl+S on a CSV opened with semicolons or a non-UTF-8 code page rewrote it as comma/UTF-8; it now keeps the options it was opened with, and Save As offers a semicolon CSV ([#83](https://github.com/ONLYOFFICE/DesktopEditors/issues/83))
- An Equation panel in the right sidebar gives structures, a searchable symbol palette and the linear/professional switch while editing an equation (option) ([#99](https://github.com/ONLYOFFICE/DesktopEditors/issues/99))
- Document variables (w:docVars) were dropped by every save from the editor, breaking DOCVARIABLE fields in Word; they are now kept ([#100](https://github.com/ONLYOFFICE/DesktopEditors/issues/100))
- On Windows, fonts activated from Adobe Fonts in Creative Cloud now appear in the font list ([#141](https://github.com/ONLYOFFICE/DesktopEditors/issues/141))
- INDIRECT("Sheet!Table[Column]") gave #REF!; it now returns the column, so a validation list from another sheet's table works ([#159](https://github.com/ONLYOFFICE/DesktopEditors/issues/159))
- The Keyboard Shortcuts search now finds an action by words from its name or its description ([#179](https://github.com/ONLYOFFICE/DesktopEditors/issues/179))
- On Linux the spell checker now also uses the distribution's hunspell dictionaries for languages the app ships none for ([#195](https://github.com/ONLYOFFICE/DesktopEditors/issues/195))
- A folder could not be taken off "Recent folders"; right-click now offers Open, Pin/Unpin and Remove from list ([#201](https://github.com/ONLYOFFICE/DesktopEditors/issues/201))
- The OCR plugin skipped TIFF pictures silently; it now reads them and says when it cannot read a file ([#211](https://github.com/ONLYOFFICE/DesktopEditors/issues/211))
- With "System (window manager)" title bar on Linux, the desktop's own window buttons are used, left or right as configured (part: no choice for the built-in bar) ([#220](https://github.com/ONLYOFFICE/DesktopEditors/issues/220))
- AutoCorrect can correct TWo INitial CApitals ("HEllo" -> "Hello") - option, off by default ([#222](https://github.com/ONLYOFFICE/DesktopEditors/issues/222))
- Charts can have custom error bars whose plus/minus values come from sheet ranges (Error Bars > More options...) ([#278](https://github.com/ONLYOFFICE/DesktopEditors/issues/278))
- A Slide Sorter view (View tab) shows all slides as a grid to select, reorder, delete, duplicate and open ([#289](https://github.com/ONLYOFFICE/DesktopEditors/issues/289))
- The Comments panel has a search box that narrows the list to comments containing the typed text ([#322](https://github.com/ONLYOFFICE/DesktopEditors/issues/322))
- Slide text with tabs past the right edge and large spaces now lays out as in PowerPoint ([#343](https://github.com/ONLYOFFICE/DesktopEditors/issues/343))
- Slide text is now kerned where the deck asks for it, and kerning survives saving ([#346](https://github.com/ONLYOFFICE/DesktopEditors/issues/346))
- A slide paragraph with no left margin and a negative indent no longer starts outside its text box ([#348](https://github.com/ONLYOFFICE/DesktopEditors/issues/348))
- Thai, Lao, Khmer and Myanmar text can break lines between words (option, off by default) ([#371](https://github.com/ONLYOFFICE/DesktopEditors/issues/371))
- A plain ribbon button can be pinned to the quick access toolbar (option, off by default) ([#420](https://github.com/ONLYOFFICE/DesktopEditors/issues/420))
- The first save of a new document can offer OpenDocument instead of docx/xlsx/pptx (option) ([#517](https://github.com/ONLYOFFICE/DesktopEditors/issues/517))
- New blank presentations can get a chosen language ("Default presentation language") ([#527](https://github.com/ONLYOFFICE/DesktopEditors/issues/527))
- The Linux package can carry one menu entry per editor (build option, off by default) ([#591](https://github.com/ONLYOFFICE/DesktopEditors/issues/591))
- A tel: phone link can be entered as a hyperlink and opens the calling application ([#603](https://github.com/ONLYOFFICE/DesktopEditors/issues/603))
- A word added to the dictionary can now be removed again (Proofing > Dictionary...) ([#630](https://github.com/ONLYOFFICE/DesktopEditors/issues/630))
- Mail merge works on a local file in the desktop app, with no document server ([#733](https://github.com/ONLYOFFICE/DesktopEditors/issues/733))
- With document dark mode on, the PDF editor's loading page was white; it is now dark, and the document editor's follows the theme ([#736](https://github.com/ONLYOFFICE/DesktopEditors/issues/736))
- The font and size of new blank documents can be chosen ("Default font") ([#746](https://github.com/ONLYOFFICE/DesktopEditors/issues/746))
- EMF and WMF pictures can now be picked in Insert > Image from file ([#780](https://github.com/ONLYOFFICE/DesktopEditors/issues/780))
- Shift+mouse wheel can scroll documents, presentations and PDFs sideways (option, off by default) ([#852](https://github.com/ONLYOFFICE/DesktopEditors/issues/852))
- A dark interface theme with coloured document-type headers is available as an example, and a custom Visio header colour now reaches the Visio tab ([#888](https://github.com/ONLYOFFICE/DesktopEditors/issues/888))
- On Linux the window manager's own title bar can be chosen in Settings instead of with a command-line switch ([#926](https://github.com/ONLYOFFICE/DesktopEditors/issues/926))
- The Table settings panel can set the vertical alignment of the selected cells ([#947](https://github.com/ONLYOFFICE/DesktopEditors/issues/947))
- Save As into another format made the new file the open document; File > Save Copy as now writes a copy and leaves the open document as it was ([#982](https://github.com/ONLYOFFICE/DesktopEditors/issues/982))
- The Undo tooltip can name the step it undoes, e.g. "Undo: Typing" (option, off by default) ([#1064](https://github.com/ONLYOFFICE/DesktopEditors/issues/1064))
- On Linux a title bar that matches the desktop can be picked in Settings (part: no button-style choice for the built-in bar) ([#1085](https://github.com/ONLYOFFICE/DesktopEditors/issues/1085))
- The page margins of new blank documents can be chosen ("Default page margins") ([#1166](https://github.com/ONLYOFFICE/DesktopEditors/issues/1166))
- On Windows, Settings can make Ration Docs the default app for every supported file type again ([#1177](https://github.com/ONLYOFFICE/DesktopEditors/issues/1177))
- Paragraphs and list items can be moved up or down with Alt+Shift+Up / Alt+Shift+Down ([#1203](https://github.com/ONLYOFFICE/DesktopEditors/issues/1203))
- On Linux the print dialog's "Pages per side" was ignored; it now reaches the printer (part) ([#1215](https://github.com/ONLYOFFICE/DesktopEditors/issues/1215))
- Typing a letter now picks an item in the editors' context menus ([#1292](https://github.com/ONLYOFFICE/DesktopEditors/issues/1292))
- Azerbaijani, Basque and Malay shipped but could not be chosen; they are now in the interface language list ([#1355](https://github.com/ONLYOFFICE/DesktopEditors/issues/1355))
- Links and the Feedback & Support button opened the web browser without saying so; their tooltips now say so ([#1363](https://github.com/ONLYOFFICE/DesktopEditors/issues/1363))
- A Hunspell dictionary for another language can be added from Settings, without touching the app's folder ([#1438](https://github.com/ONLYOFFICE/DesktopEditors/issues/1438))
- The active cell's row and/or column can be highlighted across the sheet (option, off by default) ([#1521](https://github.com/ONLYOFFICE/DesktopEditors/issues/1521))
- fcitx could not be used in the document on Plasma 6 Wayland; the app now points GTK at fcitx when the session uses it ([#1522](https://github.com/ONLYOFFICE/DesktopEditors/issues/1522))
- The slide show screen can be chosen on Windows/Linux; with three screens it no longer covers the presenter view, and a window off the desktop edge no longer crashes it ([#1548](https://github.com/ONLYOFFICE/DesktopEditors/issues/1548))
- Pinch to zoom can be turned on for Windows/Linux touchpads and touchscreens (option, off by default) ([#1611](https://github.com/ONLYOFFICE/DesktopEditors/issues/1611))
- Closing a modified local document can save it without asking (option, off by default) ([#1674](https://github.com/ONLYOFFICE/DesktopEditors/issues/1674))
- A reopened document can offer "Continue where you left off" (option, off by default) ([#1675](https://github.com/ONLYOFFICE/DesktopEditors/issues/1675))
- A new PDF text box can take the style of the last one (option, off by default) ([#1687](https://github.com/ONLYOFFICE/DesktopEditors/issues/1687))
- The full example themes were invalid and incomplete; they are now a complete, loadable template for a custom theme ([#1695](https://github.com/ONLYOFFICE/DesktopEditors/issues/1695))
- A command search finds a ribbon command by name and runs it (option, off by default) ([#1801](https://github.com/ONLYOFFICE/DesktopEditors/issues/1801))
- On macOS a tab could be moved to its own window only by dragging; Window > Move Tab to New Window now does it ([#1814](https://github.com/ONLYOFFICE/DesktopEditors/issues/1814))
- Orca read nothing in the editors on Linux; the interface is now readable while a screen reader runs ([#1828](https://github.com/ONLYOFFICE/DesktopEditors/issues/1828))
- Selected PDF pages can be saved as a new PDF from the page menu ([#1858](https://github.com/ONLYOFFICE/DesktopEditors/issues/1858))
- The print preview of a large spreadsheet now shows "please wait" while it is built ([#1864](https://github.com/ONLYOFFICE/DesktopEditors/issues/1864))
- VoiceOver read nothing but the window title on macOS; toolbars, menus and dialogs are now readable ([#1872](https://github.com/ONLYOFFICE/DesktopEditors/issues/1872))
- A hyperlink on a slide shape, picture or group is now a clickable link in the exported PDF ([#1885](https://github.com/ONLYOFFICE/DesktopEditors/issues/1885))
- On Linux the built-in title bar can show the close button only ("Window buttons: Close only") ([#1899](https://github.com/ONLYOFFICE/DesktopEditors/issues/1899))
- Move sheet to a new workbook left the sheet in the source (a copy); it now moves it ([#1905](https://github.com/ONLYOFFICE/DesktopEditors/issues/1905))
- Mouse-wheel scrolling in documents can be smooth instead of a notch at a time (option, off by default) ([#1925](https://github.com/ONLYOFFICE/DesktopEditors/issues/1925))
- Hovering a recent file now shows its full path ([#1952](https://github.com/ONLYOFFICE/DesktopEditors/issues/1952))
- A slide background or shape picture fill can be taken from the clipboard ([#1969](https://github.com/ONLYOFFICE/DesktopEditors/issues/1969))
- A video's trim was lost on every save; it is now kept, played as trimmed and can be set in Playback ([#2002](https://github.com/ONLYOFFICE/DesktopEditors/issues/2002))
- A video or audio can be set to play muted, and the setting reaches the player ([#2003](https://github.com/ONLYOFFICE/DesktopEditors/issues/2003))
- A video or audio can loop until stopped, and one that loops in PowerPoint now loops here ([#2005](https://github.com/ONLYOFFICE/DesktopEditors/issues/2005))
- A video or audio can rewind after playing, as PowerPoint's option does ([#2006](https://github.com/ONLYOFFICE/DesktopEditors/issues/2006))
- A video or audio can be hidden in the slide show while not playing, and PowerPoint decks that ask for it now hide it ([#2007](https://github.com/ONLYOFFICE/DesktopEditors/issues/2007))
- A video set to Play Full Screen in PowerPoint now fills the slide show while it plays ([#2008](https://github.com/ONLYOFFICE/DesktopEditors/issues/2008))
- Ctrl+Shift+V can paste values only in the cell grid (option, off by default) ([#2020](https://github.com/ONLYOFFICE/DesktopEditors/issues/2020))
- Number formats with the Persian calendar now show Jalali dates ([#2033](https://github.com/ONLYOFFICE/DesktopEditors/issues/2033))
- Cells can be merged keeping all their contents, one per line ("Merge and keep content") ([#2044](https://github.com/ONLYOFFICE/DesktopEditors/issues/2044))
- File > Duplicate opens a local document's current state as a copy in a new tab ([#2045](https://github.com/ONLYOFFICE/DesktopEditors/issues/2045))
- The underline under text an input method is composing can be turned off (option, on by default) ([#2100](https://github.com/ONLYOFFICE/DesktopEditors/issues/2100))
- The Windows installer registers .dot, .docm, .xlt, .ppsm, .fodp, .hwp and .hwpx for Default apps ([#2106](https://github.com/ONLYOFFICE/DesktopEditors/issues/2106))
- The document dark-mode page colour now comes from the interface theme, so a theme can make it black ([#2112](https://github.com/ONLYOFFICE/DesktopEditors/issues/2112))
- On Linux with greyscale font smoothing the interface still had colour fringes; it now follows the desktop's setting ([#2130](https://github.com/ONLYOFFICE/DesktopEditors/issues/2130))
- The Slide Size dialog can set the size of new presentations (option) ([#2137](https://github.com/ONLYOFFICE/DesktopEditors/issues/2137))
- Ctrl+Tab can go to the most recently used tab (option, off by default) ([#2139](https://github.com/ONLYOFFICE/DesktopEditors/issues/2139))
- Numeral can be "Context": Hindi digits in right-to-left paragraphs, Arabic digits elsewhere ([#2160](https://github.com/ONLYOFFICE/DesktopEditors/issues/2160))
- A picture copied in Inkscape pasted as SVG source text; it now pastes as a picture ([#2180](https://github.com/ONLYOFFICE/DesktopEditors/issues/2180))
- The AI grammar check's prompt can be changed (Grammar & Spelling > Settings) ([#2219](https://github.com/ONLYOFFICE/DesktopEditors/issues/2219))
- The AI agent can use Groq as a provider ([#2225](https://github.com/ONLYOFFICE/DesktopEditors/issues/2225))
- An AI agent provider can be given model names by hand, next to the fetched list ([#2239](https://github.com/ONLYOFFICE/DesktopEditors/issues/2239))
- Ctrl+D / Ctrl+R can fill down / right in the cell grid (option, off by default) ([#2258](https://github.com/ONLYOFFICE/DesktopEditors/issues/2258))
- The document and PDF print panels can print only the odd or only the even pages ([#2299](https://github.com/ONLYOFFICE/DesktopEditors/issues/2299))
- On X11 the file dialogs can use the desktop's own dialog (option, off by default) ([#2321](https://github.com/ONLYOFFICE/DesktopEditors/issues/2321))
- Interface scaling jumped from 100% to 125% to 150%; 105-145% in 5% steps are now offered ([#2342](https://github.com/ONLYOFFICE/DesktopEditors/issues/2342))
- An installed copy started from another folder took itself for the portable ZIP; it no longer does, and the ZIP is documented ([#2404](https://github.com/ONLYOFFICE/DesktopEditors/issues/2404))
- Documents and PDFs can be printed on both sides manually on Windows/Linux ([#2422](https://github.com/ONLYOFFICE/DesktopEditors/issues/2422))
- Document tabs can show a strip in the colour of their type (option, off by default) ([#2436](https://github.com/ONLYOFFICE/DesktopEditors/issues/2436))
- Printed cell borders broke at every vertical border; they now meet ([#2437](https://github.com/ONLYOFFICE/DesktopEditors/issues/2437))
- Plugins installed with the app can be removed and restored in the Plugin Manager (option, off by default) ([#2466](https://github.com/ONLYOFFICE/DesktopEditors/issues/2466))
- A macOS installer package (.pkg) can be built for MDM deployment ([#2477](https://github.com/ONLYOFFICE/DesktopEditors/issues/2477))
- A picture's transparent colour (PowerPoint's Set Transparent Color) is now drawn in the editors (not yet in PDF or print) ([#2484](https://github.com/ONLYOFFICE/DesktopEditors/issues/2484))
- On Linux the system title bar needed a command-line switch; Settings now has "Title bar: Built-in / System" ([#2504](https://github.com/ONLYOFFICE/DesktopEditors/issues/2504))
- A video or audio file dropped on a slide is now inserted ([#2544](https://github.com/ONLYOFFICE/DesktopEditors/issues/2544))
- Media Play, Pause and Stop animations can be added to a video or audio (Animation > Media) ([#2550](https://github.com/ONLYOFFICE/DesktopEditors/issues/2550))
- ODP import dropped text before a line break, added empty paragraphs before sub-lists and gave outline levels 2-9 level 1's size; all three fixed ([#2566](https://github.com/ONLYOFFICE/DesktopEditors/issues/2566))

## Defects we found ourselves

- **RD-0020** Adding, changing or removing an animation dropped the slide's video/audio settings (mute, volume, loop, hide, full screen); they are now kept
- **RD-0021** A .doc whose comment-range bookmarks have no tag data, or fewer end positions than starts, crashed x2t; such ranges are now skipped
- **RD-0022** Saving as ODT a document whose date/text/list content control has no font size in scope crashed x2t; the control is sized with a 12 pt default
- **RD-0023** An ODF table column or cell repeated "-1" (or any huge count) made x2t allocate without bound; the repeat count now stops at 16384
- **RD-0024** A compound (OLE) file whose directory entries link back in a loop made x2t recurse and allocate until killed; each entry is now listed once
- **RD-0025** A .ppt container whose records overran its length sent the reader back to the start of the stream, re-reading it until x2t was killed; it now resumes after the container
- **RD-0026** A .doc table row whose end has no paragraph properties crashed x2t; the row is now read without table properties
- **RD-0027** A .doc whose header counts more main-text characters than the file holds kept x2t converting for minutes; the main text now ends where the text does
- **RD-0030** Dropped, inserted and saved file names were put into the editor's script unescaped, so a crafted name could run script; they are now escaped (security)
- **RD-0031** A sheet copied to a new workbook could get the source's edits replayed on it; the copy now opens without them
- **RD-0040** A .doc character FKP claiming more runs than its page holds left NULL run properties that crashed x2t; such runs now get empty properties
- **RD-0041** A .doc without paragraph FKPs crashed x2t in its headers, footers or text boxes; they now start with no inherited paragraph properties
- **RD-0042** .doc readers used the length a record claimed instead of the bytes the stream held, reading past their buffers; they now use the bytes actually read
- **RD-0043** A .doc sprm cut short at the end of its grpprl was read past the buffer (and could ask for a 4 GB copy); its operand is now limited to the bytes present
- **RD-0044** A .ppt slide whose records could not be read crashed x2t; the slide is now written without them
- **RD-0045** The .doc header/footer table was read one position past its end, so an empty header came and went between runs; it is now read within the table
- **RD-0046** A .ppt whose edit chain loops back kept x2t reading it until killed; each edit is now read once
- **RD-0047** A .doc whose PAPX/CHPX bin table length runs past the table stream made x2t read wild memory or allocate gigabytes; the table now holds only what the stream has
- **RD-0048** .doc lengths and counts far beyond the file made x2t allocate until killed; PLEX, LFO and Clx reads are now limited by the stream
- **RD-0049** .doc footnote/endnote and comment-author loops never ended on a damaged file, writing until x2t was killed; they now stop at the end of their table or stream
- **RD-0050** docbuilder took an x2t that could not start or crashed for a successful conversion and then aborted on open; such runs now fail the open/save
- **RD-0051** A drawing or form control below rows without a height came back from ODS at row 18446744071562068031; such rows now count with the default height
- **RD-0052** Copying cells with an external link put an unclosed link and its unescaped address and tooltip into the clipboard HTML; the link is closed and its attributes escaped (security)
- **RD-0053** The font ranges table credited fonts with characters they lack; each font's marks are now cleared
- **RD-0054** The font ranges table ended its last range at U+10FFFE although it covers U+10FFFF; it now ends at U+10FFFF
- **RD-0055** A macro assigned to a chart was dropped when saving as ODS; the chart's binding now goes through ODS like a shape's
- **RD-0056** ODF frames wrote their event listeners before the frame content, which the ODF schema does not allow; the listeners now follow the content
- **RD-0060** A compound file over ~7 MB (e.g. a password-protected save) listed sector 0 in its unused DIFAT slots; they are now marked free
- **RD-0062** RTF font names written as \uN lost their spaces on open ("TimesNewRoman"); the whole name is now trimmed, not each piece
- **RD-0070** .ppt OLE objects were written to .pptx as external links to x2t's temp file, disclosing a local path; they are now embedded (security)
- **RD-0072** A .doc whose section properties run past the end of the WordDocument stream made x2t read past its buffer; only the bytes read are parsed
- **RD-0073** A .doc string table entry running past the end of its stream made x2t convert memory past the buffer; only the bytes read are converted
- **RD-0074** A .doc tab-stop sprm shorter than its tab count made x2t read past the sprm; tabs past the end are now dropped
- **RD-0075** A .doc huge PAPX or table-properties grpprl running past the Data stream made x2t read past its buffer; only the bytes read are parsed
- **RD-0076** A .doc OLE CompObj/Word 6 string whose length runs past its stream made x2t read past its buffer; only the bytes read are converted
- **RD-0077** A .doc OLE object whose LinkInfo string, picture borders or Word 6 data run past their stream made x2t read past its buffer; only the bytes read are used
- **RD-0078** A .doc comment whose author initials claim more characters than they hold crashed x2t; only the characters read are converted
- **RD-0079** A .doc form field whose name or other string runs past the Data stream made x2t read past its buffer; only the characters read are converted
- **RD-0080** A .doc font table cut short inside a font's panose or name made x2t read past its buffer; only the bytes read are used
- **RD-0081** A .doc picture header cut short by the end of the Data stream made x2t read past its buffer; only the bytes read are used
- **RD-0082** A .doc string table whose last extra data is cut short by the end of its stream made x2t read past its buffer; such extra data is not kept
- **RD-0083** A .doc/.xls encryption header whose salt or verifier runs past its stream or record made x2t read past its buffer; only the bytes present are used
- **RD-0084** A .ppt compressed OLE/VBA storage record shorter than 4 bytes made x2t write past its buffer; such a record now holds no object
- **RD-0085** A .ppt picture record shorter than its header made x2t allocate and write ~4 GB; such a record now holds no picture
- **RD-0086** An .xls formula whose length runs past its record made x2t read past the record buffer; the formula stops at the end of the record
- **RD-0087** An .xls hyperlink moniker or picture key whose length runs past its record made x2t read past the record buffer; lengths are limited to the record
- **RD-0088** An .xls Continue record shorter than its header made x2t write past a heap buffer; such a record adds no data
- **RD-0089** An .xls drawing whose property table claims more properties than its record holds made x2t read past the record buffer; properties stop at the end of the record
- **RD-0090** Inline-string cells in an xlsx without shared strings were folded into the first cell of the row (mail merge, ODS and "send to" lost them); they are now kept
- **RD-0091** An encrypted .xls whose encryption header ends before its salt made x2t read 16 bytes from an empty salt; a short value is now zero-padded
- **RD-0092** An encrypted .xls with a sheet record shorter than 4 bytes made x2t decrypt past the record (heap overflow); such a record is not decrypted
- **RD-0093** A .doc fixed-size sprm cut short at the end of its grpprl made x2t read past its operand; the operand is now zero-padded to its size
- **RD-0094** A .doc table sprm whose variable-size operand is shorter than its structure made x2t read past the operand; such operands are now checked before use
- **RD-0095** An .xlsb conditional-format formula whose extra data is missing made x2t read past the record; the book type is now 0 there
- **RD-0096** A .doc picture record claiming more bytes than it holds put uninitialised memory into the .docx image, or made x2t over-read 4 GB; only the bytes present are read
- **RD-0100** A number format built on General was written as "1000eneral" in JSON/CSV export, and Save as CSV dropped literal text such as General" kg"; the value is now written with the format's text
- **RD-0101** Cells of a C++-written Editor.bin came back one row below their row in xlsx; a cell now takes the row it is read in
- **RD-0102** x2t crashed writing CSV/JSON when a cell's style has no entry or a shared string table is missing - reachable by Save As CSV of an unedited workbook; such a cell is now written unstyled / with its stored value
- **RD-0103** Every number of a typed cell was written to xlsb as 0 on some conversion paths, formula results too; the stored value is now written
- **RD-0104** x2t crashed converting any .xlsb for External Links update or mail merge; the xlsb is now read as an xlsb on those paths
- **RD-0105** An .xlsb's inline strings and string-formula cells opened in the editor as 0 (text lost); they now open with their text
- **RD-0106** An .xlsb sheet with a short sheet-properties record got a random sync reference, different every run; it now gets none
- **RD-0107** Every .xlsb written with a sort condition carried 8 uninitialised bytes; they are now 0
- **RD-0108** A 6-digit rgb colour (no alpha) got a random alpha byte in xlsb/xlsx; it is now opaque
- **RD-0109** Numbers such as 25.78 were written to .xlsb as text, on Save As xlsb too; they are written as numbers
- **RD-0110** A structured table reference written to .xlsb (Table1[Col], Table1[#All]) had an uninitialised column bound; it is now set
- **RD-0111** Shared strings with phonetic properties were written to .xlsb with uninitialised bytes; they are now 0
- **RD-0112** x2t crashed writing .xlsb when a sort condition sorts by cell or font colour without a format id; the condition is now written

## Installing

**2026.3.0 is not signed or notarised.** The guidance is the same as for 2026.2.0.

- Download only from the project's own release page.
- Check the SHA-256 against the checksum published beside the file:

      shasum -a 256 <file>        # macOS
      sha256sum <file>            # Linux

### macOS

Gatekeeper will refuse the first launch, usually with *"Apple cannot check it for malicious
software"*, or *"is damaged and can't be opened"*. That message is expected for this release and
does not mean the download is corrupt.

1. Drag **Ration Docs.app** to `/Applications`.
2. Remove the quarantine attribute:

       xattr -dr com.apple.quarantine "/Applications/Ration Docs.app"

3. Open it normally.

### Linux

    sudo apt install ./ration-docs_2026.3.0-1_amd64.deb

The exact file name is to be confirmed by the integrator before publishing. The package is unsigned. `apt` will report it as untrusted if you add it to a repository rather
than installing the file directly.

### Windows

There is no Windows build of 2026.3.0 yet.

### About the missing signature

An unsigned build means **you are trusting the source of the file**, and nothing else is vouching
for it. If that is not acceptable, wait for the signed builds. They will be made from the same
`v2026.3.0` tag.

---

# Ration Docs Desktop 2026.2.0

The second release of Ration Docs Desktop, a hard fork of ONLYOFFICE Desktop Editors 9.4, and the
first built for **macOS, Windows and Linux**.

## At a glance

- **125 more reported upstream issues fixed** since 2026.1.0, so 209 in all, and 170 of those have
  a regression test that fails without the fix. The full list is below.
- **18 further defects that we found ourselves** (RD-0001 to RD-0018). Most are converter crashes
  and memory errors found by running the converter over thousands of public test documents.
- **A security overhaul.** Every page and plugin now runs with the least access it needs, and the
  security fixes from ONLYOFFICE 10.0 are backported. See *Security* below.

## Security

- **Plugins you install yourself now run in their own sandbox.** They can no longer read the open
  document or use the desktop bridge beyond a short list of safe calls.
- **The desktop bridge is only given to our own pages.** That means our own pages, bundled plugins
  and connected cloud portals. Remote iframes, other web pages and other local files get nothing.
- **Local files are protected.** Pages can only read the folders the editors need. Symbolic links
  and `..` paths can no longer escape those folders.
- **Links in documents are checked before anything opens.** Web and mail links open as before.
  Links to programs, scripts and installers are refused. Anything else asks you first.
- **Macros need your consent.**
  - A shape or button with an assigned macro asks before it runs (#2188).
  - Custom functions saved in a workbook wait for consent before they run.
  - The macro warning defaults to "No".
- **PDF form scripts run in a separate sandbox,** cut off from the rest of the app.
- **The AI agent's tools are limited to files you gave it.** It can only read files you picked,
  dropped or attached, and asks before reading any other file or starting a program.
- **The ONLYOFFICE 10.0 security fixes are backported.** They cover XPS, WMF/EMF, Word, PowerPoint
  and PDF images, HWP, libxml2, macros and plugin paste. The in-app PDF viewer's copy of the code
  is rebuilt with them.
- **Nothing is downloaded from ONLYOFFICE's servers at run time.** Plugin installs use the copy of
  the plugin API shipped with the app.

## Behaviour you will notice

- **Macros:** the first click on a macro button now asks first. Until you allow macros, cells that
  use a workbook's custom functions show `#NAME?`.
- **Your own plugins:**
  - Plugins that need more of the bridge than the safe list stop working.
  - A user-updated AI plugin loses its saved keys.
  - Plugins can't reach `http://` servers on your local network.
- **Links:** opening a link to a local file, folder or network share asks you first.
- **Saving to network shares and synced folders:**
  - A save that fails part-way now leaves the original intact and tells you (#2000).
  - A save needs room for two copies of the file.
- **CSV:**
  - Saving a multi-sheet CSV with Ctrl+S now warns that only one sheet is kept (#1490).
  - Rows beyond 1,048,576 are reported, not silently dropped.
- **Settings:**
  - "Keep a list of recent files" (#1594).
  - "Default document language" (#143).
  - "Non-breaking spaces with French punctuation" (#2075).
  - On a fresh profile, units follow your OS region (#432).
- **Shortcuts:**
  - Cmd/Ctrl+Shift+T reopens a closed tab (#1847).
  - Cmd/Ctrl+Shift+G opens the word count (#167).
  - Ctrl+N creates a new document on Windows and Linux (#200).
  - Ctrl+Q quits on Linux (#1270).
  - Ctrl+Cmd+F enters full screen on macOS (#858).
  - Control+U edits the active cell on macOS, and Cmd+U underlines (#247).
- **macOS:** the "Check for Updates" menu item and its prompt are gone. Ration Docs has no update feed.

## Known limitations of this release

- **Some changes need a GUI check.** Many were verified by tests and builds but not yet by hand in
  each operating system's interface: the new dialogs and menus, the Windows installer and the
  Linux sandboxes.
- **Windows code was not compiled in the macOS development cycle.** The Windows build must be
  compiled on the Windows x64 build machine, and any compile errors must be fixed before signing.
- **The plugin store and bundled plugins come from a separate repository.** Build machines must
  check out `onlyoffice.github.io` from lab02 (`ration/ration-docs-onlyoffice.github.io`), and the
  build must set `desktop-marketplace="1"` to include the plugin manager.
- **Still open:**
  - The macOS font-weight change (#1718) is not in this release.
  - F11 full screen on Windows and Linux.
  - A choice of CSV delimiter on save (#83).

## Reported issues fixed in 2026.2.0

- There was no way to choose the language of new documents; Advanced settings now has "Default document language" ([#143](https://github.com/ONLYOFFICE/DesktopEditors/issues/143))
- There was no shortcut to see the word count; Ctrl+Shift+G (Cmd+Shift+G on macOS) now opens Document Info ([#167](https://github.com/ONLYOFFICE/DesktopEditors/issues/167))
- Autofit on a custom-width column measured shortened numbers; now fits in one go ([#182](https://github.com/ONLYOFFICE/DesktopEditors/issues/182))
- On Windows/Linux no key made a new document from an editor; Ctrl+N now creates one of the editor's type ([#200](https://github.com/ONLYOFFICE/DesktopEditors/issues/200))
- Paragraph spacing that LibreOffice puts in the clipboard HTML's style sheet was dropped on paste; it is now applied ([#206](https://github.com/ONLYOFFICE/DesktopEditors/issues/206))
- On macOS there was no practical key to edit a filled cell (F2 needs fn); Control+U now opens the cell editor, as in Excel for Mac ([#247](https://github.com/ONLYOFFICE/DesktopEditors/issues/247))
- A page larger than the sheet lost its bottom when printed; now shrunk to fit ([#281](https://github.com/ONLYOFFICE/DesktopEditors/issues/281))
- Wrapped text taller than its cell was centred and clipped; it now shows from its first line ([#307](https://github.com/ONLYOFFICE/DesktopEditors/issues/307))
- Pptx symbols (a:sym, Insert > Symbol) drew as unrelated glyphs; now as PowerPoint draws them ([#328](https://github.com/ONLYOFFICE/DesktopEditors/issues/328))
- A copied display formula pasted left-aligned; it now keeps its justification ([#334](https://github.com/ONLYOFFICE/DesktopEditors/issues/334))
- Pptx symbols (a:sym, Insert > Symbol) drew as unrelated glyphs; now as PowerPoint draws them ([#344](https://github.com/ONLYOFFICE/DesktopEditors/issues/344))
- Edit > Undo/Redo of the macOS menu now reach the document ([#388](https://github.com/ONLYOFFICE/DesktopEditors/issues/388))
- The desktop editors ignored the OS Region when picking their default unit; a US Region now starts in inches ([#432](https://github.com/ONLYOFFICE/DesktopEditors/issues/432))
- A csv with more than 1048576 rows opened cut short without a word; now it warns ([#482](https://github.com/ONLYOFFICE/DesktopEditors/issues/482))
- Fit-to-page PDF of a sheet filtered in this session shrank as if hidden rows printed ([#531](https://github.com/ONLYOFFICE/DesktopEditors/issues/531))
- A new workbook saved as PDF was squeezed onto one page; now uses its page setup ([#547](https://github.com/ONLYOFFICE/DesktopEditors/issues/547))
- MacOS printed on the default sheet whatever the page size; now on the page's own size ([#560](https://github.com/ONLYOFFICE/DesktopEditors/issues/560))
- A math i/j under an accent (\vec, \dot) drew blank or as a stray glyph without Cambria Math; now a dotless i/j ([#565](https://github.com/ONLYOFFICE/DesktopEditors/issues/565))
- PDF export recompressed JPEGs that carry Photoshop/XMP metadata at quality 85; they are now embedded as they are ([#572](https://github.com/ONLYOFFICE/DesktopEditors/issues/572))
- A docx page background was shown although settings.xml has no w:displayBackgroundShape, and saving added the flag; the binary now carries the flag ([#615](https://github.com/ONLYOFFICE/DesktopEditors/issues/615))
- Insert > Image > From file took one picture at a time in the desktop app; several picked at once are now all inserted ([#617](https://github.com/ONLYOFFICE/DesktopEditors/issues/617))
- Opening a template starts a new untitled document instead of editing the template ([#619](https://github.com/ONLYOFFICE/DesktopEditors/issues/619))
- On Linux a window could open under a top panel; it now starts inside the work area ([#661](https://github.com/ONLYOFFICE/DesktopEditors/issues/661))
- About showed "deb" (or nothing) for Flatpak, Snap and AppImage builds; on Linux it now names the sandbox the app runs in ([#669](https://github.com/ONLYOFFICE/DesktopEditors/issues/669))
- The macOS About window had no way to report a problem either; it now has a "Report an issue" link ([#670](https://github.com/ONLYOFFICE/DesktopEditors/issues/670))
- On Linux with QT_SCALE_FACTOR the editor filled only the top-left part of its panel ([#694](https://github.com/ONLYOFFICE/DesktopEditors/issues/694))
- Save As no longer truncates a dotted name or quietly renames a typed extension ([#706](https://github.com/ONLYOFFICE/DesktopEditors/issues/706))
- On macOS the back/forward side buttons of a mouse closed the tab under the pointer; only the middle button does now ([#766](https://github.com/ONLYOFFICE/DesktopEditors/issues/766))
- Linux Save As hands GTK and the portal the name as UTF-8, so a Chinese name no longer aborts or garbles ([#790](https://github.com/ONLYOFFICE/DesktopEditors/issues/790))
- On macOS Ctrl+Cmd+F did not enter full screen; Window > Enter Full Screen (Ctrl+Cmd+F) now does ([#858](https://github.com/ONLYOFFICE/DesktopEditors/issues/858))
- Zooming out in documents, presentations and PDFs stopped at 50% and zooming in from below jumped to 50%; the steps now go down to 10% ([#870](https://github.com/ONLYOFFICE/DesktopEditors/issues/870))
- A window resize in a slide show closed the open video player (and stopped the video); now it is moved ([#878](https://github.com/ONLYOFFICE/DesktopEditors/issues/878))
- A plain Save to CSV exported the sheet active at open, not the one on screen ([#902](https://github.com/ONLYOFFICE/DesktopEditors/issues/902))
- Linux image dialog hid Photo.JPG - GTK filter patterns are now matched case-insensitively ([#905](https://github.com/ONLYOFFICE/DesktopEditors/issues/905))
- Typed « and » got no non-breaking spaces in French; now «nbsp text nbsp» ([#925](https://github.com/ONLYOFFICE/DesktopEditors/issues/925))
- Plain text with lone-CR line ends pasted as one run-together paragraph; now one paragraph per line ([#927](https://github.com/ONLYOFFICE/DesktopEditors/issues/927))
- An idle document no longer wakes the renderer on every animation frame ([#1000](https://github.com/ONLYOFFICE/DesktopEditors/issues/1000))
- The Windows installer registers every template type, so Default apps lists them ([#1004](https://github.com/ONLYOFFICE/DesktopEditors/issues/1004))
- Chinese text in WMF/EMF "ANSI" fonts drew as Latin-1 garbage; it now follows the system code page ([#1031](https://github.com/ONLYOFFICE/DesktopEditors/issues/1031))
- The Recover list on the start page gave names only; each file now shows when its last change was autosaved ([#1144](https://github.com/ONLYOFFICE/DesktopEditors/issues/1144))
- A Google Docs/Sheets/Slides link opened Google's editor in a tab; it now goes to the browser ([#1167](https://github.com/ONLYOFFICE/DesktopEditors/issues/1167))
- Touchpad scrolling in a document dropped the sub-pixel part of every event; it is now carried over ([#1194](https://github.com/ONLYOFFICE/DesktopEditors/issues/1194))
- On macOS a new UI language reached new editors only after a restart; they now open in it at once ([#1230](https://github.com/ONLYOFFICE/DesktopEditors/issues/1230))
- Pasting web content with images no longer freezes the editor while they download ([#1233](https://github.com/ONLYOFFICE/DesktopEditors/issues/1233))
- Ctrl+Q did nothing on Linux; it now quits the app, asking about unsaved documents ([#1270](https://github.com/ONLYOFFICE/DesktopEditors/issues/1270))
- A missing GSettings schema killed the app when it showed a notification on GNOME/Cinnamon; now the setting is read only if installed ([#1433](https://github.com/ONLYOFFICE/DesktopEditors/issues/1433))
- A Last Resort font installed by the user took every fallback range; it is now never picked for missing glyphs ([#1450](https://github.com/ONLYOFFICE/DesktopEditors/issues/1450))
- Linux "auto" interface scaling follows the desktop's fractional scale ([#1468](https://github.com/ONLYOFFICE/DesktopEditors/issues/1468))
- CJK punctuation fallback on Linux took a TC/HK face (centered 。); Simplified Chinese faces now win ([#1470](https://github.com/ONLYOFFICE/DesktopEditors/issues/1470))
- Save of a csv/tsv file with several sheets dropped every sheet but the active one without a word; it now asks first ([#1490](https://github.com/ONLYOFFICE/DesktopEditors/issues/1490))
- Media player data says whether a slide show is running ([#1491](https://github.com/ONLYOFFICE/DesktopEditors/issues/1491))
- A pinned recent file could vanish from Recent or show twice; pinned entries now stay once at the top ([#1513](https://github.com/ONLYOFFICE/DesktopEditors/issues/1513))
- Highlight in the selection now goes into the updated/new style ([#1568](https://github.com/ONLYOFFICE/DesktopEditors/issues/1568))
- There was no setting to stop the start page keeping recent files; "Keep a list of recent files" now turns it off and clears it ([#1594](https://github.com/ONLYOFFICE/DesktopEditors/issues/1594))
- Cmd+click adds/removes an item in multi-select lists on macOS ([#1655](https://github.com/ONLYOFFICE/DesktopEditors/issues/1655))
- AVIF pictures were dropped from docx/xlsx/pptx on save; their bytes are now kept ([#1664](https://github.com/ONLYOFFICE/DesktopEditors/issues/1664))
- Print preview and web PDF use the same slides as the desktop print ([#1672](https://github.com/ONLYOFFICE/DesktopEditors/issues/1672))
- With Flatpak's network permission off each file opened in a new instance; the instance socket now lives in the shared runtime folder ([#1710](https://github.com/ONLYOFFICE/DesktopEditors/issues/1710))
- A copied picture reached other apps only as HTML; it now also goes out as image/png ([#1760](https://github.com/ONLYOFFICE/DesktopEditors/issues/1760))
- A user name with a comma was refused, and on macOS '&', '#', '+' or '%' cut or broke it in the editors; both now arrive intact ([#1829](https://github.com/ONLYOFFICE/DesktopEditors/issues/1829))
- A closed document tab could not be brought back; Ctrl+Shift+T (Shift+Cmd+T on macOS) now reopens the most recently closed one ([#1847](https://github.com/ONLYOFFICE/DesktopEditors/issues/1847))
- A video's own mute/volume now reaches the player when it is opened by selecting or hovering it ([#1922](https://github.com/ONLYOFFICE/DesktopEditors/issues/1922))
- In a slide show the video controls show only while the mouse is over the video ([#1942](https://github.com/ONLYOFFICE/DesktopEditors/issues/1942))
- Play/pause/seek in the presenter's video player now drive the slide show's player ([#1943](https://github.com/ONLYOFFICE/DesktopEditors/issues/1943))
- Landscape documents print shrunk onto a portrait sheet on Linux CUPS printers ([#1947](https://github.com/ONLYOFFICE/DesktopEditors/issues/1947))
- Document the machine-wide plugin settings for administrators ([#1967](https://github.com/ONLYOFFICE/DesktopEditors/issues/1967))
- A save to a share that fails part-way leaves the document as it was and says so ([#2000](https://github.com/ONLYOFFICE/DesktopEditors/issues/2000))
- PDF bookmarks from headings now point at the right pages when only a page range is saved, and titles lose the paragraph mark ([#2010](https://github.com/ONLYOFFICE/DesktopEditors/issues/2010))
- The Windows installer no longer associates file types the user unticked ([#2031](https://github.com/ONLYOFFICE/DesktopEditors/issues/2031))
- LaTeX -> Professional no longer hangs on \thinsp/\nbsp, and reads \, \: \; ([#2062](https://github.com/ONLYOFFICE/DesktopEditors/issues/2062))
- The French punctuation autocorrect (non-breaking spaces before : ; ? !) could not be turned off; the api can now switch it ([#2075](https://github.com/ONLYOFFICE/DesktopEditors/issues/2075))
- A document's default paragraph direction (docDefaults w:bidi) can be set, and re-lays out every paragraph ([#2090](https://github.com/ONLYOFFICE/DesktopEditors/issues/2090))
- Dropping a document onto an open editor now opens it in a new tab ([#2095](https://github.com/ONLYOFFICE/DesktopEditors/issues/2095))
- Removing a plugin no longer reports success after a partial or failed removal ([#2107](https://github.com/ONLYOFFICE/DesktopEditors/issues/2107))
- Slides print fitted to the paper on macOS instead of cut off on the right ([#2110](https://github.com/ONLYOFFICE/DesktopEditors/issues/2110))
- Shift pressed during a row/column drag now inserts between rows (as Excel) instead of being ignored ([#2119](https://github.com/ONLYOFFICE/DesktopEditors/issues/2119))
- An inserted video takes the video's aspect ratio instead of the square placeholder poster's ([#2131](https://github.com/ONLYOFFICE/DesktopEditors/issues/2131))
- Document macros ran on a click and custom functions saved in a file ran on open, without the macros warning; both now wait for the user's consent ([#2188](https://github.com/ONLYOFFICE/DesktopEditors/issues/2188))
- The start page no longer fetches ONLYOFFICE's template gallery on every launch ([#2235](https://github.com/ONLYOFFICE/DesktopEditors/issues/2235))
- A new document uses the blank template of the user's language, not always en-US ([#2271](https://github.com/ONLYOFFICE/DesktopEditors/issues/2271))
- ROW/ROWS/COLUMN/COLUMNS over INDIRECT or OFFSET no longer report a false circular reference ([#2288](https://github.com/ONLYOFFICE/DesktopEditors/issues/2288))
- Wingdings symbols drew blank or as a stray glyph on Linux; they now draw from OpenSymbol ([#2318](https://github.com/ONLYOFFICE/DesktopEditors/issues/2318))
- Scrolling a document repainted at most every 40ms (20-25fps); a scroll now repaints on the next frame ([#2375](https://github.com/ONLYOFFICE/DesktopEditors/issues/2375))
- Elbow connector between aligned anchors is routed as an elbow, not a straight line ([#2428](https://github.com/ONLYOFFICE/DesktopEditors/issues/2428))
- Keep placeholder idx through save; no duplicate idx on a layout ([#2448](https://github.com/ONLYOFFICE/DesktopEditors/issues/2448))
- Editing a gradient stop no longer strips every stop's own transparency ([#2455](https://github.com/ONLYOFFICE/DesktopEditors/issues/2455))
- Turning a sorted table's header row off/on keeps its sortState on the data rows ([#2459](https://github.com/ONLYOFFICE/DesktopEditors/issues/2459))
- Tool calls sent with finish_reason, or several at once, are no longer dropped ([#2461](https://github.com/ONLYOFFICE/DesktopEditors/issues/2461))
- A comment added from a macro (ApiRange.AddComment etc.) showed twice in the Comments panel; it is announced once now (backport of upstream 551cb909f3) ([#2463](https://github.com/ONLYOFFICE/DesktopEditors/issues/2463))
- Home/End in the formula bar left the editor caret behind; Alt+Enter now breaks at the caret ([#2467](https://github.com/ONLYOFFICE/DesktopEditors/issues/2467))
- The left column of a 2-column section after a continuous break could vanish from page 1; stepping back to a later column no longer resets the section (backport of upstream 0f67b0544a) ([#2469](https://github.com/ONLYOFFICE/DesktopEditors/issues/2469))
- FontDescriptor FontBBox/Ascent/Descent/CapHeight of embedded TrueType subsets were in font units; now in glyph space (1/1000 em) ([#2471](https://github.com/ONLYOFFICE/DesktopEditors/issues/2471))
- Don't flush a null cookie manager on shutdown ([#2476](https://github.com/ONLYOFFICE/DesktopEditors/issues/2476))
- Don't crash saving a PDF with a CID font that has no CMap ([#2479](https://github.com/ONLYOFFICE/DesktopEditors/issues/2479))
- A save whose replace breaks half-way no longer strands the new content; stale save temps are removed ([#2480](https://github.com/ONLYOFFICE/DesktopEditors/issues/2480))
- Keep each comment's paraId when re-saving, so threads survive ([#2482](https://github.com/ONLYOFFICE/DesktopEditors/issues/2482))
- A pivot change that throws no longer suspends recalculation for the session ([#2485](https://github.com/ONLYOFFICE/DesktopEditors/issues/2485))
- FreeType's FTC_* and TT_* entry points were still exported from libgraphics.so ([#2490](https://github.com/ONLYOFFICE/DesktopEditors/issues/2490))
- On Linux a window moved to a screen of another scale kept its old chrome size next to a re-zoomed editor; it is now re-scaled ([#2501](https://github.com/ONLYOFFICE/DesktopEditors/issues/2501))
- Deleting all text in a shape no longer resets its font size and bullets ([#2502](https://github.com/ONLYOFFICE/DesktopEditors/issues/2502))
- An xkb region written as an adjective ("English (Australian)") now gives that region ([#2503](https://github.com/ONLYOFFICE/DesktopEditors/issues/2503))
- A grayscale JPEG 2000 image without /ColorSpace rendered black; its colour space now comes from the JPX header ([#2506](https://github.com/ONLYOFFICE/DesktopEditors/issues/2506))
- Write numbering.xml in schema order, so lists survive in Word ([#2507](https://github.com/ONLYOFFICE/DesktopEditors/issues/2507))
- The caret stops blinking when the OS has cursor blinking turned off ([#2508](https://github.com/ONLYOFFICE/DesktopEditors/issues/2508))
- Paste-options button no longer lingers after the pasted object is deselected ([#2517](https://github.com/ONLYOFFICE/DesktopEditors/issues/2517))
- Know the TSV format id in the desktop controller ([#2521](https://github.com/ONLYOFFICE/DesktopEditors/issues/2521))
- A relative path given to a second instance now opens relative to where it was typed ([#2523](https://github.com/ONLYOFFICE/DesktopEditors/issues/2523))
- Mistral no longer rejects a thread that contains a tool call ([#2524](https://github.com/ONLYOFFICE/DesktopEditors/issues/2524))
- A plugin closed mid-stream no longer leaves the editor locked; its open group is ended, text kept ([#2525](https://github.com/ONLYOFFICE/DesktopEditors/issues/2525))
- Redaction left shaded shapes, frames and soft-masked images behind ([#2526](https://github.com/ONLYOFFICE/DesktopEditors/issues/2526))
- Don't abort on "--view path" and other malformed launch arguments ([#2527](https://github.com/ONLYOFFICE/DesktopEditors/issues/2527))
- On macOS, tabs already open take the new theme's background on a theme change ([#2528](https://github.com/ONLYOFFICE/DesktopEditors/issues/2528))
- Serbian (Latin) no longer hyphenates before a word-final lj/nj ([#2533](https://github.com/ONLYOFFICE/DesktopEditors/issues/2533))
- Every dark-type theme, theme-night included, gets the dark message box ([#2537](https://github.com/ONLYOFFICE/DesktopEditors/issues/2537))
- Hangul no longer drawn with a Chinese glyph from Heiti's legacy cmap ([#2542](https://github.com/ONLYOFFICE/DesktopEditors/issues/2542))
- Switching spelling language detection off now reaches open documents ([#2543](https://github.com/ONLYOFFICE/DesktopEditors/issues/2543))
- Uppercase Cyrillic "СС" is read as seconds in Russian number formats ([#2545](https://github.com/ONLYOFFICE/DesktopEditors/issues/2545))
- One non-UTF-8 byte garbled every non-ASCII character of a UTF-8 CSV ([#2546](https://github.com/ONLYOFFICE/DesktopEditors/issues/2546))
- Don't flock documents in iCloud / File Provider folders on macOS ([#2547](https://github.com/ONLYOFFICE/DesktopEditors/issues/2547))
- A logout vetoed for unsaved documents now shows the save dialogs ([#2553](https://github.com/ONLYOFFICE/DesktopEditors/issues/2553))
- Slideshow no longer clips text that sticks out of tight exact line spacing ([#2554](https://github.com/ONLYOFFICE/DesktopEditors/issues/2554))
- Rows hidden down to the end of the sheet came back visible after an ODS save; they now stay hidden ([#2556](https://github.com/ONLYOFFICE/DesktopEditors/issues/2556))
- Portuguese and other regional keyboards on macOS no longer get the wrong country ([#2559](https://github.com/ONLYOFFICE/DesktopEditors/issues/2559))
- Accent picked from the macOS accent menu doubled in spreadsheet text boxes (eé); it now replaces the letter ([#2560](https://github.com/ONLYOFFICE/DesktopEditors/issues/2560))
- An image drag that crossed a document without dropping no longer splits the paragraph at the next click ([#2561](https://github.com/ONLYOFFICE/DesktopEditors/issues/2561))

## Defects we found ourselves

- **RD-0001** Csv kept one row past 1048576, csv -> xlsx ignored the row limit and said nothing; both now stop at 1048576 and return ROWLIMITS
- **RD-0002** MacOS started Sparkle with no appcast and offered "Check for Updates..."; the updater and its menu item are gone
- **RD-0003** Special paste with no clipboard data threw a TypeError; it now stops after reporting empty data
- **RD-0004** PDF export read one byte past the TrueType subset's glyph flags; the closing loca entry no longer consults them
- **RD-0005** A broken MNG picture freed libmng's decoder from its own error callback (use after free, double free); the callback now only reports the error
- **RD-0006** JasPer streams were closed through function pointers in a stack object already out of scope; the CxFileJas now outlives jas_stream_close
- **RD-0007** A .doc whose document properties run past the table stream read up to 700 bytes beyond the DOP buffer; the bounds now use the bytes actually read
- **RD-0008** The format detector ran strstr over zip parts that were not NUL-terminated; parts read from an archive now end in a zero byte
- **RD-0009** VBA module decompression read past the end of the compressed stream; tokens and stored chunks are now bounded by the input
- **RD-0010** A .doc style whose name or UPX lengths run past the style's bytes copied heap memory into the style; the STD's variable part is now read within its size
- **RD-0011** ODS cells of type scientific/fraction/date-time read their number format id from past the end of a global table; out-of-range types now map to 0
- **RD-0012** Saving a presentation with notes but no notes-master theme relation crashed x2t; an empty theme list now falls back to the first theme
- **RD-0013** RTF export wrote stray stack bytes after a list bullet; the list text is now exactly the bullet
- **RD-0014** Excel 2003 XML rows were not yet in the sheet while being read, so merged cells crashed the first row and went into the previous row otherwise; the row is now the sheet's last row while it is read
- **RD-0015** A .ppt with an inline fill picture in a shape's properties crashed x2t; a blip read without a temp folder is now stepped over
- **RD-0016** Saving a 3-D surface chart without band formats crashed x2t; c:bandFmts is now written only when present
- **RD-0017** An ODP table in a document without office:automatic-styles crashed x2t on open; the default cell style is now created only when it can be stored
- **RD-0018** EMF to SVG wrote through a null pointer for an empty text record with character spacing; such a text now gets a single x coordinate

---

# Ration Docs Desktop 2026.1.0

First release of Ration Docs Desktop, a hard fork of ONLYOFFICE Desktop Editors 9.4.0.

**macOS (Apple Silicon) only.** Linux and Windows are not in this release; see
*Known limitations* below.

## What this release is

The fork exists to fix defects, not to add features. There are no new features in
2026.1.0. What it has is **fixes for 84 reported upstream issues**, plus **20
further defects found while investigating them** that have no upstream report -
weighted heavily towards the two categories that cost users work: silent data
loss, and crashes.

The list below is grouped by what the defect did, and is drawn from the fork's
triage record. It carries 91 entries against the 84 figure above: the registry in
`FIXES.md` counts only issues a commit explicitly claims, while a few entries were
fixed as part of a commit that named a different issue. `FIXES.md` lists those 11
by number so the gap is visible rather than glossed over.

Every fix was reproduced before it was written and demonstrated afterwards. Where
something could not be demonstrated, it was not claimed - the accompanying
`UPSTREAM_TRIAGE.md` records what was root-caused but deliberately left alone, and
why.

## Fixes

**84 upstream issues** have at least one fix commit, and **26 further defects** were
found and fixed while working on them - 110 in all. 48 of the 84 have a test in
`fork-fix-tests/` that fails against the commit before the fix; the remaining 36
rest on their commit message, and `UPSTREAM_TRIAGE.md` says which is which rather
than blurring the two.

### Where the work landed

| Repository | Upstream issues | With a test | Found in passing |
|---|---|---|---|
| [`sdkjs`](https://github.com/Stackchase-Limited/ration-docs-sdkjs) | 29 | 18 | 7 |
| [`core`](https://github.com/Stackchase-Limited/ration-docs-core) | 22 | 13 | 4 |
| [`desktop-apps`](https://github.com/Stackchase-Limited/ration-docs-desktop-apps) | 22 | 11 | 4 |
| [`desktop-sdk`](https://github.com/Stackchase-Limited/ration-docs-desktop-sdk) | 10 | 4 | 7 |
| [`web-apps`](https://github.com/Stackchase-Limited/ration-docs-web-apps) | 3 | 1 | 1 |
| [`build_tools`](https://github.com/Stackchase-Limited/ration-docs-build-tools) | 2 | 2 | 3 |
| `onlyoffice.github.io` (plugins, not forked) | 1 | 0 | 0 |

The repository column sums to more than 84 because a single issue often spans two:
a spreadsheet bug fixed in `sdkjs` with the save path corrected in `core`, or a
dialog in `desktop-apps` whose CEF side is in `desktop-sdk`. The 84 is the count of
distinct issues.

`FIXES.md` is the full registry, one row per issue, generated from git history and
the contents of `fork-fix-tests/` rather than kept by hand - the hand-kept list in
`UPSTREAM_TRIAGE.md` had drifted eight entries behind its own commits by the time
that was noticed.

### Data loss and corruption (24)

- `HYPERLINK()` cells lost their link when copied to another application. ([#2256](https://github.com/ONLYOFFICE/DesktopEditors/issues/2256))
- Local save reported success when the write had failed - silent data loss. ([#2081](https://github.com/ONLYOFFICE/DesktopEditors/issues/2081))
- An invalid user name silently discarded every other settings change. ([#1669](https://github.com/ONLYOFFICE/DesktopEditors/issues/1669))
- Save As PDF kept the `.pptx` name and the write destroyed the original. ([#2429](https://github.com/ONLYOFFICE/DesktopEditors/issues/2429))
- A custom theme's colours lost to the built-in palette on specificity and source order. ([#1948](https://github.com/ONLYOFFICE/DesktopEditors/issues/1948))
- Ctrl+S with a cell in edit mode saved nothing and lost the typed value. ([#963](https://github.com/ONLYOFFICE/DesktopEditors/issues/963))
- A save reported success before the bytes reached the disk, so a power cut lost the document. ([#2056](https://github.com/ONLYOFFICE/DesktopEditors/issues/2056))
- A throw inside a row or column structure change left recalculation suspended for the rest of the session, so every formula went blank with no error shown (hardening - not a confirmed reproduction, see below). ([#2443](https://github.com/ONLYOFFICE/DesktopEditors/issues/2443))
- Times written to CSV had the wrong meridiem at noon and midnight, and lost a second on roughly half of all times. ([#2280](https://github.com/ONLYOFFICE/DesktopEditors/issues/2280))
- `wcstod` accepts hexadecimal float literals, so any `0x...` CSV value was imported as a number and the text discarded. ([#2301](https://github.com/ONLYOFFICE/DesktopEditors/issues/2301))
- The file name field of a header or footer was blank in an exported PDF - the converter has no DocInfo to resolve it from. ([#2275](https://github.com/ONLYOFFICE/DesktopEditors/issues/2275))
- *No upstream issue.* The last row of a CSV lost its trailing delimiters, so a reader counting fields dropped its final columns. ([#2022](https://github.com/ONLYOFFICE/DesktopEditors/issues/2022))
- Every theme's window border was below the 3:1 contrast threshold, two of them at 1.15 - effectively invisible (border only; drop shadows need a Wayland port). ([#2229](https://github.com/ONLYOFFICE/DesktopEditors/issues/2229))
- Every CSV ending in a newline gained an empty trailing row: the string was sized in bytes, so the end-of-data guard fired on a file that ended cleanly. ([#2209](https://github.com/ONLYOFFICE/DesktopEditors/issues/2209))
- A symbolic retry lost its `+ 0xF000`, so Wingdings and Symbol text inside EMF/WMF metafiles was drawn in a substituted font (core half only). ([#2195](https://github.com/ONLYOFFICE/DesktopEditors/issues/2195))
- A failed `fork` or `execve` returned 0, so a save reported success for a conversion that never ran and the document was marked clean over lost work. ([#2202](https://github.com/ONLYOFFICE/DesktopEditors/issues/2202))
- A macro bound to a shape was silently unbound when the workbook was saved to ODS - while `jsaProject.bin` was still written, so the macro stayed in the dialog with nothing attached. ([#2187](https://github.com/ONLYOFFICE/DesktopEditors/issues/2187))
- An encoding number sent by the editor indexed past a 54-entry table: 65001 - the Windows code page for UTF-8, and what our own documented API tells callers to send - killed the converter outright, and 1252 returned success with a blank spreadsheet. ([#1359](https://github.com/ONLYOFFICE/DesktopEditors/issues/1359))
- Copying one cell whose displayed text is empty replaced the system clipboard with an item carrying **no text flavour at all** - a falsy test where the contract is presence (the in-app half of the report is not explained by this; see the commit). ([#1364](https://github.com/ONLYOFFICE/DesktopEditors/issues/1364))
- One character XML forbids - pasted, never from a file - made the whole slide it sat on come back blank, because the run-text escaper handled the five entities and nothing else. ([#139](https://github.com/ONLYOFFICE/DesktopEditors/issues/139))
- Rows could be hidden but never shown: the whole-sheet branch of `setRowHidden` was an empty `// ToDo`, so a file with `zeroHeight="1"` opened unreadable with no way back. ([#2071](https://github.com/ONLYOFFICE/DesktopEditors/issues/2071))
- The `.~lock` marker was written on a share but never read - three defects, all ending in "free, go ahead and write", so two people could edit one file. ([#1362](https://github.com/ONLYOFFICE/DesktopEditors/issues/1362))
- Every CSV over ~500KB was silently corrupted at each buffer compaction: a delimiter, quote or newline lost its meaning and cells merged (the OOM half is not fixed). ([#1297](https://github.com/ONLYOFFICE/DesktopEditors/issues/1297))
- Every built-in number format was discarded on CSV export - percentages, currencies and fractions written as raw values (core half). ([#1372](https://github.com/ONLYOFFICE/DesktopEditors/issues/1372))

### Crashes and freezes (8)

- Ctrl+Home selected A1 but did not scroll when panes were frozen. ([#2398](https://github.com/ONLYOFFICE/DesktopEditors/issues/2398))
- "Install plugin manually" opened the marketplace page instead of a picker. ([#2129](https://github.com/ONLYOFFICE/DesktopEditors/issues/2129))
- A `+` in the install path decoded to a space, so the font wasm never loaded. ([#2222](https://github.com/ONLYOFFICE/DesktopEditors/issues/2222))
- The file dialog froze on Wayland: an in-process GTK chooser inside an XWayland Qt app. ([#2168](https://github.com/ONLYOFFICE/DesktopEditors/issues/2168))
- A Big5 subtable was recorded as Unicode coverage, so Heiti won the Hangul fallback and drew Chinese ideographs. ([#2433](https://github.com/ONLYOFFICE/DesktopEditors/issues/2433))
- Store-installed fonts were missed: the profile directory was guessed from the account name. ([#1954](https://github.com/ONLYOFFICE/DesktopEditors/issues/1954))
- Forcing the xcb platform plugin on a Wayland session with no X display segfaulted instead of saying so (the crash only; Wayland support is a port). ([#2105](https://github.com/ONLYOFFICE/DesktopEditors/issues/2105))
- AutoFit on a few columns froze the app: the scan walked the sheet's row extent rather than the column's cells - 4,194,304 visits where 400 were needed (see the approval list, item 9, for the row-height change it makes). ([#1018](https://github.com/ONLYOFFICE/DesktopEditors/issues/1018))

### Security and file locking (6)

- File names were interpreted as HTML in the recent-files list (injection). ([#1720](https://github.com/ONLYOFFICE/DesktopEditors/issues/1720))
- No `.~lock` marker on network shares, so a second user got no warning. ([#2383](https://github.com/ONLYOFFICE/DesktopEditors/issues/2383))
- A reference to a password-protected workbook showed `#REF!`; no password could be supplied and the failure reason never reached JS. ([#2252](https://github.com/ONLYOFFICE/DesktopEditors/issues/2252))
- A macro writing to a locked cell returned false in silence, so it looked as though macros no longer ran (part). ([#2234](https://github.com/ONLYOFFICE/DesktopEditors/issues/2234))
- Two AI providers reported every failure as "Invalid URL", sending users to correct an address that was right (the CORS root cause is untouched). ([#2268](https://github.com/ONLYOFFICE/DesktopEditors/issues/2268))
- *No upstream issue.* A zero-length converter result was reported as a successful save, because `StartWrite()` cannot answer whether the locker ever locked. (*no upstream issue*)

### Printing, rendering and layout (9)

- A leaked non-Unicode charmap turned accented characters into other glyphs. ([#2155](https://github.com/ONLYOFFICE/DesktopEditors/issues/2155))
- The GUI waited on a CUPS connect timeout before appearing, for a printer name nothing reads. ([#2312](https://github.com/ONLYOFFICE/DesktopEditors/issues/2312))
- The interface language was never declared to the renderer, so Simplified Chinese was drawn in Traditional forms. ([#2199](https://github.com/ONLYOFFICE/DesktopEditors/issues/2199))
- A copied bullet reached the plain-text clipboard flavour as a raw symbol-font codepoint, with no font to give it meaning. ([#2250](https://github.com/ONLYOFFICE/DesktopEditors/issues/2250))
- Four ways a trendline equation printed something other than the line it fitted, worst an int32 wrap that turned a slope of 1e6 into 141006.5408 (part). ([#2245](https://github.com/ONLYOFFICE/DesktopEditors/issues/2245))
- Colour printing was decided from one PPD keyword drivers do not agree on, so colour printers were offered black and white only. ([#2147](https://github.com/ONLYOFFICE/DesktopEditors/issues/2147))
- The print dialog resolved a standard paper name then threw it away, so CUPS fell back to nameless custom media with no margins. ([#2161](https://github.com/ONLYOFFICE/DesktopEditors/issues/2161))
- A document written in Verdana spilled a full page onto a second, because Verdana had no metric substitute and the picker fell through to Open Sans - 12% taller per line. ([#1570](https://github.com/ONLYOFFICE/DesktopEditors/issues/1570))
- A PDF carrying an outline opened with the bookmarks pane shut - the catalog was pinned to `/UseNone` (core half). ([#1855](https://github.com/ONLYOFFICE/DesktopEditors/issues/1855))

### Correctness and behaviour (44)

- Home key put the caret on the previous visual line in wrapped cell text. ([#2082](https://github.com/ONLYOFFICE/DesktopEditors/issues/2082))
- DATE fields never refreshed on open; auto date/time mixed local date with UTC hour. ([#1482](https://github.com/ONLYOFFICE/DesktopEditors/issues/1482))
- GTK dialogs were never told the app's theme, so Save As stayed light. ([#2266](https://github.com/ONLYOFFICE/DesktopEditors/issues/2266))
- Exporting the focused sheet to CSV exported whatever sheet was active at open. ([#1839](https://github.com/ONLYOFFICE/DesktopEditors/issues/1839))
- A formula-based conditional format rule made the spreadsheet uneditable. ([#2418](https://github.com/ONLYOFFICE/DesktopEditors/issues/2418))
- A spreadsheet reopened at A1 instead of where the user left it (scroll only). ([#1868](https://github.com/ONLYOFFICE/DesktopEditors/issues/1868))
- A defined name in a VLOOKUP dependency threw and forced the document read-only. ([#2400](https://github.com/ONLYOFFICE/DesktopEditors/issues/2400))
- A synthetic resize event per intermediate size, flashing the grid. ([#2018](https://github.com/ONLYOFFICE/DesktopEditors/issues/2018))
- Spanish spell-check worked only for es-ES; 20 other locales were unmapped. ([#459](https://github.com/ONLYOFFICE/DesktopEditors/issues/459))
- macOS Control+click opened no context menu in any editor. ([#2262](https://github.com/ONLYOFFICE/DesktopEditors/issues/2262))
- Copying a sheet to a new file opened the whole original workbook; the selected-sheets binary was written only for cloud-crypto documents. ([#2278](https://github.com/ONLYOFFICE/DesktopEditors/issues/2278))
- An unmapped format id made a nameless filter, and the portal then refused the whole Save As dialog - the document could not be saved. ([#2243](https://github.com/ONLYOFFICE/DesktopEditors/issues/2243))
- *Feature.* The default AutoFit for a new text box is now a setting, so a box keeps the size it was drawn at. ([#2442](https://github.com/ONLYOFFICE/DesktopEditors/issues/2442))
- A folder named with an emoji segfaulted the GTK file chooser: libgraphics exported its bundled FreeType 2.10.4 and cairo bound to it. ([#2136](https://github.com/ONLYOFFICE/DesktopEditors/issues/2136))
- The executable exported its statically linked libstdc++, so the system one bound to it and aborted before `main`. ([#1748](https://github.com/ONLYOFFICE/DesktopEditors/issues/1748))
- A failed connection was reported as "Invalid URL", sending users to correct an address that was already right. ([#2444](https://github.com/ONLYOFFICE/DesktopEditors/issues/2444))
- A FILTER returning from no-match filled only its first cell: the spill pass was scheduled on a flag recalculation had already cleared. ([#2426](https://github.com/ONLYOFFICE/DesktopEditors/issues/2426))
- A relative file hyperlink was handed to the shell unresolved, so nothing opened and nothing said why. ([#2293](https://github.com/ONLYOFFICE/DesktopEditors/issues/2293))
- The interface language came from `LANG` alone, ignoring `LC_ALL` and `LC_MESSAGES` (language half only). ([#2302](https://github.com/ONLYOFFICE/DesktopEditors/issues/2302))
- The desktop entry had no localised `Name`, so launchers running in a locale could not find the application. ([#2395](https://github.com/ONLYOFFICE/DesktopEditors/issues/2395))
- Nothing told Qt which desktop entry this is, so a Wayland panel had no `app_id` to match and showed no icon. ([#2397](https://github.com/ONLYOFFICE/DesktopEditors/issues/2397))
- Chat messages took their direction from the interface, so Arabic replies were laid out left to right. ([#2435](https://github.com/ONLYOFFICE/DesktopEditors/issues/2435))
- Pasting a paragraph or a table row reused the source's `w14:paraId`, so the saved docx carried ids that must be unique on up to five paragraphs (part of #2368 only - see below). ([#2368](https://github.com/ONLYOFFICE/DesktopEditors/issues/2368))
- Save As closed the whole application when the folder held a file with an emoji in its name - the same symbol interposition as #2136, and closed by that fix. ([#2355](https://github.com/ONLYOFFICE/DesktopEditors/issues/2355))
- *Tooling.* A shipped module imported an entry point the kernel beside it did not export and the loader refused to start the app; nothing in the build noticed. The package step now checks the payload's symbol closure. ([#2445](https://github.com/ONLYOFFICE/DesktopEditors/issues/2445))
- The app exited 0 straight after Qt initialised: on a host whose loopback has only 127.0.0.1, it could not bind its per-uid instance address and read that as "somebody else is primary". ([#2434](https://github.com/ONLYOFFICE/DesktopEditors/issues/2434))
- Fourteen bounds checks in the shared binary reader executed a bare `throw;`, which can only call `std::terminate` - any binary that ran the reader past its buffer killed x2t outright (the abort only; the underlying desync is still open, see below). ([#2430](https://github.com/ONLYOFFICE/DesktopEditors/issues/2430))
- `GetLastError()` was read after `CreateMutex` without clearing it first, so a stale `ERROR_ALREADY_EXISTS` made the only running instance decide it was a second one and exit 0. ([#2189](https://github.com/ONLYOFFICE/DesktopEditors/issues/2189))
- A conditional formatting rule loaded from file was built with no parent and no dependencies, so it never evaluated until an edit forced it. ([#2269](https://github.com/ONLYOFFICE/DesktopEditors/issues/2269))
- `correctFromInterface` parsed a conditional formatting formula as locale and assembled it back to locale, so a comma decimal separator was stored and then misread. ([#2328](https://github.com/ONLYOFFICE/DesktopEditors/issues/2328))
- The GTK theme was forced to Adwaita for every dialog, replacing whatever theme the desktop runs. ([#2216](https://github.com/ONLYOFFICE/DesktopEditors/issues/2216))
- A bundled Qt plugin needed Qt Quick, which was not bundled - dead on a machine without system Qt5, and a second QtCore in the process on one with it. ([#2274](https://github.com/ONLYOFFICE/DesktopEditors/issues/2274))
- A chart axis could not be scaled past a million - the clamp was in the spinner, not the engine. ([#2244](https://github.com/ONLYOFFICE/DesktopEditors/issues/2244))
- A dragged tab tore out into a new window the instant the pointer left the strip, in any direction, by any distance. ([#2334](https://github.com/ONLYOFFICE/DesktopEditors/issues/2334))
- The "make me your default" toast had no opt-out and threw the answer away, so it returned every day forever (part). ([#2389](https://github.com/ONLYOFFICE/DesktopEditors/issues/2389))
- One date shown two ways: month-first gave `dd-mmm-yy`, month-second `d-mmm-yy` - and the wider one is where the `#####` came from. ([#2296](https://github.com/ONLYOFFICE/DesktopEditors/issues/2296))
- The style gallery listed Heading 9 first: the sort compared `.Name` on an object that stores `name`, so it was a silent no-op. ([#2324](https://github.com/ONLYOFFICE/DesktopEditors/issues/2324))
- Justify did nothing to East Asian text - gaps were counted only after a space, and a line of CJK has none. ([#2263](https://github.com/ONLYOFFICE/DesktopEditors/issues/2263))
- The retina fill handle could not be grabbed: the hit test was three device pixels flat while the square drawn is far larger (part). ([#2425](https://github.com/ONLYOFFICE/DesktopEditors/issues/2425))
- *No upstream issue.* Number-format padding directives (`_c`, `*c`, `[Red]`) were written into CSV cells as text: Accounting wrote `_ * 8745.00_ `. (*no upstream issue*)
- A pivot table saved to ODS came back as plain cells: we wrote the container and never filled it, and every unset attribute serialised as the literal `--`. ([#2113](https://github.com/ONLYOFFICE/DesktopEditors/issues/2113))
- Copying an image file in a Linux file manager pasted its path as text, because `text/uri-list` was read nowhere in the editor. ([#676](https://github.com/ONLYOFFICE/DesktopEditors/issues/676))
- A saved docx could be detected as a plain zip: zip entry order put `_rels` where libmagic could not find it. ([#1323](https://github.com/ONLYOFFICE/DesktopEditors/issues/1323))
- *No upstream issue.* Our own #2056 flush did not compile on Linux: `G_IS_FILE_DESCRIPTOR_BASED` needs a header in `gio-unix-2.0`, which the build never asked for. (*no upstream issue*)

## Installing

### Linux (arm64)

    sudo apt install ./ration-docs_2026.1.0-1_arm64.deb

Installs to `/opt/ration/docs` with a launcher at `/usr/bin/ration-docs` and a
`ration-docs.desktop` entry. The tarball is the same payload for distributions
where the deb does not apply; unpack it at `/` and it lands in the same places.

Verify the download first:

    sha256sum ration-docs_2026.1.0-1_arm64.deb

### macOS (Apple Silicon)


**This build is not signed or notarised.** There is no Apple Developer ID behind
it, so macOS Gatekeeper will refuse to open it on first launch - typically
*"Ration Docs can't be opened because Apple cannot check it for malicious
software"*, or *"is damaged and can't be opened"* if the quarantine flag is set.

That is expected for this release, not a sign of a corrupted download. To open it:

1. Drag **Ration Docs.app** to `/Applications`.
2. Remove the quarantine attribute:

       xattr -dr com.apple.quarantine "/Applications/Ration Docs.app"

3. Open it normally.

Right-click → **Open** also works on some macOS versions, but clearing the
attribute is more reliable on recent ones.

Verify the download before you run it:

    shasum -a 256 RationDocs-2026.1.0-arm64.dmg

should print

    babe877641a24d8b662e12e022d0ae7391e3f5a44a043c7cfe8c8f999208f16f

An unsigned build means **you are trusting the source of the file**, and nothing
else is vouching for it. If that is not acceptable for your use, wait for a signed
build.

## The artifacts

Two platforms, one commit, one version. Both were rebuilt from a clean object tree
so that every binary carries the same version stamp.

### macOS (Apple Silicon)

| | |
|---|---|
| File | `RationDocs-2026.1.0-arm64.dmg` |
| Size | 761 MB (798,458,195 bytes) |
| SHA-256 | `4735f25999b67c1ff64c6cc34b0f386f7f83250e2e3ce75a92dc955adc969bc0` |
| Application | `Ration Docs.app`, 1.6 GB installed |
| Bundle id | `com.stackchase.rationdocs`, ad-hoc signed |
| Requires | macOS on Apple Silicon |

### Linux (arm64)

| | |
|---|---|
| Package | `ration-docs_2026.1.0-1_arm64.deb` |
| Size | 368 MB (385,931,372 bytes) |
| SHA-256 | `c990fd679038a0f962540d8c947be08896b0f6aa15d40759390398208009f731` |
| Tarball | `ration-docs-2026.1.0-1-aarch64.tar.xz`, 490 MB |
| SHA-256 | `37198fa907ea1ee3084593ce6f8954c0e57c03209a7cd01c99470de2e3240a1b` |
| Offline help | `ration-docs-help-2026.1.0-1-any.tar.xz`, 210 MB |
| SHA-256 | `d709342df26bbedcad71ecbaad7ea3457445b971cfb5609f471bacccd3758424` |
| Installs to | `/opt/ration/docs`, launcher `/usr/bin/ration-docs` |
| Requires | aarch64, glibc and libstdc++ at least as new as Ubuntu 24.04's |

The deb was installed on a clean machine and launched from `/usr/bin/ration-docs`;
the screenshots in this release are of that installed copy, not of a build tree.

**Linux is new in this release**, and it took sixteen fixes to the build to get
there - the tooling assumed an x86 host in four separate places, and two of our own
earlier fixes to the Linux application had never been compiled, because macOS
builds `desktop-apps/macos` and never touches `win-linux/`.
`build_tools/ARM64_DESKTOP_BUILD.md` records all of it.

### What was checked in the artifacts themselves

Not in the build tree - in the shipped files:

- The DMG was mounted and the application inside it inspected: bundle identifier,
  signature, version, start page. An earlier attempt at this release was caught
  this way, carrying a four-day-old application because `appdmg.json` pointed at a
  stale copy rather than at the build output.
- A document was converted with the `x2t` inside each artifact, with
  `APPLICATION_NAME` and `COMPANY_NAME` unset, and its `docProps/app.xml` read
  back. Both report `<Application>Ration Docs/2026.1.0.0</Application>`.
- `ldd -r` over the Linux payload: no undefined symbols.
  `check_symbol_closure.py`: clean on both.
- The help media in the macOS bundle is deduplicated into 182 relative symlinks;
  all 182 were verified to resolve.

## Start page

Four defects in the branded start page sidebar were fixed for this release, all
found from a screenshot of the running application rather than from the source -
two of them are injected at runtime and are not visible in the markup at all.

- The sidebar listed **"AI agent" twice**. One entry was hardcoded by the reskin,
  the other registered automatically for the AI agent plugin. The hardcoded one
  was also the broken one - clicking it blanked the content area, because nothing
  registers the panel it tried to show - so that is the one that went.
- **"Clouds" appeared twice**, for the same reason: a second heading is injected
  into the branded group at runtime.
- Every icon carried a **square outline**. The branded styles reset the icon
  box's padding, radius and background but never its border.
- The **selected item rendered as an empty white box** with its label invisible.
  The generic stylesheet assumes a light sidebar and paints the row white; the
  branded styles then wrote white text on it. The active item is now what the
  design intends: a petrol left accent with a faint wash.

Both AI plugins still ship. They share the same stored model and provider
selection, so configuring one configures the other.

## Known limitations

- **Apple Silicon and Linux arm64 only.** No Intel and no Windows build in
  2026.1.0. Intel would ship untested; Windows is the next platform to be built,
  and until it is, `updmodule` stays off - it pointed at ONLYOFFICE's update
  appcast, which would have offered their installer as an update to this product.
- **Not signed, not notarised** - see above. The Linux packages are unsigned too:
  no repository signing key exists yet, so `apt` will report the deb as untrusted
  if you add it to a repository rather than installing the file directly.
- **The Linux application segfaults on SIGTERM.** Observed headlessly: after a
  full start-up, `SIGTERM` (what a logout or `pkill` sends) ends the process with
  signal 11 rather than a clean exit. Closing the window normally is unaffected,
  and documents are written to disk on save, but a logout while the editor is open
  may skip the shutdown path. Not yet diagnosed; recorded rather than left for
  someone to find.
- **Translations fall back to English for six strings.** The strings that named
  the old product are removed from all 45 translation files, so `welWelcome` and
  five others now show in English in every locale. The right name in the wrong
  language rather than the wrong name in the right one; a translation pass is
  owed.
- **Around 19 fixes were written against Linux-specific behaviour** (GTK, Wayland,
  file dialogs) and are only now buildable there. Two of them turned out never to
  have compiled at all, and were fixed in this release; the rest are listed in
  `UPSTREAM_TRIAGE.md` and have not been exercised by hand on Linux.
- **One deliberate behaviour change.** Auto-fitting a column no longer resizes
  rows that contain no cell in that column. This removes a freeze - the old code
  measured up to 1,048,576 rows per column and created a record for each - but it
  is a visible change if you format whole columns and then auto-fit. It is
  reversible; see `REQUIRES_APPROVAL.md` item 9.
- **The AI plugin ships pre-built.** Fixes to its source do not reach users until
  the plugin is rebuilt, which is not yet part of this pipeline
  (`REQUIRES_APPROVAL.md` item 8).

## How the fixes were verified

Claims in this file are meant to be checkable rather than taken on trust.

- **48 of the 84** have a test in `fork-fix-tests/` that fails without the fix and
  passes with it. Each extracts the real function from the real source by brace
  matching rather than re-typing it, and each pins its baseline to the commit the
  fix landed on - not to `HEAD`, which would make the test pass forever while
  testing nothing.
- The remainder were demonstrated directly - usually by running the shipping 9.4.0
  converter against the fixed one and comparing the bytes - and the evidence is in
  the commit message.
- `UPSTREAM_TRIAGE.md` splits every entry by which of those applies, and lists
  what was root-caused but **not** fixed, with reasons. Several issues investigated
  for this release were deliberately left alone: some are genuine product
  decisions, and at least one turned out not to be a defect at all.

## Provenance

- Upstream base: ONLYOFFICE Desktop Editors **9.4.0**
- `PRODUCT_VERSION` inside the binaries remains `9.4.0`; `2026.1.0` is this fork's
  release version, shown as the application version on macOS.
- Licence unchanged: **AGPL-3.0-only**. Source for everything here, including the
  fork's own changes, is in this repository.
- Not affiliated with or endorsed by Ascensio System SIA.

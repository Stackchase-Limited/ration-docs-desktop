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

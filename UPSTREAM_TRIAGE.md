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

**Next task:** continue the stability sweep. A pass over all 200 open issues for
crash/freeze/data-loss titles turned up these, none yet triaged, roughly in order of
how tractable they look from source:

- **#2430** Spreadsheet fails to save/convert an XLSM with Form Control checkboxes -
  a save that does not complete is the data-loss case that matters most.
- **#2056** changes not saved on pressing save, and **#2230** changes disappearing
  when switching document tabs. Both data loss; both need reproduction first.
- **#2011** freeze copying all cells, **#2421** clipboard freeze on Linux/AppImage,
  **#2168** file dialog unresponsive on Arch/GNOME, **#2347** window unresponsive in
  a half-screen snap.
- **#2145** crash in `libascdocumentscore.so` on Fedora 42 - worth reading straight
  after #2136, since a symbol collision between a bundled and a system library is
  exactly the shape that just caused #2136, and that fix may already cover it.
- **#2189** the app closes itself on startup.

**Not ours, and recorded so nobody re-derives it:** #2438 is an outstanding piece of
diagnosis - the main thread deadlocks writing to Chromium's own `MessagePumpGlib`
wakeup pipe once it fills, because the write end is blocking and the main thread is
the only drainer. It is entirely inside Chromium, and we ship CEF as a prebuilt
binary; there is no `message_pump_glib` source in this tree to patch. The reporter's
own suggested fixes (open the write end `O_NONBLOCK`, or dedupe `ScheduleWork`) are
upstream CEF/Chromium changes. What *is* ours is the precondition: the main thread
running for seconds without returning to the pump during document load. Shortening
that would make the pipe drain and is the only lever on our side.

**Not reproducible from the report:** #2432, a macOS 9.4.0 crash applying a custom
page size when printing a presentation. `KERN_PROTECTION_FAILURE` at a stack address
on `CrBrowserMain` is a stack overflow, so infinite recursion somewhere in the print
path - but the attached report is truncated before the frames, the maintainer could
not reproduce it, and the promised video never arrived. Needs frames before anyone
guesses at the print code.

#2110, #2208 and #2148 remain traced below and unfixed; each needs an observation
this tree cannot produce by reading. The harness in `../../harness/` can launch a
real build and drive the editor over CDP, so that is the way in.

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

## Where this work lives, and what is not on lab02

Every checkout in the tree, and where its work actually goes. Taken from the remotes
themselves on 2026-09-13, not from memory:

| checkout | remote | pushed? |
|---|---|---|
| superproject | `lab02 ration/ration-docs-desktop` | yes, `ration/9.4-stability` |
| `desktop-apps` | `lab02 ration/ration-docs-desktop-apps` | yes, `ration/9.4-stability` |
| `dictionaries` | `lab02 ration/ration-docs-dictionaries` | yes, `ration/iconv-fix` |
| `build_tools` | `lab02 ration/ration-docs-build-tools` | yes, `ration/9.4-stability` |
| `core` | **github ONLYOFFICE/core** | no - nowhere to push |
| `sdkjs` | **github ONLYOFFICE/sdkjs** | no - nowhere to push |
| `web-apps` | **github ONLYOFFICE/web-apps-pro** | no - nowhere to push |
| `desktop-sdk` | **github ONLYOFFICE/desktop-sdk** | no - nowhere to push |
| `onlyoffice.github.io` | **github ONLYOFFICE/onlyoffice.github.io** | no - carries the #2129 fix |
| `core-fonts`, `document-templates` | github ONLYOFFICE | unmodified |

`build_tools` was missed in the first pass here and is now pushed; it carries the
help-image dedup. It also settles the naming convention - `ration-docs-<checkout>` under
the `ration` namespace - which is what `tools/configure-remotes.sh` expects for the four
that are missing.

**Four submodules could not be pushed, and most of the work is in them.** `core`,
`sdkjs`, `web-apps` and `desktop-sdk` still have exactly one remote each, and it is
ONLYOFFICE's own GitHub repository:

```
core        -> github.com/ONLYOFFICE/core.git
sdkjs       -> github.com/ONLYOFFICE/sdkjs.git
web-apps    -> github.com/ONLYOFFICE/web-apps-pro.git
desktop-sdk -> github.com/ONLYOFFICE/desktop-sdk.git
```

Pushing there is the one thing this fork has decided never to do, and lab02 has no
repository for any of them (`ration-docs-sdkjs` and the obvious variants all return
"project not found"). So those commits exist **only on this machine**, with no second
copy anywhere.

Two consequences worth being blunt about:

1. The superproject branch now on lab02 records submodule SHAs that resolve nowhere.
   A fresh clone will check out the superproject and then fail `git submodule update`
   for four of six. The branch is real but it does not build for anyone else yet.
2. Everything in `sdkjs`, `desktop-sdk` and `core` - which is most of the fixes - is one
   disk failure from gone.

**What is needed:** four repositories on lab02 and the submodule remotes repointed at
them, the way `desktop-apps` and `dictionaries` already are. Until then "pushed" means
the superproject, the Qt shell and the dictionaries, and nothing else.

**The remotes are now arranged so this cannot be got wrong by accident.** A push to
`ONLYOFFICE/desktop-sdk.git` was attempted on 2026-09-13 - habit, in the middle of a batch
- and failed only because the account has no permission there. That is not a safety
margin. In all four submodules the ONLYOFFICE remote is now named `upstream`, is fetch
only, and has a deliberately invalid push URL, so a push fails locally before any network
contact:

```
$ git push upstream ration/9.4-stability
fatal: 'DO-NOT-PUSH-to-ONLYOFFICE-use-lab02' does not appear to be a git repository
```

`.git/config` is not tracked, so a fresh clone comes back with `origin` pointing at
ONLYOFFICE again. `tools/configure-remotes.sh` reapplies the layout, and
`tools/configure-remotes.sh --check` reports it - worth running after any clone, and worth
wiring into CI if this ever gets CI. The script adds `origin` only once the matching lab02
project exists, so until then a push says "not set up yet" rather than 404.

The four projects it expects: `ration-docs-core`, `ration-docs-sdkjs`,
`ration-docs-web-apps`, `ration-docs-desktop-sdk`, under `lab02.ration.works/ration`.
A fifth would be needed for `onlyoffice.github.io`, which carries the #2129 fix.

**How this was checked**, so nobody repeats it: `ration-docs-{core,sdkjs,web-apps,
desktop-sdk}` and about thirty other name and namespace combinations were probed over
both HTTPS and SSH. SSH authenticates as `@ademola` with full user access and still
returns "project not found", so this is absence rather than a permissions artefact. Note
the HTTPS credential in the keychain is **git-only**: the GitLab API rejects it for
project listing, and `/projects/ration%2Fration-docs-desktop` returns 404 for a project
that was pushed to minutes earlier. Use SSH for anything beyond a plain fetch or push.

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

## Verification status - read this before trusting the table below

**Audit, and a correction to what "verified" means here.** 35 of the tests in
`fork-fix-tests/` defaulted their baseline to `HEAD`. That is fine while a fix is
uncommitted and worthless the moment it lands: `HEAD` then carries the fix, the
baseline stops differing, and the test passes forever while testing nothing. It
was already written down as a trap in this file and was still being reproduced in
new tests, including two written this week.

Measured rather than assumed - every such test was run with `BASELINE=1` and 34 of
them exited 0, i.e. reported success against code containing the fix. One of them,
`issue-1362-samba-lock`, was printing *"ok - a document held by somebody else on a
share is reported held"* while running the fixed file.

Every test is now pinned to the parent of its own landing commit, and each was
re-run both ways to confirm it fails at the baseline and passes on the working
tree. `grep -rn "BASE_REF', 'HEAD'" fork-fix-tests/` returns nothing.

**What this does and does not invalidate.** It does *not* invalidate the original
verification: each fix was demonstrated at a time when `HEAD` was still the pre-fix
tree, and those runs were real. What was lost is the *regression protection* -
between the commit landing and this audit, none of those tests would have noticed
if the fix were reverted. That is now restored.


An audit on 2026-09-15 found that **commit messages in this repository are not
evidence.** Several commits from earlier sessions cite a test directory as their
verification - `#1954` cites `fork-fix-tests/issue-1954-user-fonts/`, and there are
others - and those directories have never existed. `git log --all -- <path>` returns
zero commits for every one of them. `fork-fix-tests/` is tracked and not ignored, so
this is not a case of files being written and lost: the artifact was never there.

So the entries below fall into three groups, and the difference matters.

**1. A test artifact exists in `fork-fix-tests/`, run and seen to fail at
`BASELINE=1`.** These are verified in the sense this file means:

  #2434, #2445, #2443, #2368, #2301, #2328, #2269, #2250, #2234, #2244, #2189,
  #2105, #2216, #2274, #2296, #2324, #2263, #2425, #2334, #2389, #2022,
  #2426, #963, #2056, #2433, #2429   (back-filled)
  #2245, #2147, #2161, #2229, #2209, #2195, #2202, #2268

**2. No test file, but verified by direct observation this session** - a conversion
run through the shipped x2t, before and after, with the output recorded in the commit
message:

  #2430 (exit 134 SIGABRT becomes exit 80), #2280 (four times, wrong meridiem and a
  lost second), #2275 (FILE=&F renders as FILE=HeaderTest)

**3. Everything else.** Root-caused and argued, sometimes carefully, but with **no
artifact and no observation recorded here**. Some of these cite a test that does not
exist. Treat the mechanism described as a hypothesis worth reading and the fix as
unverified until someone writes the test.

This is not a claim that the group-3 fixes are wrong - several are obviously right on
inspection, and #2355 for instance is reasoning about a fix that *is* verified
(#2136... which is itself group 3). It is a claim that **you cannot tell from this
file which ones were checked**, and that is the problem being recorded.

**Back-filling is in progress**, data-loss issues first. When a test lands for an
entry, move its number into group 1 above.

**One trap, found on the first back-fill.** A back-filled test cannot use `HEAD` as its
baseline: HEAD already contains the fix, so the test passes both ways and proves
nothing - which is precisely how a green run can mean nothing at all. The baseline has
to be the commit *before* the fix landed. Give the test a default so nobody has to know
this:

    const BASE_REF = process.env.BASE_REF || '<fix-commit>^';

The #2426 test ran green against HEAD on the first attempt, and only failed - correctly,
with the right message - once pointed at `ede98d9619^`.

**Two more things the first three back-fills turned up**, both about reading results
rather than about the code:

- A test's exit status is the *last command in the pipeline*. `node t.js | tail -3`
  reports `tail`'s status, which is always 0. The #963 test looked green that way while
  it was actually failing. Run the test bare when you want its result.
- A back-filled test can fail because the **stub** is wrong rather than the fix. The
  #963 stub modelled prior changes as disappearing once the open edit was committed,
  which is not how the editor behaves. The answer is to correct the model, never to
  loosen the assertion until it passes.

And one on scope: `fork-fix-tests/syntax-check-desktop-sdk.sh` is cited by an earlier
commit too, and is also absent. The missing-artifact problem covers tooling, not only
tests.

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
| #2442 | *Feature.* The default AutoFit for a new text box is now a setting, so a box keeps the size it was drawn at | `sdkjs` + `web-apps` |
| #2136 | A folder named with an emoji segfaulted the GTK file chooser: libgraphics exported its bundled FreeType 2.10.4 and cairo bound to it | `core` |
| #2312 | The GUI waited on a CUPS connect timeout before appearing, for a printer name nothing reads | `desktop-apps` |
| #2056 | A save reported success before the bytes reached the disk, so a power cut lost the document | `desktop-sdk` |
| #2168 | The file dialog froze on Wayland: an in-process GTK chooser inside an XWayland Qt app | `desktop-apps` |
| #1748 | The executable exported its statically linked libstdc++, so the system one bound to it and aborted before `main` | `desktop-apps` |
| #2444 | A failed connection was reported as "Invalid URL", sending users to correct an address that was already right | `desktop-sdk` |
| #2426 | A FILTER returning from no-match filled only its first cell: the spill pass was scheduled on a flag recalculation had already cleared | `sdkjs` |
| #2433 | A Big5 subtable was recorded as Unicode coverage, so Heiti won the Hangul fallback and drew Chinese ideographs | `core` |
| #2199 | The interface language was never declared to the renderer, so Simplified Chinese was drawn in Traditional forms | `web-apps` |
| #1954 | Store-installed fonts were missed: the profile directory was guessed from the account name | `core` |
| #2293 | A relative file hyperlink was handed to the shell unresolved, so nothing opened and nothing said why | `desktop-apps` |
| #2302 | The interface language came from `LANG` alone, ignoring `LC_ALL` and `LC_MESSAGES` (language half only) | `desktop-apps` |
| #2395 | The desktop entry had no localised `Name`, so launchers running in a locale could not find the application | `desktop-apps` |
| #2397 | Nothing told Qt which desktop entry this is, so a Wayland panel had no `app_id` to match and showed no icon | `desktop-apps` |
| #2435 | Chat messages took their direction from the interface, so Arabic replies were laid out left to right | `desktop-sdk` |
| #2368 | Pasting a paragraph or a table row reused the source's `w14:paraId`, so the saved docx carried ids that must be unique on up to five paragraphs (part of #2368 only - see below) | `sdkjs` |
| #2355 | Save As closed the whole application when the folder held a file with an emoji in its name - the same symbol interposition as #2136, and closed by that fix | `core` |
| #2445 | *Tooling.* A shipped module imported an entry point the kernel beside it did not export and the loader refused to start the app; nothing in the build noticed. The package step now checks the payload's symbol closure | `build_tools` |
| #2434 | The app exited 0 straight after Qt initialised: on a host whose loopback has only 127.0.0.1, it could not bind its per-uid instance address and read that as "somebody else is primary" | `desktop-apps` |
| #2443 | A throw inside a row or column structure change left recalculation suspended for the rest of the session, so every formula went blank with no error shown (hardening - not a confirmed reproduction, see below) | `sdkjs` |
| #2430 | Fourteen bounds checks in the shared binary reader executed a bare `throw;`, which can only call `std::terminate` - any binary that ran the reader past its buffer killed x2t outright (the abort only; the underlying desync is still open, see below) | `core` |
| #2189 | `GetLastError()` was read after `CreateMutex` without clearing it first, so a stale `ERROR_ALREADY_EXISTS` made the only running instance decide it was a second one and exit 0 | `desktop-apps` |
| #2269 | A conditional formatting rule loaded from file was built with no parent and no dependencies, so it never evaluated until an edit forced it | `sdkjs` |
| #2250 | A copied bullet reached the plain-text clipboard flavour as a raw symbol-font codepoint, with no font to give it meaning | `sdkjs` |
| #2280 | Times written to CSV had the wrong meridiem at noon and midnight, and lost a second on roughly half of all times | `core` |
| #2301 | `wcstod` accepts hexadecimal float literals, so any `0x...` CSV value was imported as a number and the text discarded | `core` |
| #2328 | `correctFromInterface` parsed a conditional formatting formula as locale and assembled it back to locale, so a comma decimal separator was stored and then misread | `sdkjs` |
| #2216 | The GTK theme was forced to Adwaita for every dialog, replacing whatever theme the desktop runs | `desktop-apps` |
| #2274 | A bundled Qt plugin needed Qt Quick, which was not bundled - dead on a machine without system Qt5, and a second QtCore in the process on one with it | `build_tools` + `desktop-apps` |
| #2105 | Forcing the xcb platform plugin on a Wayland session with no X display segfaulted instead of saying so (the crash only; Wayland support is a port) | `desktop-apps` |
| #2244 | A chart axis could not be scaled past a million - the clamp was in the spinner, not the engine | `web-apps` |
| #2234 | A macro writing to a locked cell returned false in silence, so it looked as though macros no longer ran (part) | `sdkjs` |
| #2275 | The file name field of a header or footer was blank in an exported PDF - the converter has no DocInfo to resolve it from | `core` + `sdkjs` |
| #2334 | A dragged tab tore out into a new window the instant the pointer left the strip, in any direction, by any distance | `desktop-apps` |
| #2389 | The "make me your default" toast had no opt-out and threw the answer away, so it returned every day forever (part) | `desktop-apps` |
| #2296 | One date shown two ways: month-first gave `dd-mmm-yy`, month-second `d-mmm-yy` - and the wider one is where the `#####` came from | `sdkjs` |
| #2324 | The style gallery listed Heading 9 first: the sort compared `.Name` on an object that stores `name`, so it was a silent no-op | `sdkjs` |
| #2263 | Justify did nothing to East Asian text - gaps were counted only after a space, and a line of CJK has none | `sdkjs` |
| #2425 | The retina fill handle could not be grabbed: the hit test was three device pixels flat while the square drawn is far larger (part) | `sdkjs` |
| #2022 | *No upstream issue.* The last row of a CSV lost its trailing delimiters, so a reader counting fields dropped its final columns | `core` |
| - | *No upstream issue.* Number-format padding directives (`_c`, `*c`, `[Red]`) were written into CSV cells as text: Accounting wrote `_ * 8745.00_ ` | `core` |
| #2245 | Four ways a trendline equation printed something other than the line it fitted, worst an int32 wrap that turned a slope of 1e6 into 141006.5408 (part) | `sdkjs` |
| #2147 | Colour printing was decided from one PPD keyword drivers do not agree on, so colour printers were offered black and white only | `desktop-apps` |
| #2161 | The print dialog resolved a standard paper name then threw it away, so CUPS fell back to nameless custom media with no margins | `desktop-apps` |
| #2229 | Every theme's window border was below the 3:1 contrast threshold, two of them at 1.15 - effectively invisible (border only; drop shadows need a Wayland port) | `desktop-apps` |
| #2209 | Every CSV ending in a newline gained an empty trailing row: the string was sized in bytes, so the end-of-data guard fired on a file that ended cleanly | `core` |
| #2195 | A symbolic retry lost its `+ 0xF000`, so Wingdings and Symbol text inside EMF/WMF metafiles was drawn in a substituted font (core half only) | `core` |
| #2202 | A failed `fork` or `execve` returned 0, so a save reported success for a conversion that never ran and the document was marked clean over lost work | `desktop-sdk` |
| #2268 | Two AI providers reported every failure as "Invalid URL", sending users to correct an address that was right (the CORS root cause is untouched) | `desktop-sdk` |
| #2187 | A macro bound to a shape was silently unbound when the workbook was saved to ODS - while `jsaProject.bin` was still written, so the macro stayed in the dialog with nothing attached | `core` |
| #1570 | A document written in Verdana spilled a full page onto a second, because Verdana had no metric substitute and the picker fell through to Open Sans - 12% taller per line | `sdkjs`, `core` |
| #1359 | An encoding number sent by the editor indexed past a 54-entry table: 65001 - the Windows code page for UTF-8, and what our own documented API tells callers to send - killed the converter outright, and 1252 returned success with a blank spreadsheet | `core` |
| #1364 | Copying one cell whose displayed text is empty replaced the system clipboard with an item carrying **no text flavour at all** - a falsy test where the contract is presence (the in-app half of the report is not explained by this; see the commit) | `sdkjs` |
| #1018 | AutoFit on a few columns froze the app: the scan walked the sheet's row extent rather than the column's cells - 4,194,304 visits where 400 were needed (see the approval list, item 9, for the row-height change it makes) | `sdkjs` |
| #139 | One character XML forbids - pasted, never from a file - made the whole slide it sat on come back blank, because the run-text escaper handled the five entities and nothing else | `core` |
| #2113 | A pivot table saved to ODS came back as plain cells: we wrote the container and never filled it, and every unset attribute serialised as the literal `--` | `core` |
| #676 | Copying an image file in a Linux file manager pasted its path as text, because `text/uri-list` was read nowhere in the editor | `sdkjs` |
| #2071 | Rows could be hidden but never shown: the whole-sheet branch of `setRowHidden` was an empty `// ToDo`, so a file with `zeroHeight="1"` opened unreadable with no way back | `sdkjs` |
| #1362 | The `.~lock` marker was written on a share but never read - three defects, all ending in "free, go ahead and write", so two people could edit one file | `desktop-sdk` |
| #1297 | Every CSV over ~500KB was silently corrupted at each buffer compaction: a delimiter, quote or newline lost its meaning and cells merged (the OOM half is not fixed) | `core` |
| #1372 | Every built-in number format was discarded on CSV export - percentages, currencies and fractions written as raw values (core half) | `core` |
| #1323 | A saved docx could be detected as a plain zip: zip entry order put `_rels` where libmagic could not find it | `core` |
| #1855 | A PDF carrying an outline opened with the bookmarks pane shut - the catalog was pinned to `/UseNone` (core half) | `core` |
| - | *No upstream issue.* Our own #2056 flush did not compile on Linux: `G_IS_FILE_DESCRIPTOR_BASED` needs a header in `gio-unix-2.0`, which the build never asked for | `desktop-sdk` |
| - | *No upstream issue.* A zero-length converter result was reported as a successful save, because `StartWrite()` cannot answer whether the locker ever locked | `desktop-sdk` |
| #2524 | AI agent with Mistral: a reopened thread (or a switch to Mistral) that contained a tool turn was rebuilt as assistant(toolCalls) with no tool answers, so every later request failed with 400/3230 | `desktop-sdk` (ai-agent) |
| #2461 | AI agent with Ollama: tool arguments sent whole in one delta were shown but forwarded to the MCP server as `{}`; also a call in the same chunk as `finish_reason` was dropped, and parallel calls were merged or left unanswered | `desktop-sdk` (ai-agent) |
| #2508 | The OS cursor-blink setting was never passed to the editors; every caret (cell, document, slide, PDF, sheet shapes) blinked on a fixed 500 ms timer | `desktop-apps` + `sdkjs` |
| #1470 | On Linux the CJK punctuation fallback took a Traditional Chinese/HK face (Noto Sans CJK HK, AR PL) and drew 。 centred; no Linux Simplified Chinese family was in the font priority list | `core` |
| #1947 | Linux only: a landscape document printed shrunk onto a portrait sheet - Qt sends CUPS an empty `landscape` option, which CUPS reads as `nolandscape`; the job now goes out portrait with landscape pages turned by us, as quick print already did (Windows half not reproduced) | `desktop-apps` |
| #2480 | Follow-up: a replace that broke between the server's remove and rename left the content only in a hidden temp (and the next lock created an empty document); the rename is retried, the temp kept and logged until it can be put back, and stale save temps are cleaned | `desktop-sdk` |
| #1672 | Hidden slides went into PDF exports (x2t / desktop Save as PDF) and desktop printouts - content the author hid was published; now left out as PowerPoint does, ranges count by slide number | `sdkjs` |
| #1568 | "Update style" / "New style from selection" dropped the selection's highlight on purpose; now carried into the style as Word does (font colour already worked) | `sdkjs` |
| #2095 | Drag half: a document (docx/xlsx/pdf/csv...) dropped on an open editor was refused - now opens in a new tab via the start page's DropOfficeFiles route. The paste half (the issue's title) is triaged below | `sdkjs` |
| #1491 | Linux/Windows: a clicked video in a slide show kept every key (arrows scrubbed, Escape stopped it); in a show the player now keeps only M and hands the rest to the slide show. macOS was never affected | `sdkjs`, `desktop-sdk` |
| #1672 | Follow-up: the Windows/Linux print screen previewed every slide, hidden ones included, numbered by slide; it now previews exactly the slides that print. The web PDF of an all-hidden deck had 0 pages; now one blank page | `sdkjs`, `web-apps` |
| #2107 | Removing a plugin deleted file by file, ignored failures and reported success (half-removed plugin, lost files); now one rename or nothing, and the plugin manager reports a failed removal and shows a revealed system plugin as installed | `desktop-sdk`, `onlyoffice.github.io` (local clone only - see note under #2107) |
| #2318 | Wingdings on Linux (substituted by OpenSymbol) drew blank or a stray glyph: the remap table had 10 codes (now 139, each checked against both fonts) and the shaper remapped only the first symbol of a run | `sdkjs` |
| #2110 | macOS: slides printed at 100% from the corner and were cut off on the right - the editor type that forces fit-to-paper was only ever set by the Windows/Linux app | `desktop-sdk` |
| #2031 | Windows (Inno EXE): .docx/.pptx/.xlsx/.pdf were always associated on Windows 10/11, whatever the user ticked, overwriting another vendor's default; proven under Wine. The MSI is triaged below | `desktop-apps` |
| #2561 | An image dragged across an open document without dropping left the drop target armed; the next click split the paragraph (not Windows-only). The target is now cancelled when the drag leaves | `sdkjs` |
| #2560 | macOS: an accent picked from the accent menu (or any letter replacement) doubled in spreadsheet text boxes ("eé") - their typing history was not recognised as typing | `sdkjs` |
| #2559 | macOS: Portuguese (Portugal) keyboards tagged text pt-BR, and British/Australian/Canadian/Swiss German/Austrian/Serbian lost their country (Serbian lost spell checking). Linux was already fixed by #2503 | `desktop-sdk` |
| #2556 | Rows hidden down to the end of a sheet came back visible after an .ods save (four converter defects: row folding, ODS writer repeat count, reader skipping hidden runs, a self-comparison typo) | `core` |
| #2375 | macOS: scrolling a document repainted at most every 40ms (20-25fps on a 120Hz trackpad); a scroll now repaints on the next frame. Presentation, Visio and PDF keep the 40ms loop | `sdkjs` |
| #1760 | Also #1740: a picture copied in the document or presentation editor reached other apps only as an <img> inside HTML, so Facebook/Messenger/Lens got nothing; it now also goes out as image/png | `sdkjs` |
| #2131 | An inserted video was a 79.4mm square (sized from the all-black 300x300 placeholder poster), so players letterboxed it and PowerPoint stretched it; the host now reads the mp4/mov track size and the frame takes the video's aspect | `desktop-sdk`, `sdkjs` |
| #1922 | A video's own mute/volume (p:cMediaNode, set in PowerPoint) never reached the player when opened by selecting/hovering it, and when sent it was unscaled (80000; macOS took 20 as 20x); the player also reset its volume each time it reopened. Fixed in sdkjs and both players | `sdkjs`, `desktop-sdk` |
| #1655 | macOS: the pivot Group dialog's "By" list (and every multi-select list) only toggled items on Ctrl+click, which macOS turns into a right click; Cmd+click now toggles. The grouping engine was already right | `web-apps` |
| #2010 | PDF bookmarks from headings were already in 9.4; two leftovers fixed: a page-range "Save as PDF" pointed the bookmarks at the wrong pages (or none), and every title ended with the paragraph mark | `sdkjs` |
| #1942 | In a slide show the video controls covered the video for the whole show; they now show only while the mouse is over the video and hide after 2 s of a still mouse while playing (macOS and Qt players) | `desktop-sdk` |
| #1943 | Play/pause/seek in the presenter view's player reached nothing; they now drive the slide show's player (and back), sound only from the slide show | `sdkjs`, `desktop-sdk` |
| #2528 | Switching tabs flashed light gray in a dark theme on Linux (the X window holding each tab had a fixed light background); on macOS a theme change left open tabs with the old background | `desktop-sdk`, `desktop-apps` |
| #2062 | LaTeX -> Professional froze the editor for good on any spacing command but `\ ` and `\quad` (`\thinsp`, `\nbsp`..., also reached via a Word thick space); `\,` `\:` `\;` stayed as literal text. Keyboard input on Mac layouts was fine | `sdkjs` |
| #1468 | Linux "auto" interface scaling ignored the desktop's fractional scale whenever the screen-size guesses or physical DPI disagreed (4K at 125/175% came out 200%, 1600x900 at 125% came out 100%); Xft.dpi now wins | `desktop-sdk` |
| #1967 | Administrators can switch plugins off machine-wide (all, the plugin manager, or listed GUIDs) through the platform's managed settings: Windows HKLM policy, macOS configuration profile, Linux /etc/ration/docs/policy.conf (desktop-apps MANAGED-SETTINGS.md) | `desktop-sdk`, `desktop-apps` |
| #2235 | Privacy: every launch fetched ONLYOFFICE's template gallery (templates.onlyoffice.com API + ~750 thumbnails from static-oforms.onlyoffice.com) with no user action; no default gallery now, and Chromium background networking is switched off. Measured: 0 remote requests, sockets or DNS lookups for a full session | `desktop-apps`, `desktop-sdk` |
| #2271 | macOS sent made-up language codes ("ja-JA", "zh-ZH", "sv-SV", "no-NO"...) that matched no blank template, so new documents for most non-English users were US Letter / en-US; the same language's template is now used. "Set as default" page setup stays a feature request (design in the note) | `desktop-sdk` |
| #2090 | New setting "Default text direction" (Advanced settings, desktop) for new blank documents; sdkjs can now change the default paragraph direction and re-lays out on it. Documents and templates are never touched | `sdkjs`, `web-apps`, `desktop-sdk` |

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

### #902 - plain Save to CSV exported the sheet active at open - FIXED 2026-11-11
Save As CSV was already right (#1839). A plain Save (Ctrl+S on a .csv, or CSV picked for a new file)
sent "" as save params (sdkjs cell/Local/api.js DesktopOfflineAppDocumentStartSave), so desktop-sdk
used its default and x2t exported the open-time activeTab; sheet switches write no history. Plain Save
now sends the host default plus activeSheet/topLeftCells (sdkjs e2d1b5afd8; test issue-902-csv-plain-save-active-sheet-test.js). Test app: CSV opened, sheet
added and made active, Ctrl-S path wrote that sheet. Side effect: a plain xlsx Save now also keeps the
sheet/scroll on screen, as Save As does.

### #706 - Save As cut dotted names ("foo(05.09.21)" offered as "foo(05.09.docx") - FIXED 2026-11-11 (Linux/Windows)
desktop-apps win-linux cfiledialog.cpp handed the dialog the name cut at the last dot of the whole
path; Qt's widget dialog and KDE's (the portal backend on Plasma Wayland, default since #2168) then
replaced what followed that dot with the filter's extension. A name without an extension in a dotted
folder lost part of the path (/home/u/v1.2/README -> /home/u/v1). After the dialog, a typed extension
of another offered format was rewritten silently (talk.pdf with DOCX -> talk.docx) and a.docx.pdf
became a.docx.docx. Now only the file name's extension is cut; portal/Qt dialogs get name + selected
extension; a corrected name that differs from what the user typed asks first (one new English
string). desktop-apps a877e2fc4; test issue-706-saveas-dotted-name. KDE/GTK/Windows dialogs not run
live; macOS save panel unchanged and not GUI-checked for dotted names.

### #790 - On deepin 20.3 I can't save file as chinese filename - reported symptom gone in 9.4; related crash FIXED 2026-11-11
Report (6.4.2): Chinese could not be typed in the Save As name box on deepin. In 6.4 that box was
QFileDialog's widget dialog from the bundled Qt, which ships no fcitx platforminputcontext plugin, so
fcitx input could not reach it (ibus could). 9.4 does not use that dialog on Linux
(FILEDIALOG_DONT_USE_NATIVEDIALOGS undefined): Save As runs the system GTK chooser (X11) or
xdg-desktop-portal (Wayland), which use the desktop's IM module. Not re-run on deepin. Found while
checking: gtkfilechooser.cpp and xdgdesktopportal.cpp passed name/folder/title/filters with
toLocal8Bit; under a non-UTF-8 locale the portal path aborted the whole app in libdbus (unsaved work
lost) and the GTK path garbled the name. Now toUtf8 (desktop-apps 7f1090d9c; test
issue-790-linux-dialog-utf8).

### #2000 - Open/save from network share (samba/nfs/cloud) - save half FIXED 2026-11-11 (macOS/Linux)
Reported: Flatpak 9.0 on GNOME - Samba/NFS/Nextcloud/Google Drive mounts do not appear in the open/save
dialog. Our GTK chooser (desktop-apps win-linux/src/platform_linux/gtkfilechooser.cpp) is local-only and
returns gvfs FUSE paths (/run/user/<uid>/gvfs/...), which do show when the sandbox can see them; the
portal dialog returns document-portal paths. Missing mounts in the Flatpak are a sandbox permission of
the flathub manifest (xdg-run/gvfs, org.gtk.vfs.*), not in our tree.
The save half was data loss: CFileLockerFCNTL/FileProvider wrote the new file over the old one in place
(seek 0, write, truncate, fsync). A share or quota running full or a dropped connection destroyed the
document (reproduced: HFS+ image, Linux CIFS, macOS smbfs - where write/fsync succeed and ENOSPC only
comes from close(), so the save was even reported as successful). Now a hidden sibling temp, fsync,
mode/owner/xattrs copied, close() checked, size verified, rename over the document; any failure leaves
the document untouched and the save reports failure; EXDEV falls back to verified copy; a folder
without create rights keeps the in-place write. Linux F_SETLKW (open hung while another process held
a lock) is now F_SETLK. desktop-sdk 5eaf9b64; test issue-2000-network-share-save (issue-2135 extractor
updated for the Lock/OpenDescriptor split). Test app: two saves of a 0640 docx replaced the file, kept
the mode, left no temp. Trade-offs: a save needs room for both copies; hard links break; owner becomes
the saver where chown is refused. Not changed: Windows locker (in place); Save As over another
existing file (x2t writes straight to it); CFileBinary::Exists after a save drops the process's fcntl
lock (the .~lock marker remains) - seen in the test app, pre-existing.

### #182 - auto column width needed applying twice - FIXED 2026-11-11
On a customWidth column, _addCellTextToCache (sdkjs cell/view/WorksheetView.js ~9564) shortened numbers
to the current width, and _autoFitColumnWidth measured that shortened text; setColBestFit then cleared
customWidth so the second autofit measured the full number. During autofit the custom width no longer
blocks the full-width branch (sdkjs 2c08a678ee; test issue-0182-autofit-custom-width-test.js).
Reporter's file: 96 -> 99 -> 99 px instead of 96 -> 95 -> 99.

### #482 - large CSV - silent row loss over 1,048,576 rows FIXED 2026-11-11
A 273 MB / 568k-row CSV opens (x2t 97 s, 2.2 GB RSS; editor 20 s). The real defect: x2t's CSVReader stops
past the row limit with ROWLIMITS (94), which counts as success, and the desktop open path drops the
code, so rows beyond 1,048,576 vanished without a word - and saving over the CSV lost them. The CSV
dialog already parses every record; the spreadsheet Main.js onAdvancedOptions now warns with the row
count and the limit (web-apps 7ddbfa80c2; test issue-0482-csv-row-limit-warning-test.js). Open:
warning may sit under the load mask until loading ends (GUI check); x2t keeps one row past the limit;
csv->xlsx conversion ignores the limit; CELLLIMITS (96) truncation is also silent - surfacing x2t
codes needs desktop-sdk to pass them to JS.

### #560 - print ignores paper size (macOS) - FIXED 2026-11-11
desktop-apps macos ascprinter.h BeginPaint passed the web-apps preset caption ("US Letter",
"Envelope #10") to -[NSPrintInfo setPaperName:], which ignores non-macOS names; custom sizes sent
nothing. So every job used the printer default. Now setPaperSize: from paperSize.w/h (resolves to the
printer's named paper), name as fallback, JSON types checked (desktop-apps 27578a09e; test
issue-0560-mac-paper-size, real NSPrintOperation to PDF). Linux/Windows already set the size from the
document. Real print panel/printer not checked.

### #281 - bottom of a 210x330 page not printed - FIXED 2026-11-11
desktop-sdk fileprinter.cpp CheckPrintRotate, pm100 branch: a page that fits the sheet neither way was
printed at 100% from the corner and clipped. It is now fitted to the sheet (FitToPage, the larger
orientation) as the pmFit branch already does; pages that fit are unchanged (desktop-sdk c8d2135de6;
test issue-0281-print-oversize-page). Behaviour change: oversize pages shrink instead of being cut.

### #531 - filtered xlsx exported to PDF scaled down - FIXED 2026-11-11
In x2t, a filter change empties the row/column caches and nothing redraws; calcPrintScale (sdkjs
cell/view/WorksheetView.js ~4580) took the fit-to-page scale before _calcPagesPrint rebuilt them, so
hidden rows counted at default height (38 visible of 170 rows printed at 28%). The native-only cache
rebuild now runs first (sdkjs df3a283c13; test issue-0531-fit-filtered-rows-test.js).

### #547 - PDF export fits everything on one page - FIXED 2026-11-11
A plain Save to PDF (first save of a new spreadsheet) sent the host default {"fitToWidth":1,
"fitToHeight":1}, which asc_nativePrint applied to every sheet. It now sends the sheets' own page setup
and locale as Save As does, keeping #902's activeSheet/topLeftCells (sdkjs ba80ae077e; test
issue-0547-plain-save-pdf-layout-test.js; the #902 test now expects locale too).

### #927 - plain-text copy adds line breaks (Linux/macOS) - FIXED 2026-11-11
asc_CheckCopy built text/plain with CR LF paragraph ends and lone CR soft breaks; Chromium converts
newlines only on Windows. Off Windows it now uses LF (sdkjs 981db8c0e0; test
issue-927-plain-text-line-endings-test.js; issue-1760 test stub gained AscBrowser). Side effect: a soft
break pasted back as plain text becomes a paragraph break (it used to vanish). Linux editor paste not
checked live.

### #334 - copied table left-aligns a centred equation - FIXED 2026-11-11
Copy rendered each formula to a picture via MathToImageConverter(), which left-aligns the formula
object itself, and ParaMath.Copy never copied justification. Both fixed in word/Editor/Math.js (sdkjs
b7a1614833; test issue-334-copy-math-justification-test.js); the reporter's file now saves "center"
for both tables. The thread's later multi-cell paste/cursor comment is a separate defect.

### #925 - typed « » get no non-breaking spaces in French - FIXED 2026-11-11
GetAutoCorrectFlags never started French autocorrect for U+00AB/U+00BB, and
private_ProcessFrenchPunctuation only handled : ; ? !. In fr-FR text, » now gets a nbsp before it
(replacing typed spaces), « a nbsp after it; each step undoes separately (sdkjs 49123ea9fe; test
issue-925-french-guillemets-nbsp-test.js). fr-CA/fr-CH not covered.

### ONLYOFFICE 10.0.0 security fixes - audited and backported 2026-11-11
Source: DesktopEditors CHANGELOG 10.0.0 security section (37 items), DocumentServer CHANGELOG, NVD
(ONLYOFFICE CVEs: 2026-110385/110652 server-only; 2026-41030/41034 fixed before 9.3). No GitHub
advisories. Per item mapping in .rd-work/wt/cu-tmp. 18 already covered (earlier picks or our #1664
work), 15 new: core c5d814c502..fc6cea8985 (XPS font stack overflow, WMF OOB read, HWP/HML path
traversal, circular DOCX style crash, DOC CHPX/font table OOB, EMF PolyBezier OOB, ZipEmbed bounds,
PDF image-mask heap overflow, libxml2 CVE-2022-23308 ported into the vendored valid.c, and two of
ours where upstream has no commit: PPT metafile OOB read leaking memory into the PPTX, DOC piece-table
bounds); sdkjs b0b55a5bdb (macro sandbox: top/parent/frames/opener/frameElement/WebSocket/importScripts
stubbed - cookie access), b468963a2e (plugin PasteHtml in a sandboxed iframe); desktop-sdk 439fe1792c
(bridge RemoveFile path check from a PDF, crash on execCommand/PluginInstall with no args). Tests
v10-sec-core-converter (ASan), v10-sec-macro-window-aliases, v10-sec-plugin-pastehtml,
v10-sec-bridge-removefile. The PDF-reader/XPS/libxml2 and WMF/EMF fixes reach the editors' WASM
through sdkjs 4789c97347 (drawingfile + fonts rebuilt from core fc6cea8985; test v10-sec-wasm-renderers;
test app renders text + image mask). Still open: b6897a441e's 4*w*h overflow guard is size_t = 32 bit
in wasm32, so a 32768x32769 /ImageMask still traps the viewer module - needs a core guard in
RendererOutputDev (w > SIZE_MAX/4/h) and another rebuild - DONE 2026-11-12: core c9d4bbe6c4
(GetImageBufferSize refuses sizes that do not fit size_t/int stride, in every image path, plus
CPdfReader::GetButtonIcon; also fixed a DCT soft-mask heap overflow found under ASan), drawingfile
rebuilt in sdkjs 3c0c7a391c; HtmlFile2 9f33a5b519 ported as core 49f4979807 (outside CSS no longer
loaded; EPUB ../Images pictures no longer dropped; test v10-sec-htmlfile2-paths). Unknown: "DOCX double free", "integer-overflow heap write" (candidate
commits already picked). Not ported: HtmlFile2 9f33a5b519 follow-up (heavy conflicts); web-apps
3f9b9168e4 PDFE right-panel crash (changes panel behaviour; needs a GUI repro). PDF-reader fixes also
need the drawingfile WASM in sdkjs rebuilt to reach the editors (see core-wasm note). RemoveFile now
refuses paths outside the resolver's folders - cloud-crypto upload may leave an encrypted temp copy.

### #307 - wrapped centred text taller than its cell shows its middle lines - FIXED 2026-11-11
cell/view/WorksheetView.js _drawCellText passed cellVA straight to _calcTextVertPos, whose Center
branch goes negative once wrapped text overflows the row, so the clip kept the middle. Excel shows the
first line. Wrapped, unrotated overflowing text with Center/Dist/Just is drawn from the top (sdkjs
67b7cbe97c; test issue-0307-wrapped-overflow-valign-test.js). Reporter's file via x2t to PDF matches
Excel. centerContinuous (centre across cells) still not applied - separate gap.

### #1031 - Chinese text in a WMF decoded as Latin - FIXED 2026-11-11
MetaFileUtils.cpp ConvertToUnicode decoded ANSI_CHARSET as cp1252 and DEFAULT_CHARSET as Latin-1
always; Windows uses the system ANSI code page, so GBK bytes in a charset-0 font show as Chinese on a
cp936 system. ANSI/DEFAULT now follow the host code page when it is 932/936/949/950 (GetACP on
Windows; LC_ALL/LC_CTYPE/LANG elsewhere) (core 9e6c96b316; test issue-1031-wmf-ansi-codepage).
Windows branch not compiled; the macOS app launched from Finder usually has no LANG, so there it only
applies if a locale reaches x2t. Also in the drawingfile/fonts WASM only after a rebuild.

### #878 - videos set to start Automatically/On Click never played in a slide show - FIXED 2026-11-11
PowerPoint stores Playback > Start as a mediacall <p:cmd type="call" cmd="playFrom(0.0)">. common/
apiBase.js tested startsWith(...) === 0 (a boolean, never 0), so players got "playFrom(0.0)", which
neither the AppKit nor the Qt player handles; and the timeline never opened a player (the desktop
opens one only for a selected video). Now a timeline play in a show selects the video, seeks and
plays (slide/api.js callTimelineMediaCommand); a resize with no transition keeps the player and moves
it instead of closing it (sdkjs 78aab3b128, 06157857a8; test issue-0878-slideshow-video-autoplay-test.js).
Real playback in the native players and the full-screen resize timing need a GUI check.

### #344 / #328 - pptx symbols (a:sym) drew as unrelated glyphs - FIXED 2026-11-11
Serialize.js ReadRunProperties skipped a:sym, so Insert > Symbol characters (U+F020-F0FF) drew with the
latin font and fell back to Wingdings (#344: U+F0AC arrow as a star; #328 lec5.pptx: Pi, epsilon,
approx, element-of, arrows as pictures). Apple's Symbol.ttf has no (3,0) cmap, so "use Symbol" is wrong
on a Mac too. Reader now maps Symbol sym codes to the Unicode characters (xpdf symbolEncoding via the
AGL) and gives other sym fonts only to the symbol characters by splitting the run (sdkjs 6884d875b3;
test issue-0344-pptx-sym-font-test.js). Accepted behaviour change on save: a:sym is not written back -
Symbol characters save as real Unicode (U+2190 not U+F0AC), which PowerPoint shows correctly; runs with
another sym font save split with it as latin font.

### #619 - opening a template edited the template itself - FIXED 2026-11-11
CCefViewEditor::OpenLocalFile treated a .dotx/.xltx/.potx/.ott/... like any document (m_sFileSrc = the
template, document counted as saved), so Save converted back over the template. Templates now go
through the start page's CreateLocalFile(<name>.docx|.xlsx|.pptx, templatePath) path; cloud-crypt
downloads and mode=view are excluded; editing a template itself = Save As in a template format
(desktop-sdk 946e4d8f6d; test issue-619-template-opens-as-new). Test app: a .dotx opened with its
content and stayed byte-identical after edit + Save. Open: shells key the tab by the template path (a
second open focuses the first new document); binary .dot/.xlt/.pot still open in place.

### #1004 - template types missing from Windows default-app associations - FIXED 2026-11-11
.dotx itself was fixed upstream (16ebd8f24); macOS Info.plist, Linux .desktop and the MSI already list
the whole family. The Inno installer we ship (package/inno/_code.iss initExtensions) had no
.dotm/.xltx/.xltm/.potx/.potm/.ott/.ots/.otp: no ProgID, no Capabilities entry, no association even with
/FULLASSOCIATION. Added, with en/en_GB descriptions (desktop-apps 867bdbe7e; test
issue-1004-template-associations, real Inno installer under Wine). Explorer/Default apps UI and the MSI
not exercised.

### #388 - Edit > Undo/Redo did nothing on macOS - FIXED 2026-11-11
Main.storyboard sent undo:/redo: to the first responder - Chromium's view, whose browser undo has no
history for the canvas editor. The menu items now go through AppDelegate onMenuUndo/onMenuRedo to the
editor (edit:undo/edit:redo, web-apps Desktop.js clicks the header Undo/Redo; no-op with a modal open);
inputs/iframes reply edit:native and keep the browser undo. Redo shown as Shift+Cmd+Z (Cmd+Y still
works) (desktop-apps 674be1df2, web-apps 896bea2db7; test issue-0388-mac-edit-menu-undo). Checked in an
app clone with a relinked executable; a real click with the app in front and detached editor windows
not checked. Needs a full app build to ship (storyboard + AppDelegate).

### #73 - Cmd+Up/Down on macOS moved one line - FIXED 2026-11-11
Cmd+Left/Right and Option+Left/Right (with Shift) already behave as macOS in 9.4. Cmd(+Shift)+Up/Down
acted as plain Up/Down in documents and slide text and did nothing in the cell editor; on macOS they
now do Ctrl+Home/End (word Document.js, slide Presentation.js, CommonController.js, CellEditorView.js);
a selected drawing keeps Cmd+arrow as nudge (sdkjs 33475b76ae; test issue-0073-mac-cmd-up-down-test.js).
PDF form/annotation text not covered.

### #565 - math i/j under an accent (\vec, \dot) blank or a stray glyph - FIXED 2026-11-11
word/Math/mathText.js private_getCode turns an accented i/j into Cambria Math glyph numbers and Draw
drew that number in whatever font was loaded - wrong on macOS/Linux (no Cambria Math) and for runs with
their own w:rFonts. The glyph-number path now applies only when the loaded family is "Cambria Math";
otherwise a dotless code point the font has (U+1D6A4/1D6A5, else U+0131/U+0237, else the letter)
(sdkjs aa43ce0290; test issue-0565-accent-dotless-ij-test.js). On-screen editor not GUI-checked.
Separate, unfixed: the reporter's display equation lands at the right edge in x2t output.

### #661 - windows open under a top panel (Linux) - FIXED 2026-11-11 (Linux part)
Utils::getScreenGeometry's Linux branch returned the whole screen, panels included (Windows returns
rcWork), so CWindowBase::startRect kept saved/cascaded rects above the bottom of a top panel, and the
frameless window was not pulled back by the WM. Now availableGeometry - the X work area (desktop-apps
706e29c81; test issue-0661-linux-start-rect-workarea, real Qt 5.15 on Xvfb with _NET_WORKAREA).
Windows report unexplained (startRect already clips to rcWork; suspect frameless WM_NCCALCSIZE margins).

### #905 - drag and drop on Linux: defects in the existing drop path - FIXED 2026-11-11
Linux drops have worked since upstream 2023 (desktop-sdk 405e1864, f3181f31); the defects in that path:
QCefView::convertMimeData used QUrl::toString(), so %23/%25/%3F stayed encoded and a.png names with
#, % or ? dropped nothing; CAscDragDrop::CreateEvent deleted CR/LF from dropped text; a quote in a
dropped file name made a JS syntax error (backslash silently eaten). Now toLocalFile(), escaped text,
EscapeJSString (desktop-sdk 11818b60). The GTK Insert > Image filter hid *.JPG (case-sensitive
patterns) - now bracket globs (desktop-apps eea379f8a). Tests issue-905-linux-drop,
issue-905-gtk-filter-case. A real XDND drop from Nautilus/Dolphin not run (no Linux app build).
Also (#927 neighbour): plain-text paste with lone CR became one paragraph and a trailing CR was
inserted as a character; _pasteText now normalises CRLF/CR to LF (sdkjs d60507f1e5; test
issue-927-paste-lone-cr-test.js). Slide/PDF paths share it but were not run.

### #2119 - Shift pressed during a row/column drag did not insert between rows - FIXED 2026-11-11
Insert-move existed (upstream b8f32d7549) but Shift counted only if held at mousedown on a header:
_moveRangeHandle sent {ctrlKey, shiftKey} once and changeSelectionMoveRangeHandle stored them once,
so Excel's gesture (Shift after the drag starts) and border drags never inserted; the insert line also
lagged one move. Live shiftKey now flows through WorkbookView into colRowMoveProps (sdkjs ff0514e5b7;
test issue-2119-shift-drag-insert-rows-test.js). Insert-line painting and the dropped data need a GUI check.

### #1167 - a Google Docs link from a Drive mount opened Google's editor in a tab - FIXED 2026-11-11
On a GNOME Google Drive mount a native Google document is a shortcut to its docs.google.com page, and
handleInputCmd opened any http(s) argument as a web tab. docs.google.com/drive.google.com links (exact
host) now go to the system browser (desktop-apps 82e255608; test issue-1167-google-doc-link). Linux
compiled, Windows not; .gdoc/.gsheet files from Drive for desktop not handled; macOS path untouched.

### #1000 - idle document used several times the CPU of an idle spreadsheet - FIXED 2026-11-12
PaintMessageLoop._animation (sdkjs common/Drawings/WorkEvents.js) requested an animation frame every
frame forever just to check whether 40 ms had passed, waking renderer and compositor 60-120 times a
second (word, slide, visio; cell has no such loop). Between engine runs it now sleeps on a timer at the
same 40 ms cadence; wake() returns to the next frame for scrolling (#2375 kept); hidden views unchanged
(sdkjs 0bd49ef617; test issue-1000-idle-paint-loop-test.js; issue-2375 test given virtual timers).
App clone, 40 s idle: docx renderer 5.3% -> 1.5%, GPU 1.6% -> 0%; pptx 3.8% -> 1.1%. Linux/Windows not
measured; caret blink timer untouched.

### #694 - editor fills only part of its window with QT_SCALE_FACTOR (Linux) - FIXED 2026-11-12
qcefview.cpp SetWindowSize sized the editor's X windows with Qt logical pixels; with QT_SCALE_FACTOR=2
(common on 4K) the editor filled a quarter of its panel. Now multiplied by devicePixelRatioF (1 without
the variable) (desktop-sdk 963c2394; test issue-0694-linux-qt-scale-factor, real Qt 5.15 on Xvfb).
Drag-and-drop coordinates under QT_SCALE_FACTOR still logical; real Linux app not run.

### #1194 - touchpad scrolling in documents not smooth - FIXED 2026-11-12 (input side)
The 40 ms repaint gate was #2375. Left: checkMouseWhell truncated each wheel event to whole pixels, so
small touchpad deltas were lost (wheelDeltaY 2 never moved; -3 moved 40 of 45 px; fling tails stalled).
The word editor now carries the fraction to the next event, reset on direction change; mouse notches
unchanged; slide/visio/PDF/cell opt out (sdkjs aa8e849c33; test issue-1194-touchpad-subpixel-scroll-test.js).
Real touchpad feel not checked (CDP wheel events carry wheelDeltaY=0).

### RD-0001 - CSV row/cell limits: an extra row kept, csv->xlsx unlimited, cuts silent - FIXED 2026-11-12
#482 follow-up. x2t kept row 1,048,577; csv->xlsx had no row limit; ASCConverters overwrote the read's
94/96 with 0; the desktop dropped the code. Now the sheet stops at the limit, csv->xlsx returns 94, and
the open passes 94/96 to the spreadsheet, which warns that rows / cell text were cut (core 9eed63b760,
desktop-sdk 95c61da6, web-apps ffc735fa93; tests rd-0001-csv-row-limit, rd-0001-csv-open-limits).

### RD-0002 - macOS showed Sparkle's update prompt and menu with no appcast - FIXED 2026-11-12
Main.storyboard no longer instantiates SUUpdater or the "Check for Updates..." item (desktop-apps
09c48fb4e; test rd-0002-mac-no-sparkle-updater-test.js). Needs a full app build to ship.

### #2463 - a comment added from a macro showed twice in the Comments panel - FIXED 2026-11-12 (backport)
AddCommentToDocument (word/apiBuilder.js) called sync_AddComment after CDocument.AddComment, which
already does; backport of upstream 551cb909f3 (bug 83298) (sdkjs 3fae1156fb; test
issue-2463-macro-comment-twice-test.js). Docbuilder: 2 events before, 1 after.

### #2469 - left column of a 2-column section after a continuous break not drawn - FIXED 2026-11-12 (backport)
Recalculate_PageColumn's PrevPage|Column branch re-initialised the whole section, so stepping back to the
right column reset the left one, never laid out again; backport of upstream 0f67b0544a (bug 81956)
(sdkjs ba6466c2e1; test issue-2469-two-column-left-column-lost-test.js). Reporter's file: 256 -> 493 words.

### #2188 - document macros ran on a click (and custom functions on open) with no warning - FIXED 2026-11-12
SECURITY. A shape/form button with an assigned macro (it can be styled as a link) ran on one click
under every macros setting, and custom functions saved in an .xlsx were eval'd while opening. Now a
click asks (asc_onMacrosRunRequest, same rules as the autostart warning, No default, "remember"), and
file custom functions wait for consent (#NAME? until then; kept on save) (sdkjs b6a9dee535, web-apps
f8b289bf97; test issue-2188-macro-click-consent-test.js). Embed/mobile viewers no longer run macro
clicks. Open: functions saved through the Macros dialog go to localStorage and then run everywhere.

### #2288 - ROW(INDIRECT("2:N")) reported a false circular reference - FIXED 2026-11-12
recheckCellForCycle flagged any formula whose cell lay inside a saved INDIRECT/OFFSET result, whatever
consumed it, and the store kept one slot per function name. Now every result is kept (cap 256) and
ROW/ROWS/COLUMN/COLUMNS discard the one they consumed by identity; unmatched stays saved, so a real cycle
is never missed (sdkjs c996b1857c; test issue-2288-row-indirect-false-cycle-test.js, docbuilder end to
end, 5 positional + 6 genuine cycles). Test app: =ROW(INDIRECT("1:3")) in row 1 gives 1.

### #1233 - pasting web content with images froze the editor - FIXED 2026-11-12
http(s) images now download in one async DownloadFiles batch (BlockInteraction/LoadImage as on the web),
30 s JS timeout; file:// and data: stay synchronous (sdkjs 3b3a0125ea; test
issue-1233-paste-image-download-async-test.js). App clone, 3 images x 3 s: paste call 22.7 s -> 4 ms,
largest main-thread gap 22.9 s -> 0.4 s. Native on_download_files builds JSON unescaped (a URL with "
never calls back; the timeout covers it).

### #1710 - Flatpak without network: every file opened a new instance - FIXED 2026-11-12 (Linux)
SingleApplication found the first instance over UDP 127.<uid>.1:13012, which exists per network
namespace, and --unshare=network gives each flatpak run its own. With a runtime dir it now uses an
AF_UNIX socket there ($XDG_RUNTIME_DIR/app/$FLATPAK_ID under Flatpak) with an flock, UDP as fallback
(desktop-apps eecac8e78; test issue-1710-flatpak-single-instance). Old and new instances won't find each
other during the transition. Real Flatpak not run.

### #1433 - a missing GSettings schema killed the app (AppImage/toolbox) - FIXED 2026-11-12 (Linux)
We build no AppImage, but cnotification.cpp isNotificationsEnabled called g_settings_new for GNOME/Cinnamon
notification schemas, which aborts when the schema/key is missing, and unref'd a GVariant with
g_object_unref. Schema and key are now looked up first (desktop-apps a314de8d2; test
issue-1433-gsettings-missing-schema).

### RD-0003 - special paste with no clipboard data threw a TypeError - FIXED 2026-11-12
initSpecialPasteData called _callback() on null paste_data and then dereferenced it; added the return
(sdkjs 12e566a791; test rd-0003-special-paste-null-data-test.js).

### #572 - PDF export recompressed most JPEG photos - FIXED 2026-11-12
NSImageReSaver::CorrectImage (core PdfFile/SrcWriter/Image.cpp) re-encoded a JPEG at q85 whenever
"Adobe"/"Photoshop" appeared in its first 10 KB - true of nearly every XMP packet and Photoshop APP13,
so photos from Photoshop, Lightroom, Preview/sips and many cameras lost quality. Now the frame header
decides: re-encode only CMYK/YCCK or APP14 Adobe (core eb2c12c2b7; test issue-0572-pdf-jpeg-passthrough;
relinked x2t: a sips q100 JPEG now embeds byte-identical). PNG -> JPEG q85 is unchanged upstream design.

### #1829 - user names with a comma or ' refused; & # + % broke the editor on macOS - FIXED 2026-11-12
The start page's name whitelist refused "Doe, John" and O'Brien (typographic '). On macOS the editor URL
parameters were joined unencoded, so "Tom & Jerry" became "Tom ", "C# Team" lost lang/theme, and
"100% Smith" threw URIError and no editor opened. Whitelist widened; macOS percent-encodes the parameters
as Windows/Linux do (desktop-apps d269d54a3; test issue-1829-user-name-chars). Needs a loginpage and app
rebuild to ship; not GUI-checked.

### #615 (part 1) - page background painted without w:displayBackgroundShape - FIXED 2026-11-12
Word shows a w:background only when settings.xml has displayBackgroundShape (ECMA 17.15.1.25). core
BinaryWriterD never passed the flag and BinaryReaderD turned it on at every save, so we painted the page
and every save made Word paint it too. A Background DisplayShape byte (c_oSerBackgroundType 100: absent /
on / val=0) now carries the flag both ways; sdkjs draws the page only when it is on or the colour was set
in the editor (core 4dc21d337a, sdkjs ecd1f58829; tests issue-0615-display-background-shape-core and
-test.js). Test app: the reporter's file edited and saved keeps <w:background w:color="00B8FF"> and gets
no flag. Part 2 (the wrapped "4.1") remains open. Also #883 follow-up: FREQUENCY now returns counts in the
bins' original order and ignores text/bool bins, as Excel/LibreOffice (sdkjs 0bb6ae9857; test
issue-0883-frequency-bin-order, docbuilder).

### #2501 - changing resolution / moving screens breaks the layout (Linux) - FIXED 2026-11-12
The CEF editor re-zooms for its screen on every resize, but the Qt chrome is re-scaled only by
CWindowBase::updateScaling, which on Linux nothing has called since upstream cdc9803fe (2022) - so after a
screen change the tabs stayed at the old scale. CWindowPlatform::event now re-runs updateScaling (deferred)
on QEvent::ScreenChangeInternal (desktop-apps 276791931; test issue-2501-linux-screen-change-rescale, real
Qt on a two-output weston). Real mixed-DPI screens not run.

### #247 - no practical key to edit a filled cell on a Mac - FIXED 2026-11-12 (macOS)
F2 already edits in place, but Mac keyboards need fn. On macOS Control+U now opens the cell editor, as
in Excel for Mac; Underline stays on Cmd+U (Control+U no longer underlines) (sdkjs 4acf06a079; test
issue-0247-mac-edit-cell-key-test.js).

### #206 - paragraphs pasted from LibreOffice lose their spacing - FIXED 2026-11-12
LibreOffice puts Text Body spacing only in the clipboard HTML's style sheet; _set_pPr read inline styles
only. Margins and line-height now also come from matching rules of the pasted document's own sheets
(later rules win; specificity not compared). Word HTML with class-rule spacing benefits too (sdkjs
19a6e7a7bd; test issue-0206-paste-stylesheet-spacing-test.js, real code in Chromium). Real LibreOffice
clipboard not run.

### #2075 - no way to turn off non-breaking spaces before French punctuation - FIXED 2026-11-12
The FrenchPunctuation autocorrect flag existed but nothing could set it. New api + AutoCorrect checkbox
"Non-breaking spaces with French punctuation" in the document and presentation editors, on by default
(sdkjs 7a99b84860, web-apps 196bada5b0; test issue-2075-french-punctuation-option-test.js).

### #143 - no way to choose the language of new documents - FIXED 2026-11-12
File > Advanced settings > "Default document language" (desktop, word editor), "Same as the interface"
by default; applied to new blank documents only (web-apps 869747e03c; test
issue-0143-default-doc-language-test.js). #626's automatic use of the OS language is a design decision,
not done; slides/sheets not covered.

### #432 - units ignore the OS Region (inches in the US) - FIXED 2026-11-12
Windows/Linux already sent location=<country> but the desktop editor page dropped it, and macOS never
sent it. web-apps passes it to editorConfig.location; macOS sends NSLocale's country, so a fresh profile
in a US/CA Region starts in inches (web-apps 367ff6911d, desktop-apps 1591170a48; test
issue-0432-os-region-units). Windows reads the system (not user) locale; Linux C locale sends EN.

### #1594 - no way to stop keeping recent files - FIXED 2026-11-12
New start-page switch "Keep a list of recent files" (on by default); off clears the list, stops
recording (Recents_Add/Recents_Load check disable-recents), and on Windows/Linux stops adding to the
system recent documents (desktop-sdk 7597f17a, desktop-apps 2d2ba2b25a; test
issue-1594-disable-recents-test.js). Not GUI-checked; needs an app rebuild.

### #1513 - pinned recent files vanished or showed twice - FIXED 2026-11-12
Pinning existed but our search history (2fa3fc844) made panelrecent's find('.file-list-body') match two
lists, so pinned rows went into the hidden one or appeared twice; now children() (desktop-apps
fc625f1ea2; test issue-1513-pinned-recents-test.js; checked live in an app clone). Not fixed: no lasting
pin marker in the reskinned list; "0 files" count after load.

### #167 - no shortcut for the word count - FIXED 2026-11-12
Ctrl+Shift+G / Cmd+Shift+G (Word's key) opens File > Document Info with the counts (web-apps 35bc28f2f3;
test issue-0167-word-count-shortcut-test.js; live via CDP). The macOS menu's Find Previous on
Cmd+Shift+G needs a GUI check.

### #617 - Insert > Image > From file took one picture - FIXED 2026-11-12
All four editors request several files and insert all of them (AscCommon.getDesktopImageUrls); the macOS
open panel allows multiple selection when asked (sdkjs 4dcd75bc18, desktop-apps 2fceb40b24; test
issue-0617-insert-multiple-images-test.js). Side effect: other macOS multi-file callers now get several
files, as on Windows/Linux. Needs an app rebuild and GUI check.

### #670 - no "Report an issue" link in About - FIXED 2026-11-12
Start-page About and the native macOS About window link to https://ration.works/support (the SUPPORT_URL
already in package/Makefile) (desktop-apps ab21b214c8, d8de43be2e; test issue-0670-about-report-issue-test.js).

### #1230 - a new UI language reached new editors only after a relaunch (macOS) - FIXED 2026-11-12
The settings:apply handler took the editors' lang from [NSLocale currentLocale], cached for the life of
the process; it now stores the language first and uses ASCLinguist appLanguageCode (desktop-apps
5c8da46e06; test issue-1230-mac-language-new-editors). Already-open documents keep their language.

### #1450 - a user-installed Last Resort font took every CJK fallback - FIXED 2026-11-12
ApplicationFontsWorker ranks non-priority families by file size; Last Resort maps every code point and is
small, so it won all ranges (345 -> 3). Last Resort* families are now skipped when building the range
table, still selectable by name (core dc5f520a6a; test issue-1450-last-resort-fallback, real allfontsgen).

### #1270 - no Ctrl+Q to quit on Linux - FIXED 2026-11-12
Ctrl+Q now closes every window with the usual save prompts (desktop-apps dc2314a372; test
issue-1270-linux-ctrl-q-quit). Not run live on Linux.

### #870 - zoom steps stopped at 50% - FIXED 2026-11-12
The zoom box accepts 10-500%, but Ctrl+-, Ctrl+wheel and the minus button stopped at 50% in documents,
presentations and PDFs; their step lists now start at 10% like visio's (sdkjs 34252d945d; test
issue-0870-zoom-steps-below-50-test.js).

### #1490 - Ctrl+S on a multi-sheet csv silently dropped all but one sheet - FIXED 2026-11-12
DATA LOSS. A plain Save of a file opened from .csv/.tsv wrote CSV again with only the active sheet and no
warning. With more than one sheet it now asks first (the existing, translated warnDownloadCsvSheets);
Cancel - the default - opens Save As (sdkjs 80e0954ad1, web-apps b1ddc7a260; test
issue-1490-csv-save-multisheet-warning-test.js). GUI flow not run.

### #766 - middle-click to close tabs (already in 9.4); macOS side buttons closed tabs - FIXED 2026-11-12
Middle-click close exists (upstream bug 51040). Defect: macOS -otherMouseDown: acted on every other
button, so back/forward side buttons closed the tab under the pointer; now only button 2 (desktop-apps
8c8ec5f91b; test issue-0766-mac-middle-click-tab-close).

### #1847 - reopen a closed tab (Ctrl/Cmd+Shift+T) - FIXED 2026-11-12 (feature)
Per-session list of closed local documents (newest last, unique, max 20, deleted files skipped); macOS
File > Reopen Closed Tab (Shift+Cmd+T), Ctrl+Shift+T on Windows/Linux (desktop-apps b76fc9693a; test
issue-1847-reopen-closed-tab). Restoring all tabs after quit not done (design). Close-then-reopen not run
live.

### #858 - full screen shortcut - FIXED 2026-11-12 (macOS)
Ctrl+Cmd+F did nothing (our View menu is hidden, so AppKit added no full-screen item); Window > Enter
Full Screen now binds it (desktop-apps 483116cf19; test issue-0858-mac-full-screen-shortcut). Windows/
Linux F11 not done: whole window vs document-only is a design decision, and the custom frame needs a
Windows GUI.

### #200 - Ctrl+N for a new document - FIXED 2026-11-12 (Windows/Linux)
macOS already has File > New shortcuts (Ctrl+Shift+D/S/P/T). On Windows/Linux Ctrl+N in an editor sends
create:new for that editor's type (desktop-apps 283bb57d3f; test issue-0200-ctrl-n-new-document).

### #669 - About should show the package type - FIXED 2026-11-12 (Linux)
deb/rpm/exe/msi already shown from package.config; Flatpak/Snap/AppImage builds said "deb". About now
detects the sandbox it runs in (desktop-apps ec03992720; test issue-0669-about-package-type).

### #1144 - dates in the Recover files list - FIXED 2026-11-12
The start page's "Autosaved" column was always empty: Recovers_Load never set the date. It now takes the
time of the recovery folder's last change (desktop-sdk bdbd5c35; test issue-1144-recover-list-dates).

### RD-0004..RD-0018 - converter crashes and memory errors from a public-corpus run - FIXED 2026-11-12
x2t run (release + ASan/UBSan) over Apache POI, LibreOffice and Tika test documents; each distinct root
cause fixed with a minimised reproducer test (fork-fix-tests/rd-NNNN-*), core 001b1246fd..ccddc3317b.
Built with Apple clang 21 after patching boost 1.72's numeric/conversion as boost 1.81 did
(.rd-work/bin/patch-boost-clang21.sh - build-output headers only).
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

### Linux x64 2026.2.0 .deb - built and GUI-checked 2026-11-12
Clean build with build_tools in Docker (recipe: build_tools/LINUX_X64_DESKTOP_BUILD.md); the .deb installs
into a clean ubuntu:24.04 and passes docx/xlsx/pptx/pdf open-edit-save with our x2t. GUI checks PASS:
#905 (file and text drop, GTK filter), #1270, #200, #1847, #661, #694, #1710 (incl. --network none), #706,
#790 (GTK), #669, #1664 (remote-frame bridge, program link refused, rdplugin), #1594, #1513. #2501 not
testable on Xvfb; #1433's fixed path is unreachable in this build (no notification callers).
Build fixes: build_tools 43ede6b (v8 libstdc++ swap without sysroot), desktop-apps d2eb1a70e (deb
Depends: NSS, xcb-util). Defects found and fixed: #1144 date column hidden by CSS (desktop-apps
68827a107; test issue-1144-recover-date-visible-test.js); RD-0019 second-launch handoff decoded UTF-8 as
local 8-bit (desktop-apps 687091511; test rd-0019-handoff-utf8); a committed node_modules symlink
removed (8ef70c799). Known, not fixed: an empty ~/.local/share/ONLYOFFICE is created at start
(core SystemUtils GetBuildBranding defaults to ONLYOFFICE unless OO_BUILD_BRANDING is set, which would
also move build output paths); with QT_SCALE_FACTOR=2 a saved full-work-area window may open with its
status bar off-screen (observed once). The package needs glibc 2.39 (Ubuntu 24.04+ / Debian 13+).

### #2504 / #926 / #1085 / #220 - choose the window title bar in Settings (Linux) - DONE 2026-11-12 (after 2026.2.0)
Start page "Title bar: Built-in / System (window manager)" (restart), stored in the existing `titlebar`
key the --system-title-bar/--custom-title-bar switches used; a stored system title bar no longer shows
the document name twice in the editor header (desktop-apps dedc2f770; test
issue-2504-title-bar-setting-test.js). #1085 button-style choice and #220 left-side buttons in the
built-in bar not done. GUI check on Linux pending; earlier 9.0 reports of a crash with the system title
bar not reproduced by reading (null check 6b1d57d60 present) - check on the Linux box before shipping.

### #1899 - window buttons: "Close only" option (Linux) - DONE 2026-11-12 (after 2026.2.0)
"Window buttons: Minimize, maximize and close / Close only" (restart); createTopPanel hides
minimize/maximize, editor title stays centred (desktop-apps b61080a05; test
issue-1899-window-buttons-close-only-test.js).

### #982 - save a copy in another format without changing the open document - DONE 2026-11-12 (after 2026.2.0)
Any desktop Save As into an editable format made the new file the open document (an xlsx saved as CSV
became a CSV). The existing "Save Copy as..." is now shown on desktop and writes the chosen format while
the open document keeps its path, format and lock (sdkjs ab8d889574, desktop-sdk 37781973, web-apps
08a278ff9c; test issue-0982-save-copy). Hidden under blockchain encryption. GUI flow not run.

### #517 - choose the format for new documents - DONE 2026-11-12 (option, default unchanged)
Advanced settings "Format for new documents": Office Open XML (default) or OpenDocument; the first save
of a new document preselects it (sdkjs b5d8ce9cd5, desktop-sdk 3ce41d06, web-apps ed400de638; test
issue-0517-new-file-save-format). Dialogs not GUI-checked.

### #1885 - hyperlinks on slide shapes/pictures/groups missing from PDF export - FIXED 2026-11-12
Only text hyperlinks were emitted; Slide.draw never passed cNvPr.hlinkClick. Linked objects now become
URI or page links, recursing into groups (sdkjs d54317276d; test issue-1885-pdf-shape-hyperlinks-test.js).
Spreadsheet cell hyperlinks still not exported to PDF.

### #222 - correct TWo INitial CApitals - DONE 2026-11-12 (option, off by default)
New autocorrect step + AutoCorrect checkbox in the document and presentation editors; skips CDs/IDs, units,
words after a digit; Turkish/Azeri I -> ı; one undo step (sdkjs 1fd3361a6e + 9f04793a12, web-apps
49cd3bbf26 + 6c1edee61f; test issue-0222-two-initial-capitals-test.js). Off by default by the
product owner's rule that new behaviour is opt-in (Word ships it on).

### #630 - remove a word from the user dictionary - DONE 2026-11-12
Native spellchecker gains list/remove tasks (rewrites all.dic, reloads hunspell); api
asc_spellCheckGetUserDictionary/RemoveFromDictionary; a "Dictionary..." dialog in the document,
presentation and spreadsheet editors (desktop-sdk 852aa207, sdkjs 50339e12a4, web-apps 3f20b3a7fc; tests
issue-0630-remove-from-dictionary, -ui-test.js). Dialog not GUI-checked.

### #195 - use the system's hunspell dictionaries on Linux - DONE 2026-11-12
Scans /usr/share/hunspell and myspell for <lang>_<REGION> UTF-8 dictionaries we do not ship; ours always
win (desktop-sdk 7e446b0c; test issue-0195-system-hunspell-dictionaries). Not run in a Linux app yet.

### #201 / #1363 / #1177 / #2139 / #2436 - start page and tabs - DONE 2026-11-12 (after 2026.2.0)
#201 right-click Recent folders: Open, Pin/Unpin, Remove from list (desktop-apps cfbce8138). #1363 the
editors' Feedback & Support hint and the About links say they open the web browser (desktop-apps
3ff2db754, web-apps 73e0f992ea). #1177 Windows Settings "Make Ration Docs the default app for all
supported files" (ae489fe2a; association.cpp not compiled - no Windows build here). #2139 option: Ctrl+Tab
in most-recently-used order (52e500360, off by default). #2436 option: colour strip on tabs by document
type (c2acc77f5, off by default); 7d706cb3c resolves the shared settings hunks. Tests issue-0201-*,
issue-1363-* (2), issue-1177-*, issue-2139-*, issue-2436-*. GUI checks pending on all.

### #1905 / #1521 / #2160 / #2033 - spreadsheet and numeral requests - DONE 2026-11-12 (after 2026.2.0)
#1905 Move sheet to a new workbook acted as Copy; the sheets are now deleted here once the new tab has them
(sdkjs d829164103). #1521 option: highlight the active row/column (None / both / row / column, off by
default; sdkjs b749c681ab, web-apps 92fcc5c556). #2160 Numeral "Context": Hindi digits in RTL paragraphs,
Arabic elsewhere (sdkjs 84afc71c38, web-apps aaa725f624). #2033 Persian (Jalali) calendar in number formats
[$-fa-IR,16] / [$-xx0429] (sdkjs 177bd1c53b). Tests issue-1905-*, issue-1521-*, issue-2160-*, issue-2033-*.
GUI checks pending (row/column tint, Move dialog, numeral combo).

### #83 / #2321 / #2258 / #2404 / #1522 / #2130 - parked design suggestions resolved - DONE 2026-11-12 (after 2026.2.0)
#83 DATA INTEGRITY: Ctrl+S on a CSV opened with another delimiter/code page rewrote it as comma/UTF-8 (shown
with real x2t); the open-time options are now kept for Ctrl+S, Save As offers a semicolon CSV (desktop-sdk
6afd78af, desktop-apps 8dc58c398). #2321 option: portal file dialog on X11 (116bd6a1d, off by default).
#2258 option: Ctrl+D/Ctrl+R fill down/right in the grid, shape text keeps Ctrl+R (sdkjs 343dd2ce50, web-apps
d4d05aaed8, off by default). #2404 the app decided "portable" from the current directory's package.config;
now beside the executable, and make_zip.ps1 documented/guarded (f379f0bf7). #1522 GTK_IM_MODULE=fcitx only
when XMODIFIERS says fcitx and it is unset (301edac68). #2130 --disable-lcd-text when the desktop's Xft.rgba
is "none" - follows the user's own desktop setting, no change otherwise (desktop-sdk 54c6d5d6). Tests
issue-0083-*, issue-2321-*, issue-2258-*, issue-2404-*, issue-1522-*, issue-2130-*. Windows not compiled;
Linux GUI checks pending.

### #603 / #322 / #1203 / #1292 / #179 - links, comments, lists, menus, shortcuts - DONE 2026-11-12 (after 2026.2.0)
#603 tel: links accepted like mailto and opened at once when they hold a phone number; other tel: text still
asks (sdkjs f7223cbbb5, desktop-sdk 9cda0a45). #322 search box in the Comments panel (text, quote, author,
replies) in all editors (web-apps 62bf4b1e8b). #1203 Alt/Option+Shift+Up/Down move the selected paragraphs
(list items) up/down, one undo step, comments kept (sdkjs 63f1738698, web-apps 4729f16bc5) - these keys used to
fall through to selection-extend; rebindable. #1292 context menus: typing a letter picks/focuses the item
starting with it (web-apps 9e2a4c5e94). #179 the shortcuts search ignores spaces and searches descriptions
(web-apps 459948889e). Tests issue-0603-*, issue-0322-*, issue-1203-*, issue-1292-*, issue-0179-*.

### #2239 / #2466 / #1438 / #2180 - plugins, AI, dictionaries, SVG paste - DONE 2026-11-12 (after 2026.2.0)
#2239 AI agent providers take hand-entered model IDs (desktop-sdk 42a94cd1; ai-agent deploy rebuilt
reproducibly). #2466 option (off by default): bundled plugins can be hidden in the Plugin Manager and
restored; the app folder is never written (desktop-sdk 1db9f146, sdkjs 532aac2b28, desktop-apps 6c7c62a2b,
onlyoffice.github.io bea6535b on its new ration/v10-backports branch). #1438 Settings > "Add spelling
dictionary..." installs a UTF-8 hunspell pair into the user folder, user dictionaries win (desktop-sdk
4efb34f6, new header spell_dictionaries.h; desktop-apps 3fb2865cc). #2180 an SVG copied from Inkscape-like
apps pastes as a vector picture, plain SVG text still pastes as text (sdkjs 8c1cd0c54a). Tests
issue-2239-*, issue-2466-*, issue-1438-*, issue-2180-*; issue-0195/0630/676/2543 tests updated for the new
code. macOS .mm edits for #2466 not compiled; GUI checks pending.

### RD-0020 / #2003 / #2007 - slide media settings - DONE 2026-11-12 (after 2026.2.0)
RD-0020 DATA LOSS: CTiming.buildTree rebuilt the timing root on every animation edit and dropped the
p:video/p:audio media nodes (mute, volume, loop, hide, full screen); they are now carried over (sdkjs
8cdef5ad4c; test rd-0020-media-node-kept-on-animation-test.js). #2003 Playback > Mute for video/audio, and the
players no longer let a remembered volume override the file's mute (sdkjs 3d36688e80, web-apps 28c61dfec1,
desktop-sdk b4273817; test issue-2003-media-mute). #2007 "Hide while not playing", honoured in the show -
decks already carrying PowerPoint's showWhenStopped="0" now hide the video as PowerPoint does (sdkjs
7eef14211f, web-apps 93947f7455; test issue-2007-*). GUI checks pending.

### #1674 / #746 / #852 / #1969 - editing workflow - DONE 2026-11-12 (after 2026.2.0)
#1674 option (off): closing a modified local document we can write in place saves it without asking, via the
normal save (#2000 safe path); new/template/cloud/read-only still ask (desktop-apps 6093e48df). #746 option:
default font and size for new blank documents (sdkjs c951cbc881, web-apps 2518219af3). #852 option: Shift+wheel
scrolls sideways in document/presentation/PDF editors on Windows/Linux (sdkjs 6eddf61a54, web-apps 8604aeacb2).
#1969 "From clipboard" for slide background / shape picture fills (web-apps 72a998da54). Tests issue-1674-*,
issue-0746-*, issue-0852-*, issue-1969-*. GUI checks pending.

### #2299 / #2422 / #1215 - printing - DONE 2026-11-12 (after 2026.2.0)
#2299 print panels: "Only odd pages" / "Only even pages" for the range, sent as an explicit page list (web-apps
55387961da). #2422 "Print on both sides manually" on Windows/Linux: odd pages, prompt to turn the stack, even
pages (web-apps 720bbc9976; macOS prints through its own panel). #1215 (part) Linux: the GTK dialog's "Pages per
side" now reaches CUPS (desktop-apps 04a0d87d2; test prints a real QPrinter job to a CUPS queue). Tests
issue-2299-*, issue-2422-*, issue-1215-*. Pre-existing: the macOS Print button ignores the in-app page range.

### #2544 / #2137 / #2112 - presentation and theme requests - DONE 2026-11-12 (after 2026.2.0)
#2544 video/audio files dropped on a slide are inserted as by Insert > Video/Audio (sdkjs 660fdeb7c9). #2137
option: "Use this size for new presentations" in the Slide Size dialog (web-apps ad9ffc4e5f, off until ticked).
#2112 (dark part) the document dark-mode page colour comes from the theme (canvas-dark-content-background,
#3a3a3a in every built-in theme), so a true-black theme is possible; example theme
resources/themes/black-theme-dark.json.example; also fixed a page-fill colour that lost leading zeros
(sdkjs 96dcdf31dd, web-apps fe6457de1f). Tests issue-2544-*, issue-2137-*, issue-2112-*. GUI checks pending.

### #1872 - screen readers saw nothing on macOS (VoiceOver) - FIXED 2026-11-12 (after 2026.2.0)
Nothing ever called CefBrowserHost::SetAccessibilityState, so Chromium kept the page's accessibility tree off
and VoiceOver saw only the window title. NSAscApplication now handles AXEnhancedUserInterface /
AXManualAccessibility and checks VoiceOver at launch; every browser is enabled while a screen reader runs
(desktop-sdk 61e4e166, new header accessibility_state.h; test issue-1872-screen-reader-accessibility-test.js).
No change without a screen reader. Document body is canvas and stays unreadable. Needs a real VoiceOver check.

### #100 / #947 - document variables lost on save; cell vertical alignment in the panel - FIXED 2026-11-12
#100 DATA LOSS: w:docVars (the values DOCVARIABLE fields read) were dropped on every save from the editor, so
Word showed "Error! No document variable supplied"; now carried through the binary (settings item DocVars=100)
and escaped on write (core 48a2f86930, sdkjs 87ae50a92a; tests issue-0100-docvars-core, -sdkjs-test.js).
No UI to edit variables. #947 Table settings panel gains Top/Middle/Bottom cell alignment (web-apps 34fa78bf7d).

### #69 / #1814 / #2342 - macOS menus and interface scaling - DONE 2026-11-12 (after 2026.2.0)
#69 File > Open Recent lists and opens recent local documents (was a hidden, never-fed AppKit menu) (desktop-apps
6aa7e7249c). #1814 Window > Move Tab to New Window (607339b530; drag-out and the open-in-window setting
already existed). #2342 interface scaling in 5% steps 100-150% on Windows/Linux (02d1fc2f6c). Checked live in an
app clone with lldb (#69, #1814). Tab-UI redesign not done.

### #780 / #211 - EMF/WMF pictures; OCR for TIFF - FIXED 2026-11-12
#780 the engine already inserts EMF/WMF as vector pictures but no image dialog offered them; now all do
(desktop-apps a52f7eca4). #211 the OCR plugin dropped TIFF pictures silently (Chromium cannot draw them) and
gave no message for unreadable files; TIFF now goes to tesseract and failures are reported (onlyoffice.github.io
94a3e9c5 on ration/v10-backports). Tests issue-780-*, issue-211-*.

### #1695 / #888 / #736 / #1355 / #141 - themes, languages, fonts - DONE 2026-11-12 (after 2026.2.0)
#1695 the full custom-theme examples were invalid JSON and missed ~55 tokens; now valid and complete, with where
to put them (web-apps c1f5d70991; no custom themes on macOS yet). #888 example dark theme with coloured headers,
and the native Visio header read a non-existent token (web-apps 23698b98ea, desktop-apps 18fd77fc1). #736 the PDF
loading page was white in dark document mode and the document one ignored the theme's page colour (web-apps
0a9d55094d). #1355 az / eu / ms translations shipped but were not selectable; now in the language lists - Linux
with such a system locale now starts in it (desktop-apps 76994a700). #141 Windows: fonts activated by Adobe
Creative Cloud (CoreSync livetype) are found (core a60044ddd3; macOS already sees them via CoreText). Tests
issue-1695-*, issue-0888-*, issue-0736-*, issue-1355-*, issue-0141-*.

### #2477 / #591 - macOS .pkg; per-editor Linux launchers - DONE 2026-11-12 (tooling, release build unchanged)
#2477 desktop-apps/macos/make_pkg.sh builds a non-relocatable product .pkg with the binary's real architectures
and min OS, optional Developer ID Installer signing (desktop-apps 2ca197455; test issue-2477-macos-pkg; a real
1.04 GB pkg built from the test app). #591 option EDITOR_LAUNCHERS=1 in package/Makefile adds Linux launchers
for Document / Spreadsheet / Presentation / PDF Form (desktop-apps 4d3ee8ad5; test validates them with
desktop-file-validate). Neither is wired into the release build. #151/#2548 documented in DISTRIBUTION.md.

### #858 / #2106 / #34 - F11 full screen; more Windows associations; main-window file drop - DONE 2026-11-12
#858 on Windows/Linux F11 toggles whole-window full screen (tabs and title bar stay), F11 again leaves; slide show
untouched (desktop-apps b205e256b; test issue-0858-f11-window-full-screen, Qt on Xvfb/XWayland). #2106 the Inno
installer registers .dot .docm .xlt .ppsm .fodp .hwp .hwpx for Default apps (desktop-apps 0003042f3; test
issue-2106-more-windows-associations, ISCC + silent install under Wine - flaky harness, not rerun after rebase,
diff identical). #34 CMainWindow drop handlers were Linux-only; now on Windows too, with toLocalFile(),
case-insensitive suffixes and non-local URLs refused (desktop-apps f7e1ac479; test issue-0034-main-window-file-drop).
Windows code is not compiled yet; all three need Windows GUI checks.

### #1611 / #1847 / #1166 / #1952 / #1864 / #1925 - opt-in UI features - DONE 2026-11-12
#1611 option "Pinch to zoom" (Win/Linux, off by default) drops CEF --disable-pinch (desktop-sdk cdeb4bb7,
desktop-apps a37156b0c). #1847 option "Reopen documents from the last session at start" (off by default; local
files only; desktop-apps ccb7f894af). #1166 Advanced setting "Default page margins" for new blank documents (unset =
template; web-apps b541e516bf). #1952 Recent list name tooltip is the full path (desktop-apps a1c23fcfb). #1864 print
preview of a workbook >= 500k used cells shows "please wait" before building (sdkjs 5f7ad1f89c, web-apps 1ecc12124b).
#1925 option "Smooth scrolling with the mouse wheel" in the document editor, off by default (sdkjs 61fae925c0,
web-apps bcdb51112f). Tests issue-1611/-1847-restore-session-tabs/-1166/-1952/-1864/-1925. GUI checks pending;
native parts compiled syntax-only (Linux, macOS), Windows not compiled.

### #2002 / #2005 / #2006 - slide video trim kept (data loss); loop until stopped; rewind after playing - DONE 2026-11-12
#2002 p14:trim was dropped on every save: core Ext::toXmlWriter never wrote it, toPPTY clamped st/end at ~21 s, and
sdkjs ReadNvPr/Write_nvPr skipped the extLst. Now kept through x2t, the sdkjs save and editor round trips (core
c971b560a5, sdkjs 7b232bed78), played as trimmed on macOS and Qt and settable in Playback (sdkjs 3ac6a8d2b2,
desktop-sdk 8160bcfb, web-apps 291d879da9). #2005 Loop until stopped (repeatCount="indefinite"; players restart at the
end; sdkjs bdf76e0758, desktop-sdk a40c2229, web-apps f91cb3a707) - decks that already loop in PowerPoint now loop.
#2006 Rewind after playing (fill="remove"; sdkjs 09f9fe40f6, desktop-sdk a7c893cc, web-apps 9cf394be57). Tests
issue-2002-media-trim, issue-2002-trim-playback, issue-2005-media-loop, issue-2006-media-rewind. Not verified: Linux
compile (Docker down), Qt player actually playing, GUI; docx (wp15) trim is not written; fill="remove" for Rewind not
checked against a PowerPoint-made file.

### RD-0021..RD-0027 - converter crashes and hangs from the second corpus pass - DONE 2026-11-13
About 3,100 public files (LibreOffice core qa data, Apache POI test-data, IDPF epub3 samples, PyMuPDF resources) run one
at a time with a 1.5 GB watchdog. RD-0021 .doc comment-range bookmark tag read without bounds (WordDocument.cpp:394-437,
SIGSEGV; core 020ab05c8f). RD-0022 save as ODT: content control size from an empty font-size stack
(DocxConverter.cpp:691, SIGSEGV; c8b4a69f59). RD-0023 ODF number-columns-repeated="-1" read as 4294967295 and
allocated per column (table.cpp:91,234, >1.5 GB from a 2.8 KB file; ae54ea08c1). RD-0024 POLE CollectStreams recursed
forever on a looping OLE directory - hit by the format checker for every OLE file (pole.cpp:2396; e26964a596). RD-0025
.ppt container skip used a shadowed lPosition=0, so the reader re-parsed the stream (Records.cpp:180,214, >60 s;
cccd6bc2e3). RD-0026 .doc row properties with no PAPX grpprl (TablePropertyExceptions.cpp:59, SIGSEGV; 9e403b506b).
RD-0027 .doc main-text loop ran to FIB.ccpText past the real text, rebuilding a table per character
(MainDocumentMapping.cpp:134, >120 s -> 1 s; bf8072c917). Tests fork-fix-tests/rd-0021..rd-0027-*. 30 normal .ppt and
60 normal .doc files convert identically before and after. macOS only compiled.

### RD-0028 - encrypted .xls/.doc/.ppt crashed: stale libCryptoPPLib.a (build defect, no source change) - FIXED IN BUILD 2026-11-13
core eb34e8e49c (cherry-picked 2026-10-27) added virtual ~Decryptor() as the first virtual of CRYPT::Decryptor.
CryptTransform.cpp is compiled into libCryptoPPLib.a (Common/3dParty/cryptopp/project), which .rd-work/bin/corebuild.sh
skipped (it excludes 3dParty), so the Mac library dated 2026-09-19 kept the old vtable: IsVerify() ran the deleting
destructor (ASan heap-use-after-free, GlobalsSubstream.cpp:220/222). POI 35897-type4.xls segfaulted in the Mac test
app's x2t (2026-11-12) and the 2026-11-05 payload x2t; after rebuilding the library it reports "password required" (90).
corebuild.sh now always rebuilds the cryptopp project. The 2026.1.0 dmg (2026-09-11) predates the change. build_tools
builds the cryptopp project with the rest, so a clean build is fine; any machine building incrementally must rebuild it.
Linux 2026.2.0 .deb not yet checked (box unreachable 2026-11-13). Test rd-0028-cryptopp-lib-stale-vtable (RD_LIB).
No commit claims it, so the registry does not count it.

### #2566 / #371 / #159 - ODP import layout; Thai line breaking (option); INDIRECT to a table on another sheet - DONE 2026-11-13
#2566 three ODP->PPTX defects on the reporter's file: text before <text:line-break/> was dropped (regression 9c8b739d0e;
pptx_text_context add_line_break; core 1ee6da4394), every nested <text:list> added an empty paragraph (d398a242da), outline
levels 2+ took level 1's size (OutlineLevelStyle; 9b6b021247). 60 corpus ODPs: no crashes, changes only where expected.
#371 option "Break Thai, Lao, Khmer and Myanmar lines between words" (off by default; Intl.Segmenter word boundaries in
AscWord.ComplexScriptLineBreaker; sdkjs f302f97ceb, web-apps f1d5ed2a3f) - x2t docx->PDF breaks as the reporter expects.
#159 INDIRECT("Sheet!Table[Column]") gave #REF!, so validation lists had no drop-down (cINDIRECT parseReference had no
structured-reference branch after a sheet prefix; sdkjs e09e6b2cd5). Tests issue-2566-odp-import,
issue-0371-thai-line-break-test.js, issue-0159-indirect-sheet-table-test.js.

### #1548 / #1828 / #2008 / #527 / #348 and RD-0030 / RD-0031 - DONE 2026-11-13
#1548 slideshow screen on Windows/Linux: "Slideshow screen" setting (Automatic default, desktop-apps 56c65c602); a slideshow
from a window off the desktop edge crashed (screenAt null -> QList::at(count) abort / null deref; f0ccf9f00); with three
screens a presenter on the middle screen got the slideshow on the same screen - now the primary or next (f5d2cebf6, a
default change in that broken case only). #1828 Orca on Linux: a running screen reader (org.a11y.Status.ScreenReaderEnabled)
or --force-renderer-accessibility turns on Chromium accessibility and ACCESSIBILITY_ENABLED (35f7c442c). #2008 a fullScrn
slide video fills the slide show while playing and returns at the end, macOS and Qt (sdkjs d1ba4197ba, desktop-sdk f3d90689).
#527 "Default presentation language" for new blank presentations (web-apps 16a617195b). #348 a slide paragraph with marL=0
and a negative indent started its first line outside the text box; now clamped to the inset as PowerPoint does, checked
against the PowerPoint thumbnail in the reporter's file (sdkjs b258d6e942). RD-0030 security: dropped / inserted / save-
dialog file names were put into executed JS unescaped - a name with `"` could inject script (desktop-sdk 1fea875f).
RD-0031 "copy sheet to new workbook" replayed the source's changes0.json onto the copy - edits from other sheets landed
on it (4b3f8ce5). Linux syntax-compiled; GUI checks pending; Qt multimedia units not Linux-compiled (no QtMultimedia in
the image). #1330 (optional update service, ek wt) held: its Wine test could not run.

### RD-0050..RD-0056 (latent problems) and #2225 (Groq AI provider) - DONE 2026-11-13
RD-0050 docbuilder aborted (SIGABRT) when x2t could not start, and a failed save reported success: failed execve exited 0,
a crashed x2t counted as success (docbuilder_p.h; core fe4e8f5cfe). RD-0051 ODS round trip put a form control at row
18446744071562068031: rows without explicit height were registered with height 0 and regions::search divided by it
(table_xlsx.cpp, xlsx_table_metrics.cpp; de64a4e454). RD-0052 copying cells with a link: the <a> was never closed and
href/title went into the clipboard HTML unescaped (attribute injection) (sdkjs cell/model/clipboard.js; 63d44e1c43).
RD-0053 font ranges credited fonts with characters they lack - CSymbolSimpleChecker2 cleared its scratch marks from 0 and one
byte short (84 code points on this Mac; ApplicationFontsWorker.cpp; 66e4c6ed0d). RD-0054 last range ended at nMaxSymbol-1
(c7561e4bb0). RD-0055 a chart's macro was dropped through ODS (ConvertDrawing.cpp / xlsx_drawing.cpp; 46e22fe61e). RD-0056
draw:frame wrote office:event-listeners before the frame content, invalid ODF 1.2 (draw_frame.cpp; 63425b8f66).
#2225 Groq is now an AI agent provider (OpenAI-compatible at api.groq.com/openai/v1; desktop-sdk 46ddc076); IBM watsonx not
added - it needs an IAM-token client, not a provider entry. Not checked: a live Groq request / CORS, GUI. macOS only compiled.

### #2275 / #1868 follow-ups and RD-0060 - DONE 2026-11-13
#2275 spreadsheet &F printed "FILE=null" in a PDF saved from the desktop: HeaderFooter.js fell back to api.documentTitle,
still the "null" placeholder in x2t (no DocumentTitle for an Editor.bin source); now uses formulaProps.docTitle from the
save params and never prints the placeholder (sdkjs e773c13a4c). #1868 caret half: a saved workbook reopened at the
open-time cursor (moving the caret records no change); the editor now sends "activeCells" in the save params and x2t
applies it per sheet, frozen panes included (sdkjs 68457630dd, core d353ff8898; SaveParams gained a member - rebuild
libBinDocument and PPTXFormatLib before x2t). RD-0060 compound files over ~7 MB had sector 0 instead of FREESECT in
unused DIFAT slots, against MS-CFB 2.5 (cfcpp compoundfile.cpp AllocateDIFATSectorChain; core 88deda72e2) - no reader
seen rejecting the old files. Tests issue-2275-header-filename-null-test.js, issue-1868-active-cell-save-test.js,
issue-1868-active-cell-x2t, rd-0060-cfb-difat-freesect. Root-caused list reviewed by agent ez: most remaining entries are
fixed elsewhere, features, or need Word/GUI to settle.

### #343 / #346 - slide text layout against PowerPoint's own thumbnails - DONE 2026-11-13
References: docProps/thumbnail.jpeg saved by PowerPoint 14.0 in each reporter deck, compared with x2t PDF via pdftotext -bbox.
#343 a default tab that would end past the right edge was clamped to the edge (Word's bug-32345 rule) - PowerPoint wraps it;
and spaces were skipped when sizing a line - PowerPoint counts a 28pt trailing space. Both now DrawingML-only (sdkjs
11054e3e63). #346 kern was dropped everywhere: read and skipped in Serialize.js, no CTextPr field, HarfBuzz kern bit never set,
never written - so every save through sdkjs stripped all kern attributes (data loss) and slide text set unkerned wrapped where
PowerPoint fits it. Now kept, written, used by the shaper when size >= kern, and part of the text-properties cache key (sdkjs
37ea3d91f9). Behaviour change: decks/charts whose styles carry kern (PowerPoint's default) are now kerned; Word body text
unchanged. Mixed-version co-editing would misread a change carrying Kern. Tests issue-0343-pptx-tab-wrap-space-height,
issue-0346-pptx-kerning.

### #1675 / #1858 / #2045 - resume position (option); extract pages to PDF; duplicate document - DONE 2026-11-13
#1675 Advanced setting "Offer to continue where you left off when a document is reopened" (document editor, desktop local
files, off by default): caret kept as a path of element indexes + characters-before-caret (stable across save/reopen,
tables and content controls), per hashed path in localStorage, max 100; a non-blocking tip jumps there (sdkjs c1be872fcf,
web-apps 9754c42810). Turning the option off deletes the saved places. #1858 PDF editor thumbnail menu "Save pages as new
PDF..." - CPDFDoc.GetPagesBinary bytes through the existing blob download to the native Save dialog (sdkjs e48439ad4f,
web-apps 09b9b8911e); macOS already handles it (AppDelegate.mm onCEFStartSave) - the earlier note saying otherwise was
wrong. OnBeforeDownload still offers the dialog for downloads from any frame (portal downloads, Save as picture use it);
narrowing it is a separate decision. #2045 File > Duplicate for local desktop files (docx/xlsx/pptx, not PDF): writes the
current state as Editor.bin and opens it via the existing OpenBinaryAsNewFile route, which since RD-0031 drops copied
changes (sdkjs fd08e90c1c, web-apps 37c2ce2b87). Tests issue-1675-resume-position-test.js, issue-1858-extract-pages-test.js,
issue-2045-duplicate-tab-test.js. GUI checks pending.

### #2550 / #2219 / #2484 / #2437 and RD-0062 - DONE 2026-11-13
#2550 media Play/Pause/Stop animations: CTiming.createMediaCallEffect writes PowerPoint's form (presetClass="mediacall",
p:cmd type="call" playFrom(0.0) / togglePause / stop); Media group in the Animation gallery; in a slide show the timeline
command resets the repeat filter (a second Pause used to be dropped) and goes only to that media's player (sdkjs 8a4cb045f8,
web-apps c3c656be29). Play is written with 1 ms duration (media length unknown). #2219 user-editable prompt for the AI
grammar check (Grammar & Spelling > Settings; default prompt unchanged byte for byte; plugins 3a3a6961). #2484 a:clrChange is
now drawn in the editor canvas (exact colour match, cached per image; sdkjs 1fccd3ade2) - PDF export and print still opaque
(core renderer), no UI to set it. #2437 printed cell borders had a 0.375pt gap at every vertical border: CPdfPrinter drew
odd-width lines on the coordinate, the layout assumes the screen's half-pixel shift (sdkjs 5073b97d08); underline/strikeout
and sparkline axes in print move the same half pixel. RD-0062 RTF font names lost their spaces on open ("Times New Roman" ->
"TimesNewRoman"): RtfFontTableReader::ExecuteText trimmed every \uN piece (DestinationCommand.cpp:3466; core 16b11bbdc0).
Tests issue-2550-media-animations, issue-2219-grammar-prompt-test.js, issue-2484-picture-transparent-color,
issue-2437-print-border-gaps-test.js, rd-0062-rtf-font-name-spaces. GUI checks pending.

### RD-0040..RD-0049 (legacy .doc/.ppt fuzz crashes) and #278 / #1064 - DONE 2026-11-13
All 40 corpus files (LibreOffice ww6/ww8, Apache POI HWPF/HSLF clusterfuzz, Fuzzed.doc, 57272) now convert or fail cleanly; 64
normal files convert byte-identically before and after. RD-0040 CHPX FKP with crun>101 left NULL CHPXs (core be84a20320).
RD-0041 header/footer/textbox mapping on an empty PAPX FKP list (53d1c57de2). RD-0042 six sites used the claimed length, not the
bytes read - Word 6 picture memmove, ReadXst, STSHI, ListLevel, OLST, DOP grfitbid (bde4995945). RD-0043 sprm operand copied past
the grpprl, -1 -> 4 GB memcpy (318e3ef22a). RD-0044 two PPT NULL derefs: unread slide record in WriteTiming, background element
assert (8fbcbd7f5b). RD-0045 PlcfHdd shorter than 7 CPs read past the table - a normal file's header appeared ~5 runs in 8
(1fb37219ba). RD-0046 looping UserEditAtom chain (f4b6ef229c). RD-0047 bin tables larger than the stream (b371f1324f). RD-0048
PLEX, LFO count and Clx lengths capped by the stream (66ed47007e). RD-0049 footnote/endnote and annotation-owner loops that never
ended (92fd47c76c). Linux compile not run (Docker down at the time).
#278 custom error bars from sheet ranges: asc_ChartSettings.setCustomErrorBars + "Format error bars" dialog ("More options..."
in both Error Bars menus); fixed on the way: get{Plus,Minus}DataRefs returned an empty CDataRefs, hasIntersection ignored
error-bar refs, setErrValType stored the old errDir for undo (sdkjs cca3a897a9, web-apps 5fdc08a71f). #1064 option "Name the last
action in the Undo button tooltip" (off by default; ~65 English labels over 265 history ids; sdkjs cfc1f19761, web-apps
8cd5171462). Tests rd-0040..rd-0049, issue-0278-*, issue-1064-*. GUI checks pending.

### #2100 - option to stop underlining text while an input method composes it - DONE 2026-11-13
The editor always underlined composition text (sdkjs line-draw-state.js addCompositeInputLine). The IME's own Pango styling
cannot reach JS in CEF 109 (Chromium's GTK IM context turns it into ImeTextSpans only Blink's hidden textarea uses; EditContext is
experimental in 109), so the user's wish is met with a switch: File > Advanced settings > "Underline text while an input method
composes it" (on by default = unchanged; sdkjs f9156829a2, web-apps 5598f8486c). Document editor only. Test
issue-2100-ime-preedit-underline-test.js. GUI check with fcitx5/IBus pending.

### #1801 / #2020 / #1687 / #2044, RD-0070 and RD-0072..RD-0075 - DONE 2026-11-13
#1801 command search in the document, spreadsheet and presentation editors (Advanced setting, off by default; Alt+/ or
Ctrl+Option+/ - Alt+Q is the chat panel): indexes rendered toolbar buttons and menu items by caption/hint, switches tab and
clicks as an Alt key tip does, disabled items greyed (web-apps f069ce1f78). #2020 option: Ctrl+Shift+V pastes values only in
the cell grid (sdkjs 4b3250a966, web-apps 023d023fa9); Paste Special > Values already drops source fonts. #1687 option: new PDF
text boxes reuse the last box's fill, line and text style (sdkjs b264368ba6, web-apps bdc0d3f029). #2044 Merge menu "Merge and
keep content" joins non-empty cells with line breaks, wrap on, one undo (sdkjs aaa4ed4698, web-apps f6e57f4d84).
RD-0070 PPT -> PPTX wrote OLE objects as external links to x2t's temp file when the temp path contained a dot (extension taken
from the whole path; ImageManager.cpp; core 73091a378a) - 23 of 215 corpus .ppt; DOC and XLS export checked clean. RD-0072 SEPX
past the WordDocument stream (9c25d1be7a), RD-0073 string-table entry past its stream (9a120ed6d4), RD-0074 tab-stop sprm shorter
than its count (a733a82513), RD-0075 huge PAPX / table grpprl past the Data stream (07ae492180). ASan over 468 corpus files: 0 real
aborts after the fixes (28 .ppt container-overflow false positives from mixed instrumentation). Tests issue-1801-command-search,
issue-2020-paste-values-shortcut, issue-1687-pdf-textbox-last-style, issue-2044-merge-keep-content, rd-0070, rd-0072..rd-0075.
Linux compile pending for the core units (Docker down). GUI checks pending.

### #289 / #99 / #733 / #420 and RD-0076..RD-0089 - DONE 2026-11-13
#289 slide sorter: View tab "Slide Sorter" lays the thumbnails panel out as a full-area grid (zoom slider = thumbnails per row);
click/Shift/Ctrl select, drag and Ctrl+Up/Down reorder through the panel's own operations (undo works), Delete/Duplicate/copy/paste,
double-click or Enter opens Normal view, hidden slides dimmed (sdkjs f76943b391, web-apps 5359a7c021). Undo no longer switches
the view mode except between master and slide views. Ribbon insert commands still target the (hidden) current slide.
#99 option: right-sidebar Equation panel (document and presentation editors) with structure galleries, a searchable symbol palette
(~500 symbols from the math autocorrect table), Professional/Linear and Unicode/LaTeX (web-apps efb1591bde, 3989d00439).
#733 local mail merge in the desktop app: From file (xlsx/xls/ods via x2t JSON; csv/tsv parsed in the editor as UTF-8), fields,
preview, Merge to a new unsaved tab with one section per record (sdkjs cdbb399929, web-apps 088b831418); no PDF/email output offline.
#420 option: right-click a plain ribbon button to pin it to the in-page quick access toolbar (mirrors disabled/pressed state,
per-editor localStorage, max 10; web-apps 12a95aaeda). Pins are not shown in the native Win/Linux title bar.
RD-0076..RD-0089 legacy readers used claimed lengths after short reads: length-prefixed strings, OLE LinkInfo/PIC/Word 6 data,
comment initials, form-field strings, font panose/names, PICF, string-table extra data, .doc/.xls encryption headers, .ppt
ExObjStg (heap WRITE) and short blips (4 GB allocation), .xls formula cce, monikers/picture keys, short Continue records (heap
WRITE) and FOPT counts (core c51ef4b0aa..69cf1181b0). 86 normal .doc/.ppt/.xls convert byte-identically. Linux compile pending.
Tests issue-0289-slide-sorter, issue-0099-equation-panel, issue-0733-mail-merge, issue-0420-quick-access-pins, rd-0076..rd-0089.

### RD-0090 - xlsx inline-string cells without a sharedStrings part were folded into the row's first cell - DONE 2026-11-13
CRow::compressCell (OOXML/XlsxFormat/Worksheets/SheetData.cpp:4744) treated a cell with only m_oRichText (inline string not yet
moved to m_oValue when there is no sharedStrings part) as empty and folded it into the previous cell as a repeat; same for an
empty cell after a formula-only cell. Effect: mail-merge JSON lost the cells, ODS lost them, and the base64 Editor.bin used by
desktop convert_local_file / "send to" copied the first cell across ("Name,Name,Name"). The normal desktop open (streaming XLSB)
was not affected. x2t's own csv->xlsx writes inline strings. Fixed (core 012cb19776); 48 POI xlsx identical in 5 formats.
Test rd-0090-xlsx-inline-strings-folded (RD_X2T + RD_X2T_LIBS for the end-to-end part).

### RD-0091..RD-0096, RD-0100, RD-0101 - legacy reader leftovers and CSV/bin writer defects - DONE 2026-11-13
RD-0091 xls FilePass too short: ECMADecryptor used an empty salt as the CBC iv (16-byte read from a 1-byte buffer); DecryptCipher
now zero-pads short ivs (CryptTransform.cpp; core 8a74f585e9). RD-0092 encrypted xls with a BoundSheet8 under 4 bytes:
Decrypt(data+4, size-4) wrapped - XOR overflow write / 16 EB allocation (CFRecord.cpp; be82c083d8). RD-0093 fixed-size .doc sprm
operands cut short are zero-padded to their [MS-DOC] size (SinglePropertyModifier.cpp; df565af111). RD-0094 variable-size table
sprms shorter than their structure (borders, cell width/padding/valign, CSSA, TDefTable, TC80, PropRMark) now skipped
(1f2f77f8f6). RD-0095 XLSB CF formula RevName/RevExtern read one unchecked byte (d493a21e09). RD-0096 .doc MemoryStream::ReadBytes
allocated the claimed count and copied fewer - 943 bytes of uninitialised heap ended up in an output PNG, a huge size crashed
(MemoryStream.cpp, BitmapBlip.cpp; 558d235a1c). 237 of 238 normal files identical (the other differs run to run on base too).
RD-0100 a number format built on General was written as "1000eneral" in mail-merge JSON, and Save as CSV dropped the literal text
of formats such as General" kg" (CSVWriter.cpp; 3606acc7de). 79 xlsx: csv identical, json differs only where fixed. RD-0101 cells
of a C++-written Editor.bin came back one row low in bin -> xlsx (BinaryReaderS.cpp ReadCells; f5a02ff33e) - not reached from the
desktop. Linux compile pending. Tests rd-0091..rd-0096, rd-0100, rd-0101.

### RD-0102..RD-0104 - x2t crashes and zeroed numbers in CSV/JSON/XLSB paths - DONE 2026-11-13
RD-0102 CSVWriter indexed cellXfs by a cell's style with no bounds/null check, and sharedStrings with no check at all - xlsx ->
csv/json and Editor.bin -> csv crashed; the desktop's Save As CSV of an UNEDITED workbook reaches it (core bbf0cb118d).
RD-0103 CCell::toBin wrote typed number cells (t="n") as 0 because realCache was filled only for untyped cells - xlsx -> xlsb and
base64 bin -> xlsb lost those numbers; the desktop's normal Save As xlsb (raw bin) was not affected (fa18fad69d). RD-0104 every
.xlsb crashed x2t converting to a base64 Editor.bin or mail-merge JSON (dynamic_cast<CXlsb*> of a plain CXlsx) - desktop
External Links update from an .xlsb and mail merge from an .xlsb (87d8fd27d1). 158 files: no differences except the intended.
Tests rd-0102, rd-0103, rd-0104. Linux compile pending.

### RD-0105..RD-0112 - xlsb text opening as 0, numbers saved as text, nondeterministic output - DONE 2026-11-13
RD-0105 DATA LOSS ON OPEN: inline-string (BrtCellSt) and str (BrtFmlaString) cells of an .xlsb opened as 0 - WriteCell wrote
their text as a double; new CXlsb::PrepareSheetStrings after ReadSheetData (core f15d357a24). Confirmed in the real cell editor.
RD-0109 x2t's xlsb writer saved numbers as text: `#define DBL_MAX 15` in XlsxFormat/Common.cpp leaked into SheetData.cpp's unity
build, so processCellType treated 17+ char numbers over 15 as text (aa16ec2c0d). Decision (user, 2026-11-13): ship both as Excel
reads the file - xlsb files saved by older builds may show such numbers as text (e.g. "-25.780000000000001"), as Excel does.
Uninitialised output fixed: RD-0106 WsProp syncRef (8e61bde8fa->see FIXES), RD-0107 sort-condition value, RD-0108 rgb colours
without alpha got random alpha (now opaque; xlsb->xlsx styles change from 64xxxxxx to FFxxxxxx), RD-0110 PtgList colLast,
RD-0111 phonetic runs. RD-0112 crash on xlsx -> xlsb with a colour sortCondition without dxfId. Corpus deterministic under stack
and heap scribble. Tests rd-0105..rd-0112. Linux compile pending.

### Upstream issues credited through tools/fix-claims.txt (2026-11-13)
#402 #1179 #1509 #2310 #2442 #1333 #1016 #2081 #626 #466 are fixed by commits that do not name them (see "Fixed by our commits
that do not name the issue"). With the user's agreement they are now counted via tools/fix-claims.txt; build-fix-registry.py
checks every listed commit is on the current branch. Duplicates #151 and #1740 are not counted.

## Root-caused, not fixed

### #2101 - IME surrounding text on Linux - Chromium limitation, not ours
CEF 109 uses Chromium's GTK IM context (libcef imports gtk_im_multicontext_new / gtk_im_context_simple_new; GDK_BACKEND=x11).
InputMethodAuraLinux calls SetSurroundingText, but InputMethodContextImplGtk::SetSurroundingText is an empty stub and
retrieve-/delete-surrounding are never connected (TODO) - in 109 and still in 120/130/138. IBus therefore drops
IBUS_CAP_SURROUNDING_TEXT for our editor (a plain GTK3 entry under the same IBus receives it). Only Ozone/Wayland text-input
implements it. sdkjs's hidden textarea also holds only the last <=100 typed chars. Needs a patched CEF.

### #420 - pin any toolbar button to the quick access toolbar - more than a day, product calls open (re-checked 2026-11-13)
The QAT is a fixed set (Header.js onChangeQuickAccess :342; createTitleButton :868; <app>quick-access-<name>). Toolbar buttons
have no context menu and no registry from DOM element back to Common.UI.Button, so pinning needs a toolbar context menu, stable
ids, a cloned title button mirroring icon/disabled/click, per-editor persistence and unpin entries. On Win/Linux the header row
is the native title bar (Desktop.js titlebuttons :125-153, ceditorwindow_p.h), so in-page pins would not show there. Product
calls: which buttons qualify; whether Win/Linux get pins (generic native title-button type). About two days for the in-page part.

### #1876 - cloud documents open with an English UI on Windows - not fixed (needs GUI checks)
The portal picks its language from navigator.language / Accept-Language; desktop-sdk cefapplication.cpp:394-470 sets neither
CefSettings.locale nor accept_language_list, so Windows/macOS default to en-US while Linux follows LANG (the report exactly).
Fix: pass the app's UI language (CLangater) to CEF as --lang / accept_language_list before Init_CEF - changes navigator.language
for local editors and Chromium strings too, so needs Windows/macOS GUI checks.

### #2438 - Linux freeze: deadlock on a full MessagePumpGlib wakeup pipe - in prebuilt CEF
The blocking write end of Chromium's wakeup pipe is drained only by the main thread; the fix (O_NONBLOCK or deduplicated
ScheduleWork) is a CEF/Chromium patch. Our only lever is shorter main-thread stalls during document load.

### #2566 (remaining) - ODP bullets: wrapped lines start left of the bullet text
pptx_text_context Impl::ApplyListProperties (~381-399) writes text:min-label-width as a positive indent and
text:space-before as marL (indent=+0.75cm marL=0). Impress legacy lists need marL=space-before+min-label-width,
indent=-min-label-width. The positive indent is a deliberate upstream condition with special cases; changing it needs a
corpus comparison against LibreOffice renderings.

### #2008 - play a slide video full screen - about half a day
sdkjs Image.js getPlayerData sets "FullScreen" but client_renderer_wrapper.cpp CallMediaPlayerCommand reads "Fullscreen";
Timing.js getMediaAdditionalData reads oPr.fullScrn from the cMediaNode though it is an attribute of <p:video>
(CVideo.fullScrn). No player consumes get_Fullscreen() anyway. Needs sdkjs to send the slide-show rect as FrameRect while
a fullScrn video plays and restore it at the end (the #2005 setMediaFlags end hooks can do that).

### #2550 - media Play/Pause/Stop animations - about a day
Needs a mediacall preset class and a Media gallery in the Animation tab. Not started.

### #1801 - command search ("Tell me") - new UI feature, more than a day
No command search exists in web-apps. Smallest version: index each editor's ribbon buttons and menu items by caption/hint,
switch to the owning tab and trigger the item, keyboard focus handling, strings in every locale - three editors plus a
new header control. Placement and scope (menus or ribbon only) are product calls.

### #289 - slide sorter view - multi-day
The thumbnails panel already multi-selects, drags and reorders. The sorter mode is a stub only: sdkjs slide/apiDefines.js:840
c_oAscPresentationViewMode.sorter = 2, slide/Drawing/HtmlPage.js:5206 empty case, presentationeditor ViewTab.js:466 comment.
A grid sorter needs a new canvas layout, hit-testing, drag-and-drop, zoom and a View-tab button.

### #2047 / #1859 - oCIS, OpenCloud, CryptPad as cloud providers - need server-side desktop integration
A provider is data (loginpage/providers/<id>/config.json), but a server becomes a connected portal only when its page
calls execCommand('portal:login') from a server-side connector (onlyoffice-nextcloud/-owncloud desktop.js). oCIS and
OpenCloud use the document server via WOPI with no desktop hand-off; CryptPad runs its own encrypted editor fork with no
document-server endpoint. An entry would only open the web UI while granting that origin the bridge (#1664) - not added.

### #589 - WebDAV cloud connection - feature, multi-day
Needs a native remote file browser and open/save/lock over DAV; providers are web portals. Workaround: mount the share in
the OS (Finder Connect to Server, GVfs dav, Windows network drive) and open files locally.

### #2042 - MathType plugin on desktop - licensing/product decision
Upstream removed it from onlyoffice.github.io (f2e4b936, 2025-11-11) and documented it as web-only. It loads plugin
scripts remotely (refused by our #1664 hardening) and depends on Wiris's hosted service and telemetry; would need a
licensed offline Wiris build. Built-in equations and onlymath/mathpix remain.

### #1453 / #561 - native Wayland (flatpak "can't run"; blurry under fractional scaling) - needs CEF upgrade
win-linux/src/main.cpp forces QT_QPA_PLATFORM=xcb and GDK_BACKEND=x11; the bundled Qt has no wayland plugin and CEF
109 has no usable Ozone/Wayland mode for our windowed embedding, so no-X sessions cannot work and the blur is XWayland
upscaling an X11 client. #2105 (desktop-apps 2241a8a0e) already turns the segfault into a clear stderr message.
Native Wayland = CEF upgrade (CEF_UPGRADE_PLAN.md, CEF 140+), Qt wayland plugin, portal dialogs (#2168). Workarounds:
GNOME 47+ xwayland-native-scaling, Hyprland force_zero_scaling, KDE "apply scaling themselves".

### #786 - wrong colours on 10-bit (depth 30) X11 displays - not reproduced
No depth-30 X server here. CEF 109 draws into an X11 child window, Qt chrome uses xcb raster; either may assume
8-bit visuals. Next: on depth 30 (or Xvfb -depth 30) compare Qt chrome with CEF content, GPU acceleration on/off,
QT_XCB_FORCE_SOFTWARE_OPENGL.

### #278 - custom error bars from sheet ranges - UI and API missing (about two days)
Error Bars menu (SE ChartTab.js:355) offers only None/Standard error/Percentage/Standard deviation via
asc_ChartSettings.setDisplayErrorBars (sdkjs common/apiCommon.js:1839); CUST bars get a one-point numLit. The model
reads, draws and round-trips CMinusPlus numRef. Needed: setCustomErrorBars(plusRef, minusRef, dir, endCap) building a
cached CNumRef kept up to date like series refs; a "Format error bars" dialog with two range pickers; x2t round-trip test.

### #420 - pin any toolbar button to the quick access toolbar - feature, not done (about two days)
QAT is a fixed set of six buttons in Header.js (onChangeQuickAccess :342); Desktop.js:505-530 passes them by name as
titlebuttons, and Win/Linux editor windows draw native copies (ceditorwindow_p.h m_mapTitleButtons). A pinned
arbitrary button has no native counterpart; needs a context-menu item, per-editor pinned ids, cloned icon/state in
Header.js, and either in-page only or a generic native title-button type. Which buttons qualify is a product call.

### #1858 - extract pages to a new PDF - needs a byte-save path (about a day)
CPDFDoc.GetPagesBinary(indexes) (sdkjs pdf/src/document.js:7491) already produces a PDF of chosen pages. Save Copy
(#982) runs x2t over the whole document and cannot carry a subset. Route: a blob download from the editor, which
desktop-sdk cefview.cpp OnBeforeDownload (:6044) turns into CEF_SAVEFILEDIALOG; Win/Linux handle it
(onDownloadSaveDialog, cascapplicationmanagerwrapper.cpp:821), macOS has no handler. Needs that handler and a
security review that only editor-initiated blob: downloads are offered.

### #2045 - Duplicate tab - not done (about a day + two native builds)
CCefViewEditor::OpenCopyAsRecoverFile (desktop-sdk cefview.cpp:9038) can open a copy of a view's recovery dir, but
the copy only holds changes flushed by autosave, so the editor must flush first (new bridge call); a leftover
EditorForAsLocal.bin must be skipped; macOS has no tab context menu (needs File > Duplicate); PDF tabs use another
recovery layout. Lead (unverified): "copy sheet to new workbook" replaces Editor.bin with the selected sheets but keeps
the source's changes0.json, which is then replayed on top - possible wrong result, candidate RD.

### #2484 - transparent colour for a picture (a:clrChange) - not rendered (more than a day)
a:clrChange round-trips (sdkjs CClrChange Format.js:4634; core PPTX Logic/Effects/ClrChange.cpp) but nothing draws it:
the only blip effect applied is alphaModFix (CBlipFill.getTransparent, Format.js:3819), and core's renderer ignores
it, so the picture background shows in the editors and in PDF export. Needs per-pixel processing in both the sdkjs
canvas path and core metafile/PDF path, plus an eyedropper UI.

### Linux set_drop_files puts file names into JS unescaped (found 2026-11-12, agent ef) - not fixed
desktop-sdk client_renderer_wrapper.cpp ~8455: set_drop_files builds a script with the dropped file names
inside double quotes without escaping. A Linux file name containing `"` (legal there) breaks the script, and a
crafted name could inject script into the start page. Windows is safe (`"` is illegal in names). Candidate RD.

### #2026 - option to install for the current user only - not done (more than a day; Windows)
package/inno/common.iss:73 PrivilegesRequired=admin, DefaultDirName={commonpf}. Per-user would need
PrivilegesRequiredOverridesAllowed with {autopf}, converting 78 HKLM writes (_code.iss 62, common.iss 16) to HKA,
the ~8 GET_REGISTRY_SYSTEM reads and association.cpp:159, and app-local CRT DLLs since vc_redist needs admin.
The no-admin case is covered by the portable ZIP (#2404).

### #646 - wasted UI space on Windows - design call
9.4 can already hide left/right panels, status bar and toolbar (View tab, Ctrl+F1). What remains is merging the
editor header row into the tab/title row (web compactHeader); on desktop that row is the caption/drag area, so it
is a joint web-apps/desktop-apps design decision. No change.

### Packaging findings from the #2548/#1279 checks (2026-11-12) - not fixed
1. `make rpm` cannot build with our branding: common.spec's non-ONLYOFFICE %files lists undefined
   %{_imageviewer_exec}/%{_videoplayer_exec}, makes a world-writable %attr(777) /etc/ration-docs, lists
   /usr/bin/ration-docs twice and ships no help package. We release no rpm - fix before anyone does.
2. The Sep-19 2026.1.0 arm64 deb in a scratch folder has NEEDED /home/administrator/.../libicudata.so.74 (the
   defect build_tools c90bce7 fixed) - CONFIRM the published 2026.1.0 arm64 deb/tarball were built after c90bce7.
3. That arm64 payload bundles no Qt but its Depends lists none of the system libQt5 packages - check the
   2026.2.0 arm64 build (deploy_desktop.py:153 should copy Qt on Linux; the x64 build bundles Qt 5.15.2).
Also triaged: #2510 AppImage (we build none), #835 Debian main (policy/maintainer work), #645 nightlies (CI and
a separate channel), #33 FreeBSD (no CEF/v8), #1279 SRPM (the spec repacks a prebuilt payload; a source spec
means the full network build).


### #959 / #874 / #2339 / #1215 (rest) - not small
#959: the save overlay blocks during x2t's replay of changes (40k paragraphs 47 s without JIT, 5 s with the
allow-jit entitlement the shipped x2t has); editing during save needs a recovery-folder snapshot. #874: no
equation-number support at all in sdkjs. #2339: a Windows DocumentProperties button needs Windows build and
printer. #1215 rest: in-app N-up (#930) is page composition.
NOTE: the test app (.rd-work/make-test-app.sh re-signs ad hoc) and harness x2t lack com.apple.security.cs.allow-jit,
so saves timed there are 6-9x slower than the shipped app.


### #2008 / #2006 / #2005 / #2002 / #2550 / #1968 - slide media playback options - not done
Data survives for full screen, rewind (cTn fill), loop (repeatCount); both players lack an end-of-media
hook and full-screen handling (#2008 also has a FullScreen/Fullscreen key mismatch and reads fullScrn from
the wrong object). #2002 trim (p14:trim) is LOST on save: core Ext::toXmlWriter never writes it and sdkjs
skips the record. #2550 needs a mediacall preset class and a Media gallery (about a day; queued to eg);
#1968 is covered by #2550 (PowerPoint-made triggers already play since #878).


### #1592 - copy to the X PRIMARY selection (Linux) - not simple in CEF 109
The editors' canvas selection never reaches a DOM selection, so Chromium never sets PRIMARY; needs an
sdkjs selection hook, a bridge call and QClipboard::Selection in desktop-apps - three repos, > a day.


### #1064 - list of undo steps - needs labelled history points
History descriptions are internal identifiers (~320 word/slide codes to label and translate) and 243 of 244
spreadsheet history points have none; points are merged. A product decision on wording plus > a day.


### #1694 - save as XLS and DOC - blocked by the converter
docx->doc is a stub (doc.h docx_dir2doc returns error 80); the XLS writer is unfinished (values survive
but the compound file is truncated - "OLE2 MSAT is corrupt") and not wired to the editor save path.
Needs a CFB writer fix plus fidelity work.

### #132 / #1313 / #930 - PDF image quality option; printer defaults; copies per sheet - not small
#132: non-JPEG images are always re-encoded JPEG q85 (PdfWriter LoadImage); a lossless option needs a
setting through web-apps, sdkjs, x2t params and a new CPdfFile setter. #1313: print panels reset Sides;
following system defaults needs native duplex/colour queries on three platforms. #930: N-up/label printing
is a new page-composition feature.


### #83 - CSV delimiter/encoding cannot be chosen on save - design decision
Desktop Save As always sends m_nCsvTxtEncoding 46 / delimiter 4 (fileconverter.h:1101-1109); the web-apps
CSV options dialog is web-only, and the open-time options are not kept, so Ctrl+S on a semicolon or
non-UTF-8 CSV likely rewrites it as comma/UTF-8 (read, not run). Partial step: enable the commented-out
SCSV format (cefview.cpp:1855) as #2521 did for TSV; a real choice needs a native<->JS step.


### #1233 - paste of web content with images freezes the editor - root-caused, not fixed
AscCommon.sendImgUrls (sdkjs common/Local/common.js:323) calls LocalFileGetImageUrl per image
synchronously; natively DownloadSync sleep-polls on the renderer main thread, so the editor freezes for
the sum of all downloads (60 s/image on macOS, no transfer limit with curl on Linux). Fix: route
through the async DownloadFiles path (callers already accept a callback). Cross-repo, needs a GUI.


### #992 - Word picture bullets shown as a Symbol lambda - feature gap
lvlPicBulletId bullets: x2t drops the bullet images and sdkjs has no picture-bullet support
(NumberingLvl.js IsImageBullet "TODO"); the Symbol fallback (U+F06C = lambda) is what Word shows
without the picture. Needs numPicBullet in core binary read/write and sdkjs model/drawing.

### #891 - weights of a variable font missing from the font list - feature gap
Static multi-weight families list separately (FT_PARAM_TAG_IGNORE_PREFERRED_FAMILY). Variable fonts
(Bahnschrift, Skia, STIX Two Text) list only the default instance: we enumerate face indices, never
fvar named instances. Needs instance enumeration, instance index through AllFonts.js, HarfBuzz
variation coords in the WASM shaper and instanced outlines for PDF embedding. Side finding: Apple
italic faces without the italic flag (Avenir Next Condensed Heavy Italic) lose their italic slot.

### #643 - fonts activated by FontBase not found (Windows) - not testable here
We scan HKLM Fonts, CSIDL_FONTS, %LOCALAPPDATA% fonts and CloudFonts, not HKCU\...\Fonts or
session fonts added with AddFontResource. Needs GDI/DirectWrite enumeration mapped to files, Windows-only.

### #812 - Thai line breaking - feature gap (rendering itself fine in 9.4)
Tone marks, stacking and the tail-less ฐ render correctly in docx and xlsx. A Thai run has no break
opportunities (Text.js private_IsSpaceAfter), so long Thai text breaks mid-word at the margin; Word
segments by dictionary. Needs a Thai word-break dictionary in sdkjs line breaking.


### #1032 - long floating table squeezes the following heading - reproduced, not fixed
TS2.docx: Word offsets the floating table (tblpPr vertAnchor=text tblpY=1, no tblpX/horzAnchor) ~722tw
right of the margin, we put it at the margin, so the right gap passes the 6.35mm minimum in
CFlowBase.getArrayWrapIntervals and the heading wraps beside it. Source of Word's 722tw not found.

### #801 - text above instead of below a through-wrapped picture - reproduced, not fixed
Picture relativeFrom=line +312420 EMU, wrapThrough, distT=152400; sdkjs ignores distT for
through/tight wrapping (ParaDrawing.getArrayWrapIntervals uses Y0Sp/Y1Sp). A ~1pt question that needs
a Word rendering to settle.

### #615 - blue page background and a wrapped "4.1" - reproduced, not fixed
(1) w:background without settings displayBackgroundShape: Word shows white, we paint it; needs a flag
through the binary format (core BinaryWriterD ~10015 always writes it, BinaryReaderD:8929 always
adds displayBackgroundShape on save) and an sdkjs render check. (2) "4.1" after 40 spaces in a
justified cell wraps in our layout; Word's rule not derivable without a Word rendering.


### #1343 - "Invalid character in spreadsheet" - nothing is invalid, and nothing is lost

Root-caused precisely and **deliberately not fixed**, because the honest fix is a
feature we do not have. Investigated as a suspected data-loss defect in the same
family as #139; it is not one.

**The data is intact.** Verified end to end on the built converter - `❌` (U+274C)
survives `csv -> xlsx -> bin -> xlsx -> csv` byte-identically, and appears in
`sharedStrings.xml` as itself. Re-run independently here after the agent reported
it, using `harness/bin/x2t.sh` both directions: the output is byte-for-byte the
input.

Also ruled out, each by running rather than by reading: the `_xHHHH_` escaping trap
(`_x0041_`, `_x000D_` and `a_x005F_x0041_ b` as literal cell text all round-trip
identically, with correct double-escaping in both directions), and any #139-class
escaping defect in a spreadsheet writer - a hand-built xlsx carrying `&`, `<`, `"`
and `'` in sheet name, defined name, shared string, formula text, hyperlink display
and tooltip, comment author and comment body round-trips with every part
well-formed.

**What actually happens** is that the character is drawn as `.notdef`, because no
font the editor's own engine will accept contains U+274C. Two lines do that, both
in `core/DesktopEditor/fontengine/ApplicationFonts.cpp` - `CFontList::Add`, the
only door into the font list:

    if ( !( pFace->face_flags & FT_FACE_FLAG_SCALABLE ) )   // :1144
    {
        FT_Done_Face( pFace );
        return;
    }

and, on macOS, `:1274` skipping any family whose name begins with `.`. Exactly two
fonts on this machine contain U+274C, and one line excludes each:

    Apple Color Emoji.ttc   scalable=0, upem=0   -> dropped by the SCALABLE test
    LastResort.otf          family=.LastResort   -> dropped by the leading-dot test

So `ApplicationFontsWorker` emits a range table with no entry covering U+274C,
`getFontBySymbol` returns `""`, and `file.js` falls back to `m_nDefaultChar` -
glyph 0, which in DejaVu Sans is the box-with-a-question-mark in the screenshot.

**The reporter's own clue confirms it**: they noted the cell *editor* renders the
character correctly. That editor is a real DOM `<textarea>`
(`CellEditor.template:10`), so Chromium renders it with the system font stack and
finds Noto Color Emoji. The grid beside it is a canvas driven by our FreeType
engine with a much smaller stack. One string, two font stacks, two results.

**Why not fixed.** Admitting those faces means rendering bitmap and colour fonts,
and that support is absent everywhere: `FT_LOAD_COLOR` is defined at
`sdkjs/common/libfont/file.js:62` and referenced nowhere, there is no `COLR`,
`CPAL`, `BGRA` or `FT_HAS_COLOR` anywhere in `core/DesktopEditor/fontengine/` or
`sdkjs/common/libfont/`, and `fonts.wasm` contains no such strings. These faces
also report `units_per_EM == 0`, so admitting them without a strike-based metrics
path makes matters worse rather than better. That is colour-emoji support - a
feature, not a stability fix - and no change was made rather than shipping a
plausible-looking one to shared font code that could not be demonstrated.


### #2135 - two editable views of one local document

Root-caused; **deliberately not fixed**, and parked as approval item 10. The
title reads like a feature request and the one-line version of it is a data-loss
bug, so the mechanism is worth stating here rather than only in the approval list.

Two mechanisms, both deliberate. `asctabwidget.cpp:718` finds an existing view by
url and selects that tab rather than making a second - **no lock is consulted on
that path at all**. A second *process* is not refused either; `cefview.cpp:6009`
queries the lock and demotes the document to read-only and detached from its path.

The reason not to simply pass `forcenew`: the desktop save is a whole-file
overwrite through the held descriptor (`SeekFile(0)`, write, `Truncate`), with no
change-log reconciliation for local files, so the second save discards the first.
And the locker would not catch it, which was measured on this host rather than
reasoned about:

    C - THIS PROCESS holds it, via the real CFileLockerFCNTL::Lock()
        the SAME process now asks IsLocked: ltNone (free - the editor will write)
        and a second F_WRLCK from this process: granted

A POSIX byte-range lock never conflicts with its own owner, and `CLockFileTemp`
compares user + host + app-data-dir, so a second view of the same user matches its
own `.~lock` marker. Two views in one process both read "free, go ahead and write".

A safe subset exists - a second **read-only** view, which is what the reporter's
stated motivation (two places in one long document) actually needs. Two *editable*
views need either one editor model with two viewports, which is an `sdkjs` change
since a `CCefView` owns a whole editor instance, or local co-authoring with OT.

Verified incidentally by the same harness: **a stale `.~lock` from your own crash
does not wedge the document** - your own marker is recognised and ignored. So the
"stale lock" reading of this report is not what is happening.


### #2275 - the file name in a header or footer is blank in an exported PDF

Root-caused and reproduced; **an attempted fix was reverted**, and the reason is
worth more than the attempt.

**Reproduced** with a two-line xlsx whose header is `&LFILE=&F&CSHEET=&A&RPAGE=&P`,
converted by our own x2t to PDF:

    FILE=         SHEET=MySheet   PAGE=1
    body text
    footerFILE=

`&A` and `&P` resolve; `&F` alone is empty. The reason is visible in
`sdkjs/cell/model/HeaderFooter.js`: the sheet name comes from `ws.model.sName` and
the page number is computed, but

    case asc.c_oAscHeaderFooterField.fileName:
        res = api.DocInfo ? api.DocInfo.Title : "";

and `DocInfo` is set by `asc_setDocInfo` when the *editor* opens a document. The
converter never calls it, so in the process that actually renders the PDF there is
nothing to resolve. That is exactly why the reporter's "Microsoft Print to PDF"
works - a different path, with an editor behind it - and ONLYOFFICE's own export
does not.

**Why the obvious fix is wrong.** x2t already passes a `<JsonParams>` blob to sdkjs,
so adding `"documentTitle"` to it looks like the natural channel. It is not.
`spreadsheet_api.asc_nativePrint` begins `if (_options) { ... }`, and for a plain
export `_options` is **null**, so that whole block is skipped. Making JsonParams
non-empty switches it on, and it unconditionally does

    _adjustPrint.asc_setIgnorePrintArea(true);
    _adjustPrint.asc_setPrintType(Asc.c_oAscPrintType.EntireWorkbook);

before applying a fresh page layout. The header and footer then vanished *entirely* -
the PDF went from 14,914 to 13,032 bytes - which is worse than the bug. Reverted.

**What a real fix needs:** a dedicated element in the doctrenderer Settings XML
(`getDoctXml`, `core/X2tConverter/src/cextracttools.cpp`) carried through to sdkjs
separately from the print options, so the title arrives without turning on the
layout path. Then `&F` can resolve from it.

Note also that for the desktop's own Save-as-PDF the source file is `Editor.bin`, so
a title inferred from the source name is useless there - the application has to pass
`m_sTitle`. Whether it does is unchecked.

**A trap worth knowing, which cost time here:** `strings` cannot see a wide literal.
`L"documentTitle"` is `wchar_t`, four bytes per character on macOS, so
`strings x2t | grep documentTitle` finds nothing even when the code is present, and
it looks exactly like the stale-relink problem described under #2430. Check the raw
bytes instead: `python3 -c "print(open(p,'rb').read().count('x'.encode('utf-32-le')))"`.


### #2288 - ROW(INDIRECT("2:N")) reports a circular reference that is not one

Root-caused precisely; **deliberately not fixed here**, for a reason worth stating:
getting this wrong means *missing* a real cycle, and a missed cycle is an infinite
recursion, which is a far worse failure than the false positive being removed. It
needs a test that runs the formula engine end to end, which the harnesses in
`../fork-fix-tests/` are not set up to do.

**Mechanism.** `INDIRECT` and `OFFSET` produce references the static dependency
graph cannot see, so both hand their result to
`g_cCalcRecursion.saveFunctionResult` for a dynamic check
(`cell/model/FormulaObjects/lookupandreferenceFunctions.js:1790` and `:1963`).
`Cell.recheckCellForCycle` (`cell/model/Workbook.js:17122`) then walks those saved
results and flags a cycle on one test:

    if (range.bbox.contains(t.nCol, t.nRow) && range.worksheet.getName() === t.ws.getName())

That asks whether the formula's own cell lies inside the range. It does not ask
whether the formula reads any *value* from it - and `ROW`, `ROWS`, `COLUMN` and
`COLUMNS` read only coordinates. So `=ROW(INDIRECT("2:2"))` in any cell in rows
2..N is called circular, while Excel does not, and the reporter's own observations
fit: the same formula outside the row range works, and `SEQUENCE` works because it
produces no reference at all.

**A fix that would be safe in shape:** have the positional functions discard the
saved result they consumed, matched by object identity, so only the reference that
`ROW` actually took is exempted. `SUM(INDIRECT("A1:A10"))` in A5 still saves its
result and is still caught. The failure mode of an identity mismatch is that
nothing is discarded - the current behaviour - rather than a missed cycle, which is
what makes this shape worth preferring over widening the test.

Note while you are in there: the store is one slot per function name
(`oIndirectFuncResult`, `oOffsetFuncResult`, `oCellContentFuncRes` in
`parserFormula.js:12126`), so a formula with two `INDIRECT` calls already keeps only
the last. The mechanism is approximate before any change of ours.

**Also unexplained, and reported:** the reporter says the error survives deleting
and retyping the formula, survives save and reopen, and is reproduced by copying
the sheet - but a new sheet with identical content is fine. That is not explained
by the above, which is recomputed per calculation. Something is being persisted.
`parsedFormula.ca` is set to true by this same code path and is serialized; that is
the first thing to check.


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

### A batch of twenty, 2026-09-13

Swept the 193 open issues not yet in this file and took the twenty most stability- and
correctness-shaped. Three produced fixes, one turned out already fixed, and the rest are
recorded so nobody re-derives them.

**Fixed: #1748.** The most valuable of the batch, and it did not look it - a graduate
student's RISC-V port, easy to dismiss as not our platform. The backtrace says otherwise:
frames #8-#11 are `std::locale` and `std::ios_base` **in the executable**, called from
frame #12 in the *system* `libstdc++.so.6` during `call_init`. `-static-libstdc++` put a
whole copy of the C++ runtime in the binary and nothing hid it, so the linker published it
into the global scope and the system library bound to ours. Not RISC-V specific: that
platform's libstdc++ differs enough to expose what x86_64 survives by luck. Second member
of the #2136 family - a bundled library exported anyway.

**Fixed: #2444.** No URL was ever rejected. `getErrorCode()` mapped the client's
"Connection error." to 404 and `checkProvider()` maps 404 to `invalidUrl()`, so every DNS
failure, refused connection and sandbox block arrived as "your address is wrong".

**Already fixed in our baseline: #2068** (INDIRECT across sheets reported as circular). The
current cycle check compares the worksheet as well as the coordinates - added 2025-09-03
in sdkjs `229e86604b`, after the reporter's 9.0.0. Proved rather than assumed:
`../fork-fix-tests/issue-2068-indirect-crosssheet/` runs the real
`Cell.prototype.recheckCellForCycle` for the reporter's arrangement, and deleting the
worksheet comparison makes it fail. Kept as a regression test.

**#2367 - narrowed, and it affects us.** Labelled `fixed-release` upstream, but the
maintainer says the fix "will be available in one of the upcoming releases" and the report
covers 9.3.1 *and 9.4.0*, so our tree has it. The file is public
(`brunwater.com/s/BrunWater125.xlsx`) and **x2t converts it cleanly here**, xlsx to bin,
exit 0 - so the failure is not conversion but `sdkjs` reading the bin afterwards. Six
sheets, defined names, data validation, conditional formatting, drawings; nothing exotic.
Next step is the `harness/` CDP route to capture the actual error.

**Not actionable as filed:** #2409 (maintainer could not reproduce, no file, still
`waiting feedback`), #2189 and #2145 (no error, log or dump).

**Environment rather than defect, on current reading:** #2405 (Times New Roman is a
Microsoft font, absent from a Flatpak Linux host; the real complaint is that the
substitution is silent), #2396 (GStreamer codecs absent from the sandbox), #1832 (video
crash under Flatpak, with GBM driver errors logged before anything of ours runs), #2411
(fcitx5 positioning under Wayland at 200% scale).

**Font and glyph cluster: #2433 and #2199 are fixed; #2437, #2020 and #2327 remain.**

#2433 was the best-written report on the tracker and its analysis held up line for line.
`CheckSymbols` walked every charmap and fed raw codes to a checker whose codes are treated
as Unicode, so Heiti's Big5 subtable made it claim U+A140-U+F9FE - overlapping Hangul. The
font's subtable list was verified against the real file on this machine: `STHeiti
Light.ttc` font 0 is exactly (0,4) Unicode format 12, (1,0) Mac Roman format 6, (1,2) Mac
Traditional Chinese format 2. Coverage is now recorded from Unicode subtables only, with
MS Symbol kept and no-Unicode faces left alone.

**Both halves are now fixed.** `CFontFile::SetCMapForCharCode` was asking a non-Unicode
subtable for a Unicode code point, which is what turned Big5 0xD14C into 埕 once such a
font had been picked. `FT_ENCODING_NONE` and `APPLE_ROMAN` are now consulted only for a
face with no Unicode subtable, where the legacy subtable is the only mapping there is.
`MS_SYMBOL` is deliberately not gated: it is a Unicode convention (the U+F000 private use
area), not a legacy encoding.

**A latent bug found next to it, since fixed.** In that same branch `nCharIndex` was
assigned from inside the `if` condition, so a later charmap's *miss* overwrote an earlier
charmap's *hit* and the lookup reported that a face could not draw a character it can. It
surfaced as a test assertion that passed on the baseline for the wrong reason - Mac Roman
found the glyph and the Big5 subtable then cleared it - which is worth more attention than
an assertion that fails. Fixed in `core` ee2677f68d with a case in the same test.

#2199 turned out not to be a font list at all: nothing set a `lang` attribute anywhere, so
the renderer had no way to tell zh-CN from zh-TW and fell back to fontconfig's ranking.
Declared now, with the region preserved even though the translation file is chosen by
language alone.

**#2020 (paste values changes formatting)** was looked at: the `pasteOnlyValues` branch
does `_clean()` then `val = true`, which is right, so the leak is further down the paste
path and needs the editor to find. **#2437** (borders printed wrong) is an image-only
report in the print path. **#2327** unexamined.

**Formula engine: #2426 is fixed.** A formula joins the volatile-array list - the pass that
writes a spill - in the `_foreachChanged` block of `Workbook.js`, and the test that put it
there ran *after* `oCell._checkDirty()` while keying on `aca && ca`. Recalculation is what
clears those: `parserFormula.calculate()` calls `setAca(false)/setCa(false)` as soon as a
dynamic array fits again. So a FILTER going from collapsed back to spilled had already lost
the flag, was never scheduled, and its spill was never rewritten - only its own cell, which
is calculated normally, showed the new value. That F9 does not help fits the same reason,
and that editing the formula does fits too, since that path rebuilds the spill from
scratch. Now sampled before the recalculation and accepted in either state, so collapsing
and re-expanding both schedule the pass.

**Feature requests, not defects:** #1876, #1687.

### #2421, #2189, #2347 - swept, and where each one stands

**#2421 (clipboard freeze, then the wrong image pasted).** An unusually good report: a
104 MB GIF copied, then a 1.9 MB JPG copied, and the subsequent pastes produce a mixture
of both. The reporter's own diagnosis - an asynchronous clipboard write for the large
image racing a later copy - is the right shape, but **the race is not in our code.** On
desktop, `Button_Copy` hands straight to `window["AscDesktopEditor"]["Copy"]()`
(`sdkjs/common/clipboard_base.js:1378`), and that binding is
`CefV8Context::GetCurrentContext()->GetFrame()->Copy()`
(`client_renderer_wrapper.cpp:1207`). There is nothing of ours between the keystroke and
Chromium's clipboard, and we ship CEF as a prebuilt binary - the same wall as #2438.

What *is* ours is the payload: sdkjs still builds the clipboard HTML on the copy event,
and a 104 MB image base64'd into a DOM node is a plausible second source of the freeze.
That part is worth measuring before anything else - `harness/` can time a copy of a large
image in the real editor. Do not touch `clipboard_base.js` on suspicion; the async
`navigator.clipboard` paths there are the *browser* route and are not what the desktop
build takes.

**#2189 (closes itself on startup, Windows).** Not actionable as filed - no error, no log,
no dump, and the reporter says outright they have nothing more to give. Same position as
#2145. It needs a Windows Error Reporting dump or a run with logging enabled before there
is anything to read.

**#2347 (unresponsive after a half-screen snap).** Left for now, and worth pairing with
#2438 rather than reading on its own: that report established that a burst of
`X11Window::OnConfigureEvent` -> `DispatchResize` -> `PostTask` is what finally blocks the
main thread on a full wakeup pipe, and snapping is exactly a resize storm. We fixed the
one resize defect that was ours (#2018, a synthetic event per intermediate size), so
anyone picking this up should first check whether #2018's fix already changed it.

### #2168 - a note on the flag that reads backwards

`--xdg-desktop-portal=default` sounds like "use the default dialog". It does not: it
selects the portal, exactly like the plain `--xdg-desktop-portal`, and the two differ only
in whether the preference is stored - `=default` clears it, the plain form sets it. This
predates the Wayland fix and was left alone deliberately; the test asserts the behaviour
as it is. If it is ever changed, `--xdg-desktop-portal=default` meaning "GTK, and forget
my preference" is the reading that matches the name.

### Batch, 2026-09-14 (fourth): #2435 fixed, #1848 is not a defect

**#2435 - fixed.** The plugin already had RTL support, which is why this looked puzzling
at first: an `isRTL` flag drives `dir` on the dropdowns, inputs, dialogs and layout. But
that flag follows the *interface* language, and a message's direction belongs to the
message. An English interface is shown Arabic answers and the reverse, often in one
conversation, so no interface-wide direction can be right for the transcript.
`dir="auto"` on the assistant's markdown container and the user's bubble lets the browser
judge each paragraph and list item from its first strong character. The chrome stays on
`isRTL` on purpose - which way menus open should not flip because someone pasted a line of
Arabic.

**#1848 - not a defect in this tree.** A student compiled from source on Windows and the
"Edit Text" button did not appear; they are asking whether their build is wrong. It is
labelled `question` upstream and there is nothing to reproduce - no version, no log, and
the answer depends on their build configuration rather than on our source. Nothing to do
here unless it turns up again from a packaged build.

### Batch, 2026-09-14 (third): #2395 and #2397 - two Linux integration defects

Both were reported as separate problems and turned out to be the same omission seen twice:
the application was not telling the desktop who it is.

**#2395 - the launcher cannot find it.** The `[Desktop Entry]` block carried `Name=` with
no localised variants. The specification says a launcher should fall back to the
unlocalised key, and many do, but several index only `Name[<locale>]` once a locale is set.
The giveaway is in the file: all four Desktop Actions carry about forty localised Names
each, so "New document" was findable in French while the application it belongs to was not.
Forty-one localised Names added, each the product name unchanged - it is a brand, so what
matters is that the key exists, not that the value differs. The locale list is taken from
the Actions already in the file rather than invented.

**#2397 - no icon in a Wayland panel.** A panel matches a window back to a desktop entry.
Under X11 it can use WM_CLASS, which is what our `StartupWMClass` key is for, and that has
been present all along - which is why the desktop file looked innocent. Under Wayland there
is no WM_CLASS at all; the compositor has only the xdg-shell `app_id`, and Qt takes that
from `QGuiApplication::setDesktopFileName`, which was never called. `DESKTOP_FILE_NAME`
already existed in `defines.h` with the right value and was being used only for a DBus
activation call.

**Still open in the same file, and needing translations rather than a mechanical edit:**
`GenericName` and `Comment` are localised for Russian only, so a French user now finds the
application and then reads "Document Editor" underneath it in English.

**A rebranding hazard worth knowing:** #2397's fix only works while `DESKTOP_FILE_NAME` and
the installed `.desktop` basename agree. They do for a package built from this tree, since
both derive from the same name, but a rebrand that changes one and not the other makes the
icon quietly disappear again with nothing to indicate why.

### Batch, 2026-09-14 (second): #2302 fixed, #2337 and #1491 ruled in scope but not done

**#2302 - fixed, the language half.** `CLangater::init` read `LANG` and nothing else, but
that is the last of the three variables that decide the message language: POSIX order is
`LC_ALL`, `LC_MESSAGES`, `LANG`. A desktop that offers "interface language" separately from
"formats" - KDE and GNOME both do - sets `LC_MESSAGES` and leaves `LANG` alone, so reading
only `LANG` reports a language the user did not choose. All three are read now, and `C` and
`POSIX` are skipped because they are not languages. The reporter's other symptom, AltGr
being dead on a French layout under Wayland, is a keyboard matter and is **not** claimed.

**#2337 (spell-check language changes as you type) - covered by #2543; this note was wrong
(corrected 2026-11-10).** There IS a switch: "Spelling language detection" (start page Settings,
auto/off) is stored as `spell-check-input-mode`; Off makes `CAscKeyboardChecker` send -1, and
sdkjs (`Run.js:1027` `private_CheckLanguageBeforeAdd` via `asc_getKeyboardLanguage`) skips the
retag on -1 for letters and the space alike. The reporter's real complaint - Off only worked after
reopening the document (upstream bug 81377) - is the #2543 defect, fixed in desktop-sdk `2c10dedf61`.
Headless word run on `ration/v10-backports`: de-DE caret, layout 1033 -> "Hallo x" tagged 1033;
layout -1 -> stays 1031. Retagging while on Auto is by design. No new setting needed.

**#1491 (video swallows the keys that should change slides) - the work is identified.**
`QAscVideoView::keyPressEvent` handles Left and Right as video scrubbing and always calls
`event->accept()`, so nothing reaches the presentation. It does emit `onKeyDown`, and
`QCefView_Media` both declares and defines `onMediaKeyDown` to receive it - but **the
connection is commented out** (`qcefview_media.cpp:279`) **and the slot body is an empty
stub** (`:333`). Someone started this and stopped. Finishing it means deciding which keys a
presentation should take back (Left, Right, Escape, Page Up/Down at least) and how to hand
them to CEF, then not accepting those events in the player. That needs a Qt and CEF build to
try, which is why only the unambiguous defect next to it - `Key_P` falling through into
`Key_Escape`, fixed in desktop-sdk 2d8dcfc0 - was taken here.

### Batch, 2026-09-14: #1954 and #2293 fixed

**#1954 (Microsoft Store fonts missing from the list).** They install under
`%LOCALAPPDATA%\Microsoft\Windows\Fonts`, and that directory *was* scanned - but it was
located by concatenating the account name into `C:\Users\<name>\AppData\Local`. A
profile directory is frequently not named after the account: a Microsoft account login
derives it from the email address, a renamed account keeps its old folder, a domain
account can be `<name>.<DOMAIN>`, a redirected profile is not under `C:\Users` at all. The
reporter is on Windows 11 24H2, where a Microsoft account is the normal sign-in. The
system directory had the same shape of bug more simply: `sWinFontDir` is read from
`CSIDL_FONTS` at the top of that function and was then ignored for a hardcoded
`C:\Windows\Fonts`. Both now come from the shell, with the old guess kept as the fallback.

**#2293 (relative file hyperlinks do nothing).** The URL reached `Utils::openUrl` exactly
as stored, and a relative path has no scheme, so `QDesktopServices` and `xdg-open` both
have nothing to act on and neither reports an error - hence a prompt followed by silence.
Resolved now against the document's own directory, which the handler can reach through the
event's sender id and the public `CCefView::GetLocalFilePath()`.

**Neither is compiled where it runs.** #1954 is inside `#if defined(_WIN32)` and no Windows
compiler has seen it; #2293 is Linux/Windows shell code. Both were extracted and run
against stubs, #2293 against real QtCore over a real temporary tree.

### #2327 - does not reproduce on 9.4

Reported against 9.3.1.8 as "OnlyOffice adds some text before the binary content", with a
saved docx rejected by an upload that accepted the same file from other editors.

Round-tripped `document-templates/sample/sample.docx` through the shipped x2t, docx -> bin
-> docx, which is the path the editor takes on open and save. The output:

- begins with `50 4b 03 04`, a normal local file header, with nothing before it
- has `[Content_Types].xml` as its first entry, which is what OPC requires
- passes `unzip -t`
- sets the data-descriptor bit on no local header, so nothing is written in streaming mode
  that a strict reader would refuse

The entry *order* after the first differs from Word's, which is allowed and is not what
was reported. The "text before the binary content" in the screenshot is most likely the
first entry's filename, which in any zip sits immediately after the 30-byte header and
shows up as readable text in a hex viewer.

So either this was fixed between 9.3.1.8 and 9.4, or it is specific to the reporter's
file. **Ask for the file**; without it there is nothing further to test, and the
round trip above is the test anyone would run.

### Crash sweep, 2026-09-13: #2394, #1324, #1832, and a locale hazard ruled out

**#2394 (the app crashes on Open Local File / Save As) is very probably already fixed by
the #2168 change.** The reporter's own workaround is `--native-file-dialog
--xdg-desktop-portal`, which is precisely what #2168 made the default on Wayland: it
stops the in-process GTK chooser being used at all. They are on Debian with GNOME 50,
where Wayland is the session by default, and it reproduces across deb, Flatpak and
AppImage - consistent with a display-server problem rather than a packaging one. #2168
was filed as a freeze and this as a crash; the same dialog can do either.

**Not claimed as closed**, for one reason: the #2168 default keys on the session being
Wayland, so if this reporter is on X11 they are still running the in-process dialog and
still crashing. Worth asking them for `echo $XDG_SESSION_TYPE` before closing it.

**#1324 (abort at startup) and #1832 (crash playing a video)** both carry
`gtk_disable_setlocale() must be called before gtk_init()` in their logs. That warning is
real and is now fixed - `main.cpp` said it too late - but it is a warning, not the abort,
and neither report is claimed as fixed.

**The next thing to try for #1324**, and the more interesting one: `main.cpp` calls
`gtk_init()` *before* CEF starts, while `desktop-sdk`'s `cefapplication.cpp` initialises
GTK *after* CEF on purpose, with the comment "the Chromium sandbox requires that there
only be a single thread during initialization". gtk_init spawns threads. So the early call
contradicts a constraint our own tree documents, and an abort during sandbox startup is
the shape that would produce. `a21bbc19d` shows the call was moved to main.cpp to
consolidate four scattered `gtk_init(NULL, NULL)` calls, not for an ordering reason, so
removing it may well be safe - but it needs a Linux build to try, which is why it was not
done here.

**Ruled out while looking, and worth not re-deriving:** Qt, not GTK, is what sets the
process locale in this application - `SingleApplication` is constructed before either
`gtk_init`, and Qt calls `setlocale(LC_ALL, "")`. Measured: under `LC_ALL=de_DE.UTF-8` a
`QCoreApplication` moves `LC_NUMERIC` from `C` to `de_DE.UTF-8`, after which
`strtod("1.5")` returns 1.0. That is a genuine hazard for any C-library float parsing, and
**nothing in this tree corrects it** - but it has almost no consumer: the Qt shell has no
`atof`/`strtod`/`sscanf("%f")` at all, and `graphics`, `fontengine` and `common` have one
occurrence between them. So it is not the cause of these crashes. Worth remembering if a
number-parsing bug ever appears on a comma-decimal locale.

### #2011, #2145 - swept this round, neither actionable yet

**#2011 (freeze copying all cells).** Not found by reading, and the obvious explanation
is wrong. Every path that builds clipboard content for a whole-sheet selection already
clamps to the used range through `_getRangeMaxRowCol`
(`sdkjs/cell/model/clipboard.js:925`), the HTML and text generators both apply it
(`:1242`, `:1444`), and `_foreachNoEmpty` (`cell/model/Workbook.js:18707`) bounds its own
row loop with `Math.min(worksheet.rowsData.getMaxIndex(), bbox.r2)`. On an empty sheet
all of those collapse to a single row. `git log -S` dates the clamping to 2017-2020,
well before the reporter's 9.0.3, so "the clamp was added later" does not explain it
either.

The reporter's asymmetry is the thing to chase: a whole *column* freezes briefly and a
whole *row* does not. A column is 1,048,576 cells against a row's 16,384, so something
is still O(rows) on a path none of the above covers. **Reproduce it before reading any
further** - `harness/` can drive the real editor over CDP and time
`asc_Copy` on a select-all, which would show where the time goes instead of guessing.

**#2145 (crash in `libascdocumentscore.so` on Fedora 42).** Not actionable as filed: one
unsymbolised frame (`libascdocumentscore.so + 0x2f056f`), no reproduction beyond "just
use the editor". Worth re-testing after a Linux build with the #2136 fix in it - a
Flatpak on Fedora crashing during general use inside that library is the same shape as
the FreeType symbol collision, and may already be fixed. If it still crashes, the report
needs symbols before anyone can act.

### #2430 - a Form Control checkbox is destroyed by opening the file, not by saving it

Reported as "fails to save/convert XLSM containing Form Control Checkboxes", with x2t
dying on Windows at `0xC0000409` (STATUS_STACK_BUFFER_OVERRUN). **Reproduced here on
macOS with the reporter's own attachment**, where it does not crash - it silently
destroys the control instead, which is worse, because the save reports success.

Run against the shipped converter, no editor and no Windows needed:

```sh
# the reporter's file, from the issue
curl -sLO https://github.com/user-attachments/files/31384021/example.xlsm

harness/bin/x2t.sh example.xlsm out.xlsx          # direct convert
harness/bin/x2t.sh example.xlsm bin/Editor.bin 8194   # what opening it does
# then bin -> xlsx with <m_bFromChanges>true</m_bFromChanges>, which is what saving does
```

| part | in the file | direct xlsm -> xlsx | after a round trip through the editor's bin |
|---|---|---|---|
| `xl/drawings/vmlDrawing1.vml` | yes | **kept** | gone |
| `xl/ctrlProps/ctrlProps2.xml` | yes | **kept** | gone |
| `<legacyDrawing>`, `<controls>` in `sheet1.xml` | yes | kept | gone |

**The loss is at open.** `Editor.bin` contains no trace of the control - not the VML,
not the `ClientData`, not even the checkbox's label text (`strings` finds zero matches
for `Checkbox`, `ClientData`, `vmlDrawing`, `ctrlProp` and the label). So the editor
never knows the control existed, and any save writes a file without it. The subsequent
save cannot be at fault; there is nothing left to serialise by then.

**This is a gap in the binary format, not a missing feature in the converter.** The
direct `xlsm -> xlsx` path preserves all three parts byte-for-byte, so `core` can
already carry them across a conversion; it is the editor's bin that has no
representation for them. That asymmetry is what makes this a defect rather than an
unsupported-format decision.

**Not established:** why Windows crashes where macOS silently succeeds. `0xC0000409`
is a stack-cookie or `__fastfail` abort, so plausibly a genuine overrun that macOS
tolerates - but that is a guess, and the change set here does not include one. An
empty change set reproduces neither symptom, so anyone chasing the crash needs a real
`changes0.json` from a live edit; the `harness/` CDP route can produce one.

**Fixing it properly is not small:** it means representing form controls in the bin
format on both sides, `core`'s serializer and `sdkjs`'s reader. Worth weighing against
a narrower alternative - carrying unknown-but-present parts through the round trip the
way Excel and LibreOffice do - which would fix a whole class of silent loss rather
than this one control type.

### #2148 - PDF print drops objects added in the PDF editor - does not reproduce on 9.4
Reproduced the reporter's exact case with their PDF (Account-Inhaberwechsel.pdf): a headless PDF
editor (our sdkjs + pdf wasm) added a text box and a TextArt, the real `_printDesktop` captured the
changes, and a driver repeated the desktop's native steps on our PdfFile (LoadFromFile, EditPdf,
AddToPdfFromBinary, reopen). The objects are in the edited PDF and are drawn by the raster renderer
(macOS print) and by the real `qrenderer.cpp`/`qascprinter.cpp` into a Qt PdfFormat printer (Linux
print to file) - pdftotext finds the text. Upstream marked it fixed (their bug 79346); 9.4 has it.
Not covered: a real CUPS printer.

### #2110 - slide print crops the right side - FIXED 2026-11-10 (macOS)
The earlier note here (rotate branch) was wrong. The reporter's PDF shows a 4000 px raster (a 16:9
slide at 100%) on a 3300 px Letter sheet: nothing was fitted. `CPrintData::CheckPrintRotate` forces
pmFit only for etPresentation, and the editor type is set only by the Windows/Linux app's
TABEDITORTYPE handler; the macOS app never set it, so it stayed etUndefined and pm100 applied.
`cefview.cpp` now sets the type on the view when the renderer reports it. Not checked in a real
macOS print dialog.

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


### #2107 - a plugin installed for all users cannot be uninstalled - FIXED 2026-11-10

**Update.** Plugins installed for all users already had no Remove button (`canRemoved=false` in
`pluginMethod_GetInstalledPlugins`). What was broken: native `RemovePlugin` deleted file by file and
returned true whatever happened (a read-only folder left an empty plugin dir and lost files), and the
store treated an empty answer as a cancel. Both fixed; see the Fixed table. **Hosting gap:** the
store fix lives in `onlyoffice.github.io`, a local clone (excluded from the superproject, origin =
ONLYOFFICE, push disabled) with no lab02 repository - so it and the earlier #2129 commit reach only
builds made on this machine.

Earlier note:

Root-caused and confirmed by reading, not by running: this machine has no
system-plugin install to remove.

The plugin **list** and the plugin **remove** disagree about where plugins live.
`CPluginsManager` carries two directories - `m_strDirectory` (the system one,
next to the binary) and `m_strUserDirectory` - and the call site in
`client_renderer_wrapper.cpp` fills in both:

    oPlugins.m_strDirectory     = m_sSystemPlugins;
    oPlugins.m_strUserDirectory = m_sUserPlugins;

Enumeration honours both. `GetInstalledPlugins` reads `GetDirPlugins(m_strDirectory)`
*and* `GetDirPlugins(m_strUserDirectory)` and pushes system entries into the same
list the user's own plugins go into, so the UI offers a system plugin for removal
exactly like any other. `RemovePlugin` then does this, and only this:

    std::wstring sPluginDir = m_strUserDirectory + L"/" + sAdd;
    if (NSDirectory::Exists(sPluginDir))
    {
        ...          // remove, or move to backup
    }
    return bResult;

There is no second branch. For a system plugin the constructed path does not
exist, the entire body is skipped, and `bResult` stays `false`. `m_strDirectory`
is never consulted by this function - it is used for listing and for reading
`config.json`, never for deletion.

**Why it looks like nothing happened.** The call site returns `bResult` to
JavaScript, so the failure is not lost at the C++ boundary, but it then
unconditionally runs

    "if (window.UpdateInstallPlugins) window.UpdateInstallPlugins();"

whether the removal worked or not. The list is re-read from disk, the system
plugin is still on disk, and so it reappears in place. To the user the click did
nothing and said nothing.

**Not fixed, and the reason is not laziness.** Deleting from the system directory
is a privileged write - on Windows that is `Program Files`, on Linux `/opt`, on
macOS inside the signed and notarised bundle, where removing a file breaks the
signature. There is no elevation path in this process. The honest fixes are to
stop offering system plugins for removal, or to report the refusal instead of
redrawing the list; both are product decisions about what the plugin manager
promises, so they are parked rather than guessed at.

### #2095 - Cannot paste a copied filesystem path (file copied in a file manager)
Correction: the issue is about **paste**, not drag; the old heading here described the wrong bug.
Reproduced in rd-linux-verify: an Xlib clipboard owner offering Nemo's flavours
(gnome-copied-files, text/uri-list, UTF8_STRING=path) and a real Ctrl+V in headed Chromium 108
and 138 under Xvfb. The paste event carries only types ["Files"]: one kind:'file' item with the
bare name, and getData() returns "" for text/plain, text/uri-list and the gnome flavour.
Chromium hides the text when files are on the clipboard, so `clipboard_base.js`
`_private_onpaste` sees only a non-image file item and does nothing. JS cannot get the path
(File has a name only), and desktop-sdk has no native clipboard API. Fixing it needs a native
bridge (NSPasteboard / QClipboard urls) that returns the paths on paste. Not done:
feature-sized and multi-repo. Side effect: the #676 uri-list branch in
`getFileManagerImagePaths` is never reached in Chromium >= 108; image files still paste through
Chromium's image/* File items.
The drag variant (a document dropped on an open editor did nothing) is fixed - see the Fixed table.

### #2123 - recent files list - the reported path difference is real but is not the cause

This is recorded because it is a **claim I checked and could not stand behind**, and
the checking is worth as much as a fix.

The reported root cause was that `recents.xml` resolves to a different place on
Windows than on Linux and macOS. The first half is true. Every reader and writer
agrees on the *expression*:

    recover_path + L"/../recents.xml"          (applicationmanager_p.h x2, client_renderer_wrapper.cpp)

but `recover_path` is assigned twice, in two projects, with different bases:

    applicationmanager.cpp:  recover_path = app_data_path  + L"/data/recover"
    main.cpp:                recover_path = user_data_path + "/recover"

and on Windows only, `main.cpp` mutates the base first - `user_data_path` is
captured **by reference** and the Windows branch does
`Utils::makepath(user_data_path.append("/data"))`, which is an in-place append.
So the file lands under `.../data/` on Windows and one level up elsewhere.

**But that does not break anything**, which is the part the report missed. The
mutation happens before any of the path assignments that use it, all three call
sites compute the name from the same `recover_path`, and `setup_paths` is invoked
exactly once:

    grep -n "setup_paths" desktop-apps/win-linux/src/main.cpp
    144:    auto setup_paths = [&user_data_path](CAscApplicationManager * manager) {
    259:    setup_paths(&AscAppManager::getInstance());

A second call *would* append `/data` again and strand the list at `.../data/data/`,
because the capture is by reference and `QString::append` mutates - that is a real
trap sitting one refactor away, and it is noted below under latent problems. It is
not today's bug. Each platform is self-consistent, so a path difference between
platforms cannot by itself lose a recents list on one of them.

Left open with the root cause **not** established, rather than closed on a
plausible-sounding one.

### #2126 - debug mode stays on after it is turned off

Reported as a sticky value in `settings.xml`. **Not confirmed here** - the search
for the setting in the desktop app sources returned nothing to anchor on, and
rather than reason from the issue text alone it is left unverified. No claim is
made about the cause.

## Already fixed in our 9.4 baseline - no action

### Fixed by our commits that do not name the issue (settled 2026-11-13, agent fi)
#402 and #1179 spell-check language 8192 from custom/neutral keyboard layouts - sdkjs 9b733e650e (LANGID validated).
#1509 and #2310 inserted video wrong size / black square - sdkjs 80b81cf77e (sized from its poster). #1740 copied image pastes
as an icon - duplicate of #1760 (sdkjs 9f3cc5dd87, image/png on the clipboard). #2442 default AutoFit of new text boxes - sdkjs
3bfc7d6c76 + web-apps 94024b16c2. #1333 print selection to PDF prints all sheets - sdkjs 0a8f5abc77 (same as #1641). #1016 first
half is #1333; the system Print path rasterising pages is by design. #2081 silent save failure with a stale .~lock -
desktop-sdk 51e9e27032 (+5eaf9b64). #626 default language for new documents - web-apps 869747e03c (#143), option; #527 for
presentations. #151 run without installing - duplicate of #2404 (desktop-apps f379f0bf71). #466 WebRTC window icon - #2397
(desktop-apps ee934cd076, setDesktopFileName). #1330 - on held branch wip/1330 (Wine test not run).
These are not credited in FIXES.md: no commit claims them.

### #2068 - INDIRECT to another sheet reports a circular reference - already fixed in 9.4 base
sdkjs 229e86604b ("Fix bug #76318"), an ancestor of our branch: recheckCellForCycle compares the worksheet too. Correction:
fork-fix-tests/issue-2068-indirect-crosssheet/ cited by an earlier note does not exist.

### #1436 - files not saved on Synology/NAS - fixed by our #2480 work (reproduced 2026-11-13 on gvfs sftp)
Real upstream 7.5.1 CFileLockerGIO + SaveFile against a `gio mount sftp://` share: SaveFile=SUCCESS but the share keeps the OLD
content - the report exactly. Upstream v9.4.1.22 fails the #2480 sftp test (18 checks); our branch passes. Cause: g_file_append_to
in CFileLockerGIO::Lock (desktop-sdk e2062290, first in v7.5.0.1 - "7.4.1 works, 7.5.0 broken"); fixed by our 565af3d1 and
17e125e1 (save to a sibling temp, move over). smb:// (Samba 4.15 and 4.19) does not reproduce, so the Synology/SMB variant is
unconfirmed. Not credited in FIXES.md: no commit claims #1436.

### #2145 - random SIGSEGV in libascdocumentscore.so - same mechanism as #2136/#2355, covered by our fixes
The thread's symbolised trace: Ctrl+; opens GTK3's emoji chooser -> pango -> cairo-ft -> crash inside libgraphics.so (bundled
FreeType interposition); our crash handler then crashed in OnDestroyWindow (fixed by #2476). First real GNU ld check of
graphics.version: 207 exported FT symbols without it, 0 with it; LD_DEBUG shows cairo/fontconfig binding 67 FT symbols to
libgraphics without the script, all 73 to libfreetype with it. The crash itself not reproduced (no real GTK/Wayland session).

### Upstream "closed as fixed" issues checked 2026-11-13 (agent fa) - already in our code, or nothing to backport
- #1656 data loss .docx (images): upstream bug 69036 fixed by core 812fae8f6c, cbbf650c56 - both ancestors of our branch (attachment never uploaded).
- #1770 SUMIFS: reporter's xlsx recomputed in docbuilder gives 99/88/77/0 as expected (file holds stale cached #VALUE!).
- #573 invisible headings: both reporter files to PDF with our x2t - headings visible and in the text layer (canvas not checked).
- #671 PDF export ignores picture-fill opacity: alphaModFix 50% docx exports at (228,143,143) vs (200,30,30) - respected.
- #1442 GOA Google Drive read-only: upstream fix (desktop-sdk 5f960986, CheckLockFilePath(file,1)) is in our filelocker.cpp.
- #1715 Chinese garbled on macOS: core a865901405, e8ecb2cdfb, baf8321c61 (CoreText enumeration, Heiti/Songti) are in our tree.
- #1619 templates page blank on Enter: the error is from ONLYOFFICE's remote gallery; ours is local (paneltemplates.js), remote off (#2235).
- #586 cloud doc opens in browser: 6.1->6.2 provider-id rename; panelconnect.js:490-511 remaps unknown ids by name and re-saves.
- #2540 filter arrows don't open: real cell editor, real mouse events, frozen panes/scroll/zoom 0.5-2 - menu opens every time;
  upstream could not reproduce either. Untested lead: DocumentHolderExt.js:2065 ignores clicks while an earlier dlgFilter is set.
- #493 Microsoft Store: distribution decision; depends on the Windows build/signing blocker.
- #1675 open at last edited position: feature, in no upstream tag. Smallest version: per-path cursor position in localStorage
  and a "Continue where you left off" tip on open - product call on the prompt.

### #1835 - HuggingChat models in AI - already supported
The AI agent's "OpenAI Compatible" provider (desktop-sdk plugins/ai-agent/src/providers/openaicompatible/index.ts)
takes any base URL, lists every model and chats over /chat/completions. Hugging Face's router
https://router.huggingface.co/v1 is OpenAI-compatible with CORS *; the real provider under vitest against its captured
/v1/models offered 128 of 128 models and completed a streamed chat. Recipe: Add provider > OpenAI Compatible, that URL,
a Hugging Face token. Live chat with a real token not tried.

### #1785 - Zotero citation numbering after inserting between citations - already works (bundled plugin 1.0.9)
Real CitationService + citeproc + ieee.csl on a fake ordered document: insert C between A and B gives [1][3][2], Refresh
renumbers to [1][2][3] with the bibliography in order (citation-service.js ~430-560, fields in document order via
CDocument.GetAllAddinFields). Upstream 1.1.0 has no numbering change.

### #662 - 150% scaling doesn't work on Windows - already fixed in 9.4
On Windows 10+ IsUseSystemScaling() (desktop-sdk applicationmanager_p.h ~233) is on by default and Settings offers
Auto or 100-200%. Running the real choose_scaling (utils.cpp:622): system 1.25/1.50/1.75 -> UI 1.25/1.50/1.75.

### #303 - remove the GConf dependency (Linux) - already fixed in 9.4
No GConf use in desktop-apps, desktop-sdk or build_tools (all "gconf" matches are pkgconfig); deb/rpm
dependencies do not list it.

### #946 - use the system print dialog
Already in 9.4: "Print using the system dialog" in every editor's print panel (web-apps c4ae376f8c); Windows
PrintDlgEx, Linux GTK, macOS print panel. Skipping the in-app panel entirely would be a product call.


### #1166 - spreadsheet weekday/month autofill
Already in 9.4 (upstream 45855): Monday/Tuesday, Mon/Tue, January, Jan all extend in docbuilder.
Default page margins for new documents and the other asks are product calls / features.


### #1223 - default AutoCorrect language
Covered by #143's "Default document language" (drives spellcheck and the AutoCorrect exceptions
language). Gap: presentations' placeholder text keeps an explicit lang="en-US".

### #941 - switch spellcheck language with a shortcut
"Spelling language detection" already follows the keyboard layout (checked in word and slide editors;
Linux xkb fixed by #2503/#373, live toggle by #2543). A last-two-languages shortcut is a product call.

### #1387 - edit language-specific autocorrect behaviour
The concrete French non-breaking-space problem is the #2075 checkbox; a per-language rules editor is a
new subsystem and a product call.


### #949 - Print Selection
Already in 9.4: right-click "Print selection" in documents/PDF, the print range in spreadsheets, thumbnails
in presentations; in an app clone GenerateSelectionPrint held only the selected paragraph. A "Selection"
entry in File > Print is upstream ticket 58285 (design).


### #2231 - file picker non-responsive (GNOME 49 Wayland)
Duplicate of #2168, fixed in our tree (desktop-apps 006ee3415: XDG portal on Wayland);
issue-2168-wayland-file-dialog passes (10/10), 7/10 before. Not run live.

### #2065 - "Light yellow" tooltip for a light green
Upstream 6df663f546/0821289f30 added light greens/blues/oranges to the colour-name map; the reporter's
E2F0D9 now names "Light Green", and a scan of every theme tint/shade finds no cross-family names.


### #2468 - AI agent merged arguments of sequential MCP tool calls
Our desktop-sdk c865aace + 073ae7ba (#2461) already fix it (upstream bug 84216 has no desktop-sdk commit
up to v10.0.0.176); issue-2461-ollama-tool-args-test.js fails on c865aace^ with this exact symptom.

### #2367 - "An error has occurred while opening the file" (BrunWater125.xlsx)
Our sdkjs 08f5a78f76 (#2400) is the same fix as upstream 367e49c9f0/2271967b1a; the reporter's file,
editing "3. Grain Bill Input"!A6, throws at 08f5a78f76^ and works now. Supersedes the earlier note.

### #1505 - GPO MSI installs in Czech only
Upstream 4bb17c4b1/459230f49 add language-neutral 0 to the MSI summary; ours (make_advinst.ps1:188-199)
does, English first. Parsed check only (needs Windows + Advanced Installer + GPO).


### #364 - window cannot be made narrow enough for split screen
5.5.1 had MAIN_WINDOW_MIN_WIDTH 960 x dpi; upstream dropped it in the 2022 window refactor
(31ea6ae4c/acd4fffb2). 9.4 uses WINDOW_MIN_WIDTH 520 x dpi (cwindowbase.cpp:80); macOS minSize 518x440.
Half of 1600x900 and of 1366x768 at 125% fit. Code/history reading only; Windows spot-check advised.


### #373 - Kubuntu spellchecker stays en-US instead of following the keyboard layout
Fixed by our #2503 (desktop-sdk c430d3b1): xkb "English (Australian)" now maps to en_AU (the old
substring match against "Australia" failed and fell back to en_US); issue-2503-xkb-region-adjective
passes on the main tree.


### #772 - copying an image from Eye of GNOME pastes its file path
Reproduced EOG's exact clipboard (image targets + file URI as text) under Xvfb with Chromium 109 (=
our CEF): the paste event offers only the file (image/jpeg); text/plain is empty, and the real
_private_onpaste takes the image branch. The 6.4 bug was the older CEF exposing text/plain.

### #616 / #275 - drag and drop support, image preview
Linux file/image drops exist since 2023 and document drops open tabs (#2095); the path's defects are
fixed under #905. Left as features: a preview pane in the GTK file chooser; inserting more than the
first of several dropped images.


### #1241 - process blocks shutdown (Linux)
Fixed by our #2553 (desktop-apps e467dbac5, bb8dcab02): Qt's fallback session management is off and a
logout is vetoed only with unsaved changes; main.cpp forces xcb, so KDE/Cinnamon take that XSMP path.
issue-2553-logout-cancelled passes. A forced logout after a veto leaves data/recover (continuous
LocalFileSaveChanges). Windows WM_QUERYENDSESSION still goes through Qt's fallback - may veto every
shutdown as #2553 did on Linux; needs a Windows check.

### #743 - typing impossible when the pointer is off the window (Linux)
Upstream 953c25ee2 (7.3.0) hands X focus to the CEF child on XCB_FOCUS_IN
(cwindowplatform.cpp:163-171); in our tree. Code reading only - needs a GUI check on LXQt/Plasma.


### #212 - Read-only doc: Save As doesn't say it can't save
Real x2t returns 80 for a 0444 target, a non-writable folder and a uchg-locked file, leaving the target
untouched; fileconverter.h passes the code up, LocalFile_SaveEnd sends status 2, sdkjs raises
ConvertationSaveError and web-apps shows "This file cannot be saved... The file is read-only". A
read-only file opens unsaved, so Save goes to Save As. GUI dialog itself not exercised.

### #372 - Unnecessary files in home folder
The 5.5.1 launcher copied "New document.*" into xdg-user-dir TEMPLATES ($HOME when unset) on every
start; upstream c3be73c00 made it opt-in (--new-document-templates). Ran our generated launcher in a
container: $HOME stays empty unless the flag is given. Leftovers: the opt-in copy should refuse when
TEMPLATES is $HOME; `command -v ... &> /dev/null` under dash backgrounds the command.

### #1086 - changelog in the update box opened in IE
Reported against WinSparkle's IE view; our tree has no WinSparkle. CUpdateManager/CMessage open the
release-notes link with the system handler on every path, and Ration Docs doesn't build the update
module at all (build_tools make.py "updmodule is off").


### #672 - "Show from beginning" started from the current slide
Fixed upstream in web-apps 25a28289c4 (bug 68209, Mar 2025): Viewport.onPreviewStart calls
StartDemonstrationFromBeginning/FromCurrentSlide by flag. Ran the real Toolbar/Statusbar handlers and
the real slide editor: beginning -> slide 0, current -> current (hidden slides skipped).


### #678 - .docx from Pages - one line per page
The Pages export puts <w:framePr w:w="0" w:h="0" w:hRule="exact"/> in w:pPrDefault; in 6.3 every
paragraph became a zero-height frame. Our 9.4 x2t lays out the reporter's file as 7 normal pages; a
docx round trip keeps the framePr (no loss) and layout ignores it.

### #1269 - Exported PDF shows garbage instead of Cantarell text
Arch's Cantarell-VF.otf (CFF2 variable) exports correctly with our 9.4 x2t: glyphs drawn as outlines,
not embedded, so the text is not selectable/searchable (follow-up: embed CFF2). Static CFF embeds
fine. Harness note: x2t harnesses must pass the fonts-cache dir (font_selection.bin) as m_sFontDir,
like the app, or non-bundled fonts come out garbled in PDF (harness artefact, not a product bug).

### #501 / #317 - bullets smashed or missing (Linux)
Reporters' files with a Linux-like font set (no Symbol/Wingdings): no bullet in a page corner, and
Symbol/Courier/Wingdings bullets draw via OpenSymbol; the Wingdings U+F0F0/U+F0E8 arrows need the
#2318 recode table (sdkjs 0f18391e82), which current ration/v10-backports has.


### #1024 - Opening CSV files selects Tab delimiter by default
Already fixed (8.3, sdkjs d75f1d8310 / web-apps a15234fdef): the desktop CSV dialog detects the
delimiter from the file (getCSVDelimiter counts , \t ; : outside quotes, honours sep=); .tsv picks Tab
by extension; the remembered delimiter applies only to save-as-CSV. Real getCSVDelimiter and
OpenDialog.textCallback run in node: plain/quoted CSV -> Comma, sep=; -> Semicolon, TSV -> Tab.

### #883 - FREQUENCY outputs a horizontal array
Already vertical in 9.4 (cFREQUENCY builds C[k][0]); docbuilder run gives F1:F4 = 4,3,1,2 as Excel.
Separate, unfixed: FREQUENCY sorts the bins and returns counts in sorted order (Excel keeps the bins'
order, to be confirmed against Excel), and counts text/bool bins as 0.

### #240 - Landscape orientation not printable on macOS
macOS print path reworked upstream Feb 2024 (desktop-apps edcbf32e1, 08d85796f, 3b28fed37); later
comments are Linux and are our #1947. Real ASCPrintView/ASCPrinterContext + CheckPrintRotate through an
NSPrintOperation to PDF: A4-landscape pages come out 841.89x595.28 upright; with the destination forced
to "printer", an all-landscape document still prints on landscape sheets. Panel/physical printer and
">1 copies" variant not checked.

### #233 - Bad language for a date in PDF
x2t applies the save params' locale (native.js:307); desktop Save As sends the editor's regional setting
(sdkjs 3426fad8b9). Reporter's file: "28 June 2019" without locale, "28 juin 2019" with 1036. The one
path that dropped it - a plain Save of a new file to PDF - is fixed with #547.

### #359 - Caption numbers not renumbered when inserting between captions
Headless 9.4 word editor, reporter's steps with tables and with images: "1: one / 2: three / 3: two",
kept by the desktop save. CDocument.AddCaption updates every SEQ field of the label (since v6.2).


### #2011 - spreadsheet freezes when copying all cells

Already fixed upstream before our baseline, by `72bf2637d9` ("fix/bug-76100",
2025-07-25), which is an ancestor of our branch. The reporter is on 9.0.3.29,
which predates it.

Worth recording *why*, because the report contains the diagnosis and it is easy
to look in the wrong place. Copy produces several clipboard flavours, and the
data ones - text, HTML, and the binary - have been clamped to the used range
since 2017/2020 via `_getRangeMaxRowCol` (`cell/model/clipboard.js`), which is
why they were never the problem. `Range._foreachNoEmpty` is bounded too, by
`cellsByColRowsCount`/`rowsData.getMaxIndex()` since 2022, so it costs nothing on
an empty sheet. `_getRowTop` is O(1).

What was unbounded was the *image* flavour. Before `72bf2637d9`,
`Clipboard.prototype.drawSelectedArea` went straight to

    let ctx = ws.workbook.printForCopyPaste(ws, activeRange, true);
    base64 = ctx.canvas.toDataURL("image/png");

with no size limit, so selecting everything asked for a canvas covering
1,048,576 rows by 16,384 columns. That is precisely the asymmetry the reporter
describes and which identifies the culprit: a whole **row** is one row tall and
copies fine, a whole **column** is a million rows tall and takes "a few
seconds", and **everything** never comes back. The fix added per-browser canvas
limits, clamped `activeRange` down to what fits, and bailed out entirely past
`maxCanvasArea`.

Our tree has all of it. No action.


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

### #2303 - "AGPL license has impossible terms" - legal question for the product owner and counsel
About upstream LICENSE section 7 additions (logo retention vs trademark); relevant to us as a fork. No code change.

### #1983 - object position capped at 1583.717 pt in Advanced settings - by design (matches Word)
X/Y spinners are limited to +-55.87 cm (web-apps ImageSettingsAdvanced.js:594/619 and the PE/SSE/PDF dialogs), the app-wide
22-inch limit (sdkjs word/Editor/Common.js:673 MAX_MM_VALUE = 558.7, also the maximum page size). 1583.7 pt is Word's own
position limit; the largest page is 55.88 cm, so every on-page position is reachable. Not float32 precision.

### #2470 - the "A4" slide size is 275.2 x 190.5 mm, not 210 x 297 mm

Not a defect. The preset is PowerPoint's "A4 Paper (210x297 mm)" *slide* size,
which PowerPoint itself defines as 10.83 x 7.5 in (27.52 x 19.05 cm), landscape:
a slide sized to fit on A4 paper with margins, not the A4 page. Matching it keeps
decks interchangeable with PowerPoint. A true 210 x 297 mm slide is a custom size.
(2026-10-27)

### #1568 - highlight and font colour not captured by "update style" - FIXED 2026-11-10
Was deliberate upstream (`GetStyleFromFormatting` cleared `TextPr.HighLight`); we chose Word
parity and now carry it into the style. Font colour was always captured. See the Fixed table.

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

### #2486 - cannot undo the footer repeating on every page
By design: a footer repeats for its section. Different first page, different odd/even pages, and
Next-Page section breaks with "Link to previous" off give per-page or per-part footers; all exist in
our 9.4 editor. No code change.

## Feature requests, not defects

### Large features and out-of-scope requests (settled 2026-11-13, agent fi)
#3 git integration (flat OOXML + semantic diff, multi-week). #99 equation toolbox - contextual equation toolbar and
UnicodeMath/LaTeX input exist; a symbol palette panel does not. #314 global macros (app-level store through the #1664 sandbox).
#410 Chrome OS (x64 .deb runs in Crostini; no package). #532 ms-word:/ms-office protocol (+WebDAV). #548 ODBC/REST data.
#564 workspaces/bundles. #693 UI redesign (design call). #733 mail merge offline (canUseMailMerge needs the server;
documenteditor Main.js:1883). #956 offline cloud sync. #1687 PDF text boxes reuse last style (small; not done). #1772 Qt6.
#2044 WPS-style merge keeping all contents. #2391 voice dictation (OS dictation types through the normal input path).
#2531 Google Drive integration. #2020 Ctrl+Shift+V = paste values (new shortcut; original report fixed). #33 FreeBSD (no CEF
build). #645 nightly builds, #835 Debian repo, #2510 AppImage zsync - infrastructure/packaging, not code.

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

### #8 - Portuguese (ABNT2) dead keys, "CEF bug" - likely gone in 9.4, not verified live
The 2016 cause was CEF issue 1813 (no IME/compose on Linux). CEF 109 creates gtk_im_context_simple (compose/dead keys) and a
multicontext for IBus/fcitx; sdkjs text_input2.js passes dead keys through composition. The live check (setxkbmap br abnt2 +
xdotool, with and without IBus) is scripted in .rd-work/wt/fk-tmp/w/run.sh but did not run - the Docker daemon died.

### Settled 2026-11-13 (agent fi) - not reproducible or not testable here
#2191 save/create fails after hours (Flatpak): continuation of #2134/#2086 (fixed in 9.2.0); no logs; our #2081/#2202 make a
failed write never look successful. #2405 Times New Roman missing on Flatpak: environment (no MS fonts); the toolbar shows
the run's stored name, never the substitute. #2406 ligatures in EMS Serenissima: w14:ligatures="all" is honoured; shaping
restarts at property changes and NBSP; needs the font (upstream bug 82447). #2396 arm64 Linux audio no controls: vaapisink
warnings are GStreamer probing; untestable here. #2411 fcitx5 candidate window at 200% on Wayland: CEF/XWayland caret rect.
#2440 no "+" next to Clouds: our start page always renders it (panels.js:79-83). #2555 Quick AI Action freeze: 10.0 feature,
absent in our plugin. #326 Nextcloud U2F: CEF 109 Alloy has no WebAuthn UI; untested. #2372 MSI "Publisher Unknown":
upstream's MSI; we publish no signed Windows installer yet.

### E4 re-attempts 2026-11-13 (agent fd) - still not reproduced
#2474 Ctrl+. crash (Linux): upstream 9.4.0.129 aarch64 tarball under Xvfb+openbox in Docker, no IME / IBus default / IBus with
the emoji hotkey forced to Ctrl+. - app stayed alive, no XCB errors; Ctrl+. applied subscript. Current IBus defaults the emoji
hotkey to Super+., so the IBus theory is weak; needs the reporter's backtrace (x86_64, GNOME/XWayland, Debian 13 untested).
#2473 date filter October empty: German CSV via x2t into the real cell sdk, autofilter month m10 shows all three October rows;
no autofilter commit between v9.4.0.129 and our HEAD; reporter says 10.0 works. #2446 numbered-list font/size not saved: real
word sdk + x2t to DOCX/ODT keeps TNR 14 (whole selection and number-only); RTF lost the font name's spaces (RD-0062, fixed),
not the size - needs the reporter's file. #2230 needs two live tabs + native clipboard; reporter says 10.0 works.

### E5 re-attempts 2026-11-13 (agent fe) - still not reproduced
#2456 Copy Style loses font in tables: real word engine in docbuilder, 72 variants (table style, language, text/cell/caret
source and target) - font, size, bold carried in all; needs the reporter's file. #2080 Linux/XWayland layout: unknown layout
gives -1, nothing sent; mapping covered by #2503 tests; GNOME Wayland XWayland keymap not testable here. #2452 no PowerPoint
thumbnail in the reporter's pptx, so no reference. #1916 Windows native context menu at 200% needs a CefContextMenuHandler
(feature-sized). #2551 Windows lost canvas; #2529 no file; #2512, #2460, #2496 10.0-only; #2453 by design; #1894 bad install.

### #347 / #342 re-checked 2026-11-13 against PowerPoint thumbnails
#347 vertical spacing: with the bundled fonts (Calibri -> Carlito) our render matches the thumbnail within one pixel; the
wrap seen earlier came from a font cache without the bundled fonts (Calibri -> Avenir). #342 "planete" off-centre: agrees
with the thumbnail within one pixel (2.8pt); sub-1% Tahoma advance differences cannot be resolved at 256px.

### #1032 (re-checked 2026-11-13) - floating table ~720tw right of the margin - offset source not established
Reporter's Word 2021 PDF (TS2.pdf): table left edge at 92.8pt against a 56.7pt margin, offset 36.1pt = 722tw (pages 1, 2).
Our x2t puts the table at the margin (diff exactly 36.09pt). tblpPr vertAnchor=text tblpY=1, no tblpX/horzAnchor/tblInd;
Normal Table tblInd=0; compatibilityMode 15. Only 720s in the package: unused "Body Text" ind left=720 and an overridden
numbering hanging indent. Needs Word or LibreOffice to vary one attribute at a time; no fix.

### #2539 - v10 cannot connect to a self-hosted portal (HEAD /api/2.0/capabilities 404) - not in our 9.4 code
The v10 React start page (routes/clouds/index.jsx checkPortal, still in v10.0.0.176) checks the portal with fetch HEAD and
counts a 404 as unreachable. Our start page (dialogconnect.js _require_portal_info) sends GET through $.ajax /
AscSimpleRequest. Run against a HEAD-404/GET-200 server: ours connects, v10 refuses. Upstream's hotfix (bug 84507) is not
public yet. If we ever take the v10 start page, change the check to GET.

### #2495 - macOS 10.0: Nextcloud files open in a separate window - not reproduced
Reported as a 10.0 regression (9.4.0 works). Our path CheckPopup -> IsExternalCloudEditor("/apps/onlyoffice/") -> CREATETAB
-> AppDelegate onCEFCreateTab opens a window only with editor-window-mode=1; upstream did not change CheckPopup up to
v10.0.0.176 and our #1664 link policy touches only external links. Needs our macOS build + Nextcloud 31 to confirm.

### #1393 - Linux: GNOME Online Accounts (Google Drive) files take ~1 min to open - not reproduced
Needs a GOA Google account. Traced: .desktop Exec %U without X-GIO-NoFuse, so the app likely gets the gvfsd-fuse path,
treats it as local, opens it read-write with an fcntl lock and writes a .~lock marker in the Drive folder - each a Google
API round trip. Next: strace the open on the Linux box before choosing a fix (option: read-only/no marker on gvfs paths).

### #1730 - KDE Plasma 6 kwin_scene_opengl GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT - not ours
Logged by kwin_wayland, not by our process; upstream closed it as KWin bug 491751 (fixed Plasma 6.6+). The app keeps working.

### #2549 - migrate to gtk3/gtk4 for Nixpkgs - not ours
We link gtk+-3.0 (win-linux/defaults.pri) and the deb/rpm name no gtk2; the only gtk2 references are unused legacy
files (desktop-sdk cef/windowsxp cefclient CMakeLists, core libvlc Dockerfiles). The stale gtk2 input was in the Nix
package, removed by NixOS/nixpkgs PR 582158.

### #877 / #1722 - per-language default shortcuts; icon themes - product decisions
#877: any action can already be rebound per editor; locale-specific default sets change everyone's defaults.
#1722: a theme JSON can already carry its own icon sprites ("icons": {"sprite-buttons-base-url"}); an
independent icon-set setting is new UI in six places.


### #739 / #361 / #778 / #1238 / #1611 / #2535 / #2039 / #1858 / #1929 / #60 - triaged 2026-11-12
#739 Restrict Editing / forms protection already works in 9.4 (checked end to end); Forms tab only for form
formats is a product call. #361 equation numbering: no support to build on (see #874). #778 punch/fold marks,
#1238 OS thumbnails, #2535 built-in traffic-light buttons (system title bar since #2504 covers themed WMs),
#2039 Apple Intelligence (needs a Swift bridge), #60 DjVu writer: features/product calls. #1611 pinch works on
macOS; Windows/Linux pass --disable-pinch (client_app.h:314) - an opt-in setting is the follow-up. #1858 copy/
paste pages already merge/split; "insert/extract pages from file" needs a picked-file read/save path (#1664
review). #1929 smart cards: Windows CryptoAPI may already work; PKCS#11/Keychain and PDF signing are multi-week.


### #1828 / #2246 / #2093 / #1801 / #1913 / #420 - accessibility and UI features - triaged
#1828 Linux screen readers: needs AT-SPI detection and a check that our CEF Linux build has ATK (then reuse
#1872's state). #2246 accessibility checker, #1801 command search, #1913 ribbon customisation, #420 pin to
quick access: new UI features / product decisions (QAT is a fixed set of six). #2093 touch: handled in
CMobileTouchManager and the slideshow; the drawing-swipe case is fixed upstream (e3d29d39a4), the media-tap case
needs a touch device.


### #289 / #1804 - slide sorter view; book cover - features
#289: the thumbnails panel already multi-selects, drags, Ctrl(+Shift)+Up/Down moves; a grid sorter view
(c_oAscPresentationViewMode.sorter exists but is empty) is multi-day. #1804: no cover-page feature exists; a
cover designer is a product decision. #2112 paste part: split Paste button with options already in 9.4.


### #278 - custom error bars from sheet columns - UI missing only
The model reads, draws and round-trips c:errBars with custom plus/minus refs (both directions); only a
"Format error bars" dialog with range pickers is missing - more than a day and a UI design.


### #584 - group tabs when there are too many - product decision
The tab bars scroll (win-linux CTabBar, macOS ASCTabsControl); a grouping tab is a new tab-bar design on
two native implementations. Smallest follow-up if chosen: a "List all tabs" menu button.


### #1310 - remove the editor's second header row - product decision, not done
A compact-header redesign of web-apps' Header view (where each control goes); multi-day and a product call.


### #1389 - comment balloons in "Only markup / no balloons" - by design
Simple markup suppresses only track-change balloons (as Word); comments have their own switch, File >
Advanced settings > "Turn on display of the comments".

### #1352 - ~/Downloads created at startup (Linux) - Chromium/CEF behaviour
strace of the 9.4 tarball: CEF init creates $HOME/Downloads only when ~/.config/user-dirs.dirs is
missing (Xfce without xdg-user-dirs); nothing in our code does. Workaround: xdg-user-dirs-update.


### #348 - pptx first line left of the box with indent<0, marL=0 - rule not established
ECMA and MS-OI29500 say nothing about clamping; LibreOffice clamps only bulleted paragraphs; POI ignores
indent for non-bulleted ones. Needs a PowerPoint rendering before changing paragraph layout.

### #1032 - floating table ~720tw right of the margin - offset source not established
MS-OI29500 2.1.162 defaults put the table at the margin, as we do; the only 720 in the file is a numbering
hanging indent that the heading style overrides. Needs Word experiments.

### #2481 - Caps Lock ignored (Wayland + XWayland) - not in our code
Nothing in our tree handles letter case; Chromium decides it from the XWayland keymap. Not reproduced.

### #2287 / #1522 - fcitx candidate scaling / fcitx5 on Plasma 6 Wayland - environment
fcitx draws its own window; the thread fixed it in xwayland-satellite. #1522: we force xcb, so GTK's X11
IM module needs GTK_IM_MODULE=fcitx, which Plasma 6 advises unsetting; a launcher default is possible but
untested.

### #2518 - content smaller than the surface under niri - 10.0 only
The band is 10.0's self-drawn shadow (#2229); our 9.4 frame has a 3px border, no shadow margin.

### #2285 / #1861 - editor fills only part of the window (niri, sway) - probably #694
Both screenshots show the CEF area scaled down by 1/1.3 and 1/1.5 with full-width Qt chrome - #694's
symptom (fixed, desktop-sdk 963c2394) if QT_SCALE_FACTOR was set; the reporters did not say. Not claimed.

### #1208 / #1353 - Hyprland/sway unusable; maximise flicker - reported fixed in 8.x/9.0.4 by users


### #339 - YouTube plugin video does not play in the slideshow - feature gap
The plugin's OLE object plays in edit/view mode; in the slideshow CommonController.js:1652-1656 handles
only desktop media files, so a click goes to the next slide. Never implemented (upstream 36175 open).

### #2272 - AI grammar checker slow - cannot occur in our build
Its grammar/spelling run on the text-annotation API, which our sdkjs stubs out (Document.js
InitCustomTextAnnotator); no onParagraphText/AnnotationRange in the payload.

### #1251 - macOS tab logo has poor contrast - not applicable to our icon
Our dark/light tab logos, composited on the inactive/active tab colours, are about 6:1 and 9:1+.


### #1400 - Debian trixie install appears to fail - not in 9.4
7.5's postinst called update-desktop-database unguarded; upstream removed it (0cf8f92ca). Our .deb built
from the real templates installed, upgraded and purged cleanly in debian:trixie (arm64, stub payload).

### #2208 - PDF editor replaces barcodes - not reproducible for embedded TrueType barcode fonts
"Edit text with origin font from file" (sdkjs d3d730762d, after the reporter's 9.2.1) keeps the embedded
font: a Code 39 TrueType PDF stays bars while editing and after save. Type3/CFF/CID barcode fonts untested.

### #2126 - debug mode sticks - not reproducible (macOS)
--ascdesktop-support-debug-info-keep=1 persists via settings.xml and =0 clears it. Windows "Open with"
not run. Side note: CheckSetting persists every --x=y switch (inert for the debug port).


### #648 - content flickers dark on tab switch (Linux, light theme) - not reproducible here
The reporter's GIF shows one dark (#3c3c3c) frame over the content per switch; no light-theme colour
matches. The tab's X window was white until #2528 (desktop-sdk ce7cdbdb) gave it the theme colour, and
upstream tab-flicker fixes since 6.3.1 are in our tree. Likely the system palette or compositor before
first paint; needs a Linux GUI build with a dark GTK theme + light app theme.


### #2493 - "Paste as plain text" missing (10.0) - not reproducible in 9.4
In an app clone with real CDP clicks, the Paste split-button shows "Keep source formatting" and "Keep
text only" for external and in-document copies. A greyed menu appears only when the clipboard read
fails (no user gesture). Upstream's 10.0 trigger (their 84857) is not in v10.0.0.176. Side finding,
unfixed: initSpecialPasteData (clipboard_base.js:1663) calls _callback() on null paste_data and then
dereferences it - a missing return.

### #1005 - Polish translation of the print dialog (Linux) - nothing to translate
The 2022 screenshot is Qt's QPrintDialog (only qtbase_ru.qm shipped). 9.4 on Linux uses GtkPrintDialog,
whose labels come from the system gtk30 catalogue; our own strings are in langs/pl.ts. Not shown live
(no pl locale in the container).

### #2130 - subpixel UI text despite grayscale system antialiasing (Linux) - needs a Linux GUI
Nothing reads the system setting; the only hook is --disable-lcd-text on ALT Linux (client_app.h).
Proposed: also add it when Xft.rgba is none / GNOME antialiasing is grayscale / KDE XftSubPixel none,
once a Linux run confirms CEF 109 ignores GTK's setting.


### #1621 - grey window after Win+Shift+Arrow to another monitor - Windows/GPU only
Upstream reproduced only on Intel Arc (their 68947), both monitors 150%. Nothing in our code ties
rendering to the shortcut path; likely CEF/GPU compositing. Needs Windows with two monitors.

### #566 - table cursors tiny on HiDPI (Linux) - not testable here
CSS image cursors (editorscommon.js CHTMLCursorModern) scale with the app's pixel ratio, not the OS
cursor size; whether CEF 109 draws the SVG cursors at device scale needs a HiDPI Linux GUI run.

### #1976 - side panels turn back on (Windows) - not reproducible, no code defect found
Panel state lives only in localStorage (sse-hidden-leftmenu/rightmenu); the reporter's video also shows
first-run hints, i.e. the whole localStorage came back empty - a lost/locked CEF profile database.


### #950 - dot accent position in presentation equations - not reproducible in 9.4
Headless slide editor: \dot x renders with the italic shift (dot centre 26 px vs letter centre 21), as
Word; pptx and docx x2t output identical. The 7.1 picture does not occur.

### #415 - Chinese characters not displayed - not reproducible in 9.4
Chinese in Arial/Calibri/Times/default and several East Asian fonts all render via per-glyph fallback
(Heiti SC / Arial Unicode MS); no squares. The 5.5.1 report predates the fallback.


### #644 - release notes in an unexpected language (macOS) - appcast authoring, not app code
Our vendored Sparkle 2.0.0 picks an xml:lang="ru" releaseNotesLink whenever ru is anywhere in
AppleLanguages if the English link has no xml:lang; tagging it xml:lang="en" fixes it. Ration Docs
ships no feed (no SUFeedURL). If we publish an appcast, every releaseNotesLink needs xml:lang,
including "en". Separately: a fresh profile shows Sparkle's "Check for updates automatically?" and the
app menu has an enabled "Check for Updates..." with no feed - both should be hidden.

### #647 - app title becomes smaller after a click - not on macOS, not reproduced on Linux
macOS title bar is native Cocoa. On Linux/Windows 9.4 the main window's title label is empty
(__DONT_WRITE_IN_APP_TITLE) and activation only fades the title buttons; the auto vs 150% DPI mismatch
in the thread is the auto-DPI computation #1468 reworked. Needs a Linux check at auto scaling.


### #350 - ppt: additional text/background image - BLOCKED (files gone)
Both reporter files were on cloud.univ-grenoble-alpes.fr shares that now answer "Partage non trouvé".
Upstream fixed Presentation1.ppt in 7.0.1 and tracks Presentation2.ppt as their 56546.

### #342/#343/#346/#347/#348 - pptx text placement series - no PowerPoint reference, no fix
#342: off-centre text matches plain Tahoma advances - PowerPoint lays out differently (unknown how).
#346: Arial Bold line is 358.64pt for 357.6pt available; we wrap, PowerPoint tolerates ~1pt.
#347: no measurable defect. #348: indent=-385763 with marL=0 puts our first line left of the box;
if PowerPoint clamps marL+indent >= 0 that is the bug - needs a PowerPoint rendering to confirm.
#343: TD02-4 fine per the reporter; TD02-3 tab-driven lines overflow - expected behaviour unconfirmed.


### #312 - Decrease Decimal on empty cells in a selected row/column - not reproducible in 9.4
Real cell editor, whole rows/columns selected, format 0.00 then decrease/increase 1-3 times, values
typed into near and far empty cells (A50000, XFD1): every cell got the shifted format.
changeDigNum applies one format to the range. Mouse selection in the GUI not tried.

### #374 - moving between cells is slow - not reproducible
20,000x35 workbook with 80k formulas: ~16 ms per arrow move (frame-bound), commit ~55 ms; with 20k
volatile formulas commits take ~420 ms (recalc), moves unchanged. Reporter's file never shared.

### #556 - Exclude Title from the table of contents - not reproducible in 9.4
Default Title style has no outline level, so TOC \o "1-3" never lists it (checked in the headless
editor); giving Title outline level 1 lists it, as Word does. The reporter's Title came from a template
with an outline level. Workaround: TOC from selected styles. No defect.

### #1046 - Hindi InScript halant + char gives three halants - not reproducible in 9.4
Real ibus-m17n hi:inscript keystroke traces (Ubuntu 24.04 container) replayed through Chromium's IME
path into the 9.4 word editor give the correct conjuncts (क्रिया, ब्लू, गल्लो), as a plain textarea. The
report predates the 7.2.1 input rewrite (text_input2.js). Live ibus into the editor under Xvfb not
achieved (focus).


### #1664 - Outdated and vulnerable v8 is used - APPLIES TO US (security assessment, 2026-11-11)
Every platform ships CEF 109.1.18 / Chromium 109.0.5414.120 (V8 10.9.194.10, confirmed in the shipped
framework); Linux/Windows x2t/docbuilder use V8 branch-heads/8.9 with JIT on (build_tools v8_89.py:445);
macOS arm64 x2t links the system JavaScriptCore. Upstream has nothing newer (build_tools v10.0.0.176 and
master fetch CEF 5414; desktop-sdk feature/cef-update (CEF 138) stalled 2025-08). CISA KEV lists 30
in-the-wild Chromium bugs since our build, incl. libwebp CVE-2023-4863 - reachable by opening a document:
x2t passes WebP bytes through as media/*.png and <img> decodes them.
Worse, and ours to fix: (a) PDF form JavaScript runs via EvalScript (sdkjs pdf/src/forms/formActions.js:756)
with full global access, reaching the AscDesktopEditor bridge - shown by running the real code; (b) the
bridge is injected into every page and iframe of every origin (client_renderer_wrapper.cpp ~6560),
including the plugin store, YouTube embeds and cloud portals; (c) the macro warning's default button is
"enable" and the JS macro sandbox escapes via the AsyncFunction constructor (macros.js _safePluginEval);
(d) no_sandbox, --disable-site-isolation-trials and --allow-file-access-from-files are all set. Links in
documents do go to the system browser. Fix order: isolate PDF JS, gate the bridge by origin, macro dialog
default "No", restore site isolation; then a self-built CEF upgrade (the only fix for the engine CVEs).

**Hardening landed 2026-11-11** (fork-fix-tests/issue-1664-*):
- PDF form/annotation JavaScript runs in QuickJS compiled to WebAssembly (sdkjs pdf/src/scripting,
  engine/pdfscripting.js, npm packages pinned by sha512; rebuild is byte-identical). Only allowlisted
  form API crosses in; 3 s deadline and memory/stack limits. Test app: the rd-1664 form computes as
  before and the escape probe reads "contained".
- window.AscDesktopEditor only for our own pages (file:// under the app and user plugin dirs,
  onlyoffice://plugin, ascdesktop:// error pages), connected cloud portals and their document-server
  frame (desktop-sdk bridge_access.h); remote iframes, data:, other file:// and unconnected servers
  get none.
- Macro warning: "No" is the default/Enter, the text says macros can touch this computer, and files
  from Downloads/mail/temp always ask; AsyncFunction/AsyncGeneratorFunction/GeneratorFunction
  constructors and import/**/() closed; a rejected macro no longer leaves intrinsics broken. A macro
  the user runs is still trusted code (deferred callbacks and Api objects lead back to window) -
  stated in the warning. Test app: Enter runs nothing, Yes runs the macro.
- Site isolation: full --site-per-process breaks the AI agent's convertFileExternal and cross-origin
  cloud editors (messages go to the main frame's process), so the trials switch stays and
  --isolate-origins puts onlyoffice.github.io and the YouTube origins in their own processes.
  --allow-file-access-from-files must stay (the editors XHR their templates/locales from file://).
- Engine upgrade: plan in CEF_UPGRADE_PLAN.md (CEF 156; macOS 13 minimum; 7-11 engineer-weeks to a
  shippable macOS build).
Follow-ups found: the YouTube plugin and the plugin store pages load scripts from the network into
file:// pages with the bridge (bundle them); _createProcess is reachable from any onlyoffice://
frame; the renderer sandbox needs ~200 renderer file operations moved behind IPC first;
cefview.cpp OnFileDialog does not match the 109 signature (no override) and has never been called.

**Follow-ups landed 2026-11-11** (sdkjs b0a9cfb763, desktop-sdk a000faca 4f9635f9 67c62bc5,
desktop-apps 2745193bc, onlyoffice.github.io cdfcd7a local only; tests issue-1664-webp-guard,
-paste-webp, -createprocess-gate, -file-access, -no-remote-scripts):
- WebP/AVIF bytes are stopped before Chromium 109's decoders (document images in desktop-sdk,
  pasted data: URLs in sdkjs), closing the libwebp CVE-2023-4863 route through an opened document.
- Bridge _createProcess and arbitrary-path writes are gone for plugins; the AI agent's MCP server
  commands ask the user first (macOS, Windows, Linux).
- file:// pages and the bridge read only the app, editor, plugin and user-data folders, not any file.
- YouTube and plugin store pages no longer load remote scripts into file:// pages.
- OnFileDialog now overrides the 109 signature (970a438c); override sweep f7f79a14.
Still open:
renderer sandbox; CEF upgrade; PluginInstall runtime download (below).
- Links from any page (document hyperlinks in all editors, PDF links, plugin/start-page window.open)
  go through desktop-sdk link_policy.h in CheckPopup: http/https/mailto open as before; programs,
  bundles, scripts, installers, javascript:/data:/ms-msdt: etc. are refused; anything else (local
  files/folders, smb, other app schemes) needs a native confirm, Cancel default (desktop-sdk 833fea20,
  desktop-apps 9b2f78275). The link warning rendered the link as HTML - a hyperlink target could run
  script in the editor frame as soon as the warning showed; now escaped, and the desktop app asks once
  natively (web-apps 6b3b01aa96). Tests issue-1664-doc-links, -doc-links-webapps. Test app 2026-11-11:
  a Calculator.app link from the editor did not launch. Open/Cancel not clicked live; Windows/Linux
  dialogs not shown live.
- AI agent tool calls (callToolFunction) only answer the bundled agent's frame; they read at once only
  files the user picked, dropped or attached (or a tool wrote), and ask the user for any other path
  (same confirm as MCP commands; "Don't Allow" default; remembered until quit). The _saveAndOpen eval
  had a stray `}` (SyntaxError, so the callback never registered and the result went to converter id
  1); fixed, and the agent's inverted success checks too (desktop-sdk f86491b2; test
  issue-1664-ai-tool-files). Dialog text and Allow/Don't Allow not yet clicked through in the GUI.
- User-installed plugins run in their own origin rdplugin://<guid>/ (desktop-sdk c9b26fcebc
  plugin_scheme.h, sdkjs ff6eb2e4e3; test issue-1664-plugin-origin, bridge-origin extended). Before:
  file:// origin, parent.document and the 233-member bridge reachable, and ascdesktop://fonts//etc/hosts
  read any file from a local editor's frames (m_bIsLocal skipped path checks; now refused for user
  plugins). Plugin tier allowlist: file dialog, GetImageBase64 of picked files only, scale values,
  generateNew/getGenerationInfo. Encryption password no longer reaches plugin frames. localStorage
  migrated once for keys the plugin's own files name. Approved by the product owner 2026-11-11 with
  known losses: a user-updated AI plugin (ran at onlyoffice://plugin) loses keys and current
  model/provider; user-installed encryption plugins lose the crypto bridge; LAN http blocked as mixed
  content; non-alphanumeric GUIDs don't load. Live: OCR, AI plugin, Plugin Manager, store
  install/run/uninstall OK. Not verified: picking a file then GetImageBase64; migration across restart.
  Still open for other frames: ascdesktop:// / onlyoffice:// path checks skipped for local editors.
- Symlinks/junctions inside allowed folders (and a link at the end of a ?lang= / param-suffixed
  scheme path) now resolve before the check (desktop-sdk 8a118ef3, NSFileAccess::ResolvePath; test
  issue-1664-symlinks). Windows branch only syntax-checked; hard links and a swap-after-check race
  remain by design.
- Plugin store (onlyoffice.github.io 683027f, local only; test issue-1664-store-html): every remote
  config.json/rating value is escaped, CHANGELOG markdown is rebuilt from allowed tags only, card links
  must be http(s)/mailto. Not yet GUI-checked in an app build.
- build_tools fetching v1/plugins*.js: already fixed on lab02 by a3a1931 (pinned, checked-in copies;
  test issue-1664-build-plugin-api). Note a3a1931 also drops the plugin manager from desktop deploys
  unless the build config sets desktop-marketplace="1" - a product decision, not yet made.
- AVIF (and any picture core cannot re-encode) was dropped from docx/xlsx/pptx on every save since
  before the guard: CImageManager2::GenerateImageExec pointed the rel at a .png it never wrote. Now the
  original bytes are kept; avif -> image/avif (core 0228100ad6; test issue-1664-avif-save). Not yet
  GUI-checked; odt/doc/rtf saves not tested.
- PluginInstall downloaded plugins.js, plugins-ui.js and plugins.css from onlyoffice.github.io into the
  user v1/ folder on every store install/update, and every user plugin loads them; Init_CEF's refresh
  used a file remove on that directory, so a downloaded v1/ was never replaced, even across updates.
  Now the app's pinned v1/ is copied on install and replaces the user copy at start-up (desktop-sdk
  793de03c; test issue-1664-plugin-api-runtime; test app: a planted stale plugins.js was replaced).
  The remote plugins.js already differs from ours (adds ignoreDisabledToolbar). Still open: store
  plugin packages themselves (<baseUrl>/deploy/<name>.plugin, "releases/latest") have no integrity
  check or pinning, and an http:// baseUrl would be accepted.

### #2238 - IME candidate panel overlaps text in split (snapped) window - not in our page code
Windows / 9.2.1 / Microsoft Pinyin; "split" = Windows snap (from the attached video). The IME anchor (hidden
textarea, common/text_input2.js) was reworked upstream (bug 78151, sdkjs ee2e0b3843, in our tree). Real word
sdk in headless Chromium, CDP imeSetComposition, composition box vs caret at 1350x900, snapped 959x1040,
maximized, resized mid-composition, scrolled, DPR 1-1.75: the box always spans the caret line and opens
the IME below it, following every resize. The remaining suspect is CEF/TSF screen mapping after a frameless
Qt window snap on Windows. Needs a Windows check of a 9.4 build.

### #2519 - editors_helper.exe left in memory after closing (Windows) - not on macOS
macOS 9.4 test app, 10 quit cycles (bare, docx, docx+xlsx+PDF, slideshow, AI plugin, AI agent panel): every
helper gone in 1-5 s; even SIGKILL of the browser takes them down (POSIX suicide-on-channel-error). Windows:
the normal quit reaches CefShutdown (applicationmanager.cpp:978-995, cefapplication.cpp:639-679); the only
path that skips it is the _WIN32 early return in CApplicationCEF::Close() (CEF #2703 workaround), and an
unsandboxed Windows renderer has no kill-on-close job. Not crashpad, not updatesvc. On the Windows x64
machine: is editors.exe still alive (parent PID)? if so dump it (hang in close); if orphaned, procdump the
helper; log whether Close() takes the early return.

### #2458 - Linux/GNOME Wayland: ABNT2 dead keys fail; --enable-wayland-ime makes File > Exit hang - not reproduced
Our Linux host is X11-only (main.cpp:110-111 forces xcb/x11; CEF browsers are X11 children), CEF 109.1.18.
Our real linux_arm64 libcef under Xvfb with setxkbmap br abnt2 and xdotool dead keys gives "ãéç" with the
GTK simple context, IBus GTK module and IBus XIM, on Ubuntu 24.04 and Fedora 44 (the reporter's OS); replaying
Chromium's composition events into the real word editor inserts "ãéç". The failure needs a GNOME Shell
Wayland session. --ozone-platform=wayland is unsupported (Wayland Chromium under an X11 host); the app quits
only on CEF_DESTROYWINDOW, so a close that never fires OnBeforeClose leaves it waiting. Possible hardening,
not done: force --ozone-platform=x11 for CEF. Aside: GTK_IM_MODULE=wayland kills our libcef at start on X11.

### #2019 - Horizontal scroll with second mouse wheel not working - not in our JS
Windows 9.0.4, Logitech MX Master thumb wheel: 3 columns, then horizontal scrolling stops until another
tab is opened. Real CDP mouseWheel events with deltaX only scroll horizontally on every event in the
cell editor (Windows and macOS paths), word at 300% and via checkMouseWhell for slide/PDF; no state in
cell/view/EventsController.js:2103 can stop after one event. "One notch, then nothing until focus
changes" points at WM_MOUSEHWHEEL delivery to the CEF window (Windows-native, unhandled by our
shell). Needs Windows + MX Master. macOS two-finger horizontal swipes (deltaX-only) work.

### #2530 - window unmaximized when a presentation ends - 10.0 only
Our 9.4 shell never un-maximizes the window for a slideshow: win-linux moves the panel into a separate
widget and showFullScreen()s that, the main window is only hide()n/show(false)n (Qt keeps
WindowMaximized); macOS full-screens the CEF view and only hides/shows the window. Same code in
v10.0.0.176; 10.0 changed the Linux window platform layer (thin frame, frame extents), the likely
culprit. Ran the real CWindowPlatform::show under Xvfb + openbox: stays maximized in all four setups.
macOS test app, two slideshow cycles: the window comes back to exactly its frame (1024x828 at 1323,411).

### #1845 - Fullscreen triggers oscillatory jumping - not reproduced (Linux, Xfce/LXQt)
Upstream 9.4.0.129 under Xvfb + xfwm4 (compositor on/off, CPU throttled, 7 maximize/restore cycles)
always settles at 1920x1052. The reporters' videos show only the Chromium surface alternating sizes,
so the loop is in CEF X11 child-window sizing: QCefView::UpdateSize (qt_wrapper/src/qcefview.cpp:486-524)
XConfigureWindow's cef_handle and CEF's own windows on CefGetXDisplay() without XFlush while
CefWindowX11 resizes the same child from another connection. Needs a real Xfce/LXQt box; first fix to
test: XFlush in SetWindowSize and stop sizing the grandchild.

### #2565 - AI Tools getting errors when editing current document - not in our tree
10.0's new in-editor chat (ONLYOFFICE/onlyoffice-ai-chat) drops the tool result from the Mistral
history, so the first request after any tool call ends in assistant(toolCalls) and Mistral answers
400/3230. That is the pre-#2524 converter; our ai-agent was fixed in ac6f93e4. Running our
utils.ts on the reported thread: pre-#2524 fails, now ends in a tool message. Our 9.4 editors ship
the AI plugin 3.2.3, whose agent loop sends tool messages. Product note: a future chat panel will be
wired to our own chat module, not ONLYOFFICE's.

### #1428 - Display issue in Spreadsheet on Mac (zh cell-style gallery) - fixed upstream, in 9.4
The defect is the canvas-drawn cell-style thumbnails (tofu and a Japanese serif face for Chinese
names), i.e. the CJK fallback range in AllFonts.js. Upstream fixed the Mac ranking after 7.5.1
(core 95d2939a73 PingFang, e8ecb2cdfb Heiti/Songti), both in our core. Rendering the real gallery
with this Mac's AllFonts.js for zh/zh-tw/ja/en at 1x and 2x: all CJK maps to Heiti SC, no boxes.
Forcing the range to Hiragino Mincho reproduces the reported picture.

### #1561 - Printing to PDF has problems (spreadsheet "print selection") - fixed upstream, in 9.4
"Print to PDF" is a save-as through x2t that reopens Editor.bin + changes; 8.x printed the
selection stored at open time. Fixed upstream in sdkjs 9b0c27e450 (bug 75637): the live selection
travels in pageSetup.selection. Ran the real cell sdk + payload x2t: B2:C4 -> 1 page/6 cells,
B10:J100 -> 2 pages/819 cells, no other sheet, no erased text; asc_Print gives the same counts.

### #2475 - Printing pages upside down (duplex long edge)
Checked our Linux print path (ceditortools.cpp, cprintdata.cpp, gtkprintdialog.cpp, qascprinter.cpp - SetPageOrientation
is a no-op - and fileprinter.cpp CheckPrintRotate, which rotates only 0/90 by page size). Reproduced in Docker (Qt 5.15 +
CUPS + generic PS PPD with Duplex, QPrinter set up as ceditortools does): a portrait long-edge job goes out as
`sides=two-sided-long-edge Duplex=DuplexNoTumble`, final PS `<</Duplex true/Tumble false>>`, every page 595x842 upright;
short edge gives Tumble true. Qt 5.9.9 (shipped) has the same CUPS option code. Nothing of ours flips alternate pages; the
printer or driver applies the wrong tumble. Needs the reporter's printer model, PPD and a CUPS debug log. The suspected
IPP-only duplex loss in the GTK dialog was run too and does not happen: driverless printers get a temporary queue with a
PPD, and on a queue without one Qt refuses duplex whatever we pass.

### #1947 - Landscape prints portrait (Windows half)
The Linux half is fixed (see the Fixed table). Windows: our side maps A4 + landscape to DMPAPER_A4 / DMORIENT_LANDSCAPE
(printdialog.cpp); the "User defined" paper the reporter sees for landscape is not reproducible here and needs a Windows
check with the reporter's printer (Epson L565, driver 2.43).

### #2474 - Ctrl+. crashes the editor on Linux

Not reproducible on macOS, and nothing in our shell handles Ctrl+. - neither
desktop-apps nor desktop-sdk's key handling sees the combination. On GNOME,
Ctrl+. is IBus's emoji-picker shortcut, and the XCB BadMatch errors before the
segfault point at the input-method path inside Chromium (CEF 109), not at our
code. Needs a Linux box with IBus and a backtrace. (2026-10-27)

### #2446 - numbered-list font and size not saved

The maintainer could not reproduce it on 9.4 or 10; not tried here. Possibly
related to #2507 (numbering.xml written out of schema order, fixed) if the file
is then opened in another application. Waiting for a file.
(2026-10-27)

### #2473 - date filter "All dates in the period -> October" shows nothing

Not reproduced, and left. The reporter confirmed it works after updating to
10.0 and upstream closed it; no commit between v9.4.0.131 and v10.0.0.176
names it. Read on our tree: the October entry in `AutoFilterDialog.js` sends
`c_oAscDynamicAutoFilter.m10` (8 - the enum is in alphabetical order, m1, m10,
m11, m12, m2...), and `DynamicFilter.prototype.isHideValue` maps m10 to month
index 9 and compares `getUTCMonth()` of the cell's date, the same path as every
other month. Nothing month-10-specific found. Needs a file and the locale
(German UI, dates typed DD.MM.YYYY from a CSV) before anyone looks again.
(2026-11-04)

### #2443 - spreadsheet unable to save after adjusting table structure

**Not reproduced**, and it cannot be from what is on the thread: there is no
attached file, and the reporter could not restate the steps ("I did some more
adjusting"). What was landed is a defect found along the reported path that
would produce these symptoms; it is not proof that it is *the* cause.

**The defect.** The row and column structure operations suspend recalculation
across their whole body - `DependencyGraph.lockRecal()` raises a counter and
`calcTree()` returns immediately while it is above zero (`Workbook.js`, "if
(this.lockCounter > 0) { callback && callback(); return; }"). The matching
`unlockRecal()` sat at the end of the function with nothing between them to
survive a throw. So one exception anywhere in `_insertColsBefore`,
`_insertRowsBefore`, `_removeCols`, `_removeRows` or `lockRecalExecute` left the
counter stuck above zero and the workbook unable to recalculate **for the rest of
the session**. Nothing reports that state.

That is a close match for the report: "formulas break, stop working, cells show
empty, but no visible errors", and a freshly typed `=SUM(A2+1)` blank as well -
which is exactly what a document that has stopped recalculating looks like, and
exactly why there was no error to point at.

Fixed by releasing the lock while unwinding. `unlockRecal(true)` skips the
recalculation itself: the model is mid-failure, and running `calcTree` over it
would at best throw again and mask the original error. Ignoring indentation the
change is purely additive - 55 lines inserted, none removed - so every success
path is untouched. `fork-fix-tests/issue-2443-recalc-lock-test.js` extracts the
real `_insertColsBefore` and the real lock members by brace matching, forces a
throw at the first call the body makes, and checks the counter returns to zero
and the next edit recalculates; `BASELINE=1` fails with `lockCounter=1`.

**Ruled out along the way**, so nobody repeats the search: `_insertColsBefore`'s
`borders` array is not read when it is undefined (the `prevCellsByCol` block that
indexes it is inside `if (!bUndoChanges)`, which is the same condition that
assigns it, and `index > 0` guards both). `TablePart.addTableColumns` renumbers
correctly when several columns are inserted, because `_generateColumnName2`
rebuilds its name map on each call and so sees the names already assigned in that
loop. Inserting a column at the table's first column deliberately shifts the
table rather than joining it - that is Excel's behaviour too, and it is what the
reporter hit as "wasn't able to make this new column a part of the table", not a
bug. The copy-as-image the reporter saw is a deliberate clipboard flavour
(`cell/model/clipboard.js`, `printForCopyPaste` then `toDataURL`), not an error
fallback - getting *only* the image means the data flavours came back empty.

**What would move this forward:** the file, or the browser console from a session
where it happened. The remaining 35 `lockRecal()` call sites across `cell/` have
the same shape and have not been converted.

### #2430 - xlsm with a Form Control checkbox cannot be saved - HALF FIXED

**Reproduced here**, from the reporter's own `example.xlsm`, and bisected against
our own x2t. The abort is fixed and verified. **The underlying defect is not** -
read the last section before assuming this issue is closed.

**The bisect.** Same file, same changes directory, one variable at a time:

| | result |
|---|---|
| bin -> xlsx, no changes | exit 0 |
| bin + changes, plain control sheet | exit 0 |
| bin + changes, `m_bFromChanges` true but no changes dir | exit 0 |
| bin + changes, VML checkbox removed from the file | exit 0 |
| **bin + changes, checkbox present** | **SIGABRT** |

So it needs the apply-changes path *and* the checkbox, which is exactly what the
reporter said. `0xC0000409` on Windows is how this same abort surfaces there.

**What was fixed.** A breakpoint on `__cxa_throw` never fires; one on
`std::terminate` shows frame #1 `__cxa_rethrow`. That is a bare `throw;` running
with no exception in flight. There were **fourteen** of them, one in every bounds
check of `CBinaryFileReader` (`OOXML/Binary/Presentation/BinaryFileReaderWriter.cpp`
- the file name is historical, this reader is shared, not presentation-only):
`Seek`, `GetUChar`, `GetChar`, `GetUShort`, `GetShort`, `GetULong`, `GetLong64`,
`GetRecordSize`, `GetDoubleReal`, `GetString1`, `GetStringUtf8`, `GetString3`,
`GetString4`, `GetPointer`. They read as "give up on this read" and could never do
anything but kill the process.

That is a class, not one file: any binary that sent this reader past the end of
its buffer took x2t with it, silently, and the editor turned that into "This file
cannot be saved or created" with the user's edits unwritten. All fourteen now
throw `std::out_of_range` naming the function and position. Verified on a rebuilt
binary (checked by `strings`, not by trusting the build - see the build note
below): **exit 134 SIGABRT becomes exit 80, a clean conversion error.**

**What is still broken, and where to start.** The file still does not convert. The
exception says where:

    CBinaryFileReader::GetRecordSize (record length 797560):
        read outside the buffer (pos 1647, size 3789)

`GetRecordSize` reads a record length from the stream and checks
`m_lPos + sz > m_lSize`. Position 1647 in a 3789-byte buffer is well inside it, and
the length read there is **797,560** - two hundred times the size of the whole
buffer. That is not a truncated or short record; it is not a length at all, so
**the reader has lost sync with the stream** and is reading structure out of the
middle of something else. It happens partway
through a small sub-stream, and only when the VML checkbox is present. The next
step is to find what sdkjs's serializer writes there for a legacy drawing and where
the C++ reader's idea of the layout diverges from it. The throw site now reports
the record length as well, because the position and size alone read as survivable
and hide the desync.

### A build defect found while verifying this, which matters on its own

`make.py` exited 0, and the x2t it deployed did not contain the change that had
just compiled. This happened **twice**, and the second time looked like this:

    Sep 14 17:36  hasNewCode=1  core/build/lib/mac_arm64/libPPTXFormatLib.a
    Sep 14 17:29  hasNewCode=0  core/build/bin/mac_arm64/x2t
    Sep 14 17:41  hasNewCode=0  build_tools/out/.../converter/x2t

The deployed binary has the **newest mtime of the three and the oldest content** -
it is new only because it was copied. Nothing about the build looks wrong.

The cause is `ADD_DEPENDENCY` in `core/Common/base.pri:711`, which does only
`LIBS += -L<path> -l<lib>` and never sets `PRE_TARGETDEPS`. So make has no
dependency edge from any target to the static libraries it links, and will not
relink when one changes. Every project in the tree that uses `ADD_DEPENDENCY` is
affected, not just x2t.

**Consequence:** any change in `core` that does not touch a given binary's *own*
sources may not reach that binary on an incremental build. This is a plausible
mechanism for #2445, which was recorded above as somebody else's packaging
accident - a mismatched `ooxmlsignature.dll` shipped beside a newer kernel is
exactly what this produces.

**Workaround in the meantime:** delete the binary before rebuilding
(`rm core/build/bin/<platform>/x2t`), and check the result with `strings` rather
than trusting the exit code. **Proposed fix:** have `ADD_DEPENDENCY` add each
static library to `PRE_TARGETDEPS`. Not done here - it touches every project in
the tree and needs a clean build and an incremental build to verify, which is more
than this issue should carry.

### #2424 - Accounting-formatted numbers print as garbled text (Chinese)

**Not `core`, and not garbling.** The screenshots show `##############`, which is the
column-too-narrow indicator, not mojibake. That fill is decided in
`sdkjs/cell/model/Workbook.js:17558`.

Swept column widths 7.0 to 12.0 through x2t's PDF path: Accounting needs a width of
9.0 where `#,##0.00` needs 8.0 - a one-character difference, and Excel reserves the
same space for the currency symbol and the closing pad. No `####` appears at any
width where the text actually fits. So the behaviour is correct and the report is
about a column that is one character too narrow for the format applied.

**What did come out of reproducing it** is a real defect with no issue of its own: the
literal run-in and run-out of a number format section were being written into the CSV
as plain text, so an Accounting cell exported as `_ * 8745.00_ `. Fixed; see the Fixed
table.

### #2318 - some fonts are not rendered properly on Linux - FIXED 2026-11-10
Correction: the fix was in sdkjs, not core. Wingdings is substituted by the bundled OpenSymbol, and
`ChangeGlyphsMap` (`common/libfont/map.js`) translated only 10 codes; `textshaper.js` also remapped
only the first symbol of a run. Table built from LibreOffice's aWingDingsTab, filtered to glyphs
present in OpenSymbol 102.10 and 102.12 and checked by eye (139 codes). Verified with the reporter's
docx through x2t with Ubuntu fonts. The missing space before "Être" in the same report is a separate
MS Gothic metric-substitution question, not fixed.

### #2399 - draw.io plugin: PDF export and print preview fail

Not ours, and not a code defect. `onlyoffice.github.io/sdkjs-plugins/content/drawio/vendor/drawio/webapp/js/PreConfig.js:7`
ships `window.EXPORT_URL = 'REPLACE_WITH_YOUR_IMAGE_SERVER'`. draw.io renders PNG, JPEG,
SVG and HTML in the browser but POSTs PDF and print preview to that export server -
which is exactly the split the reporter sees, and explains the message in their
terminal. The placeholder needs to point at a real export service, or those two formats
have to be disabled in the plugin.

### #2012 - PDF export garbles auto-skewed and auto-bolded fonts

**Appears fixed since 9.0.3; not reproducible on this tree.** Built the reporter's exact
condition twice - Open Sans, which has no italic face, and then a font directory with
the bold-italic faces deleted - and both render correctly.

Decoding the streams shows what was wrong then: their 9.0.3 PDF reuses `/F3` with `2 Tr`
but allocates a brand-new subset code for every character, including ones already in
that subset, which is the glyph-to-subset mismatch. Ours reuses the existing codes
`0001..0008` and adds only genuinely new ones. Recorded so nobody re-derives it.

### #2394 - the app crashes on Open Local File, Save and Save As

Same family as #2136 and #2355, and closed by the same version script - though, as
with #2355, not verified against this reporter's own system.

Everything in the report fits that mechanism and not much else. It is the in-process
GTK file chooser that dies, and running with `--native-file-dialog
--xdg-desktop-portal` - which replaces that chooser with the portal - is the
reporter's own workaround. The system is a Chinese locale with a CJK UI font
(腾祥嘉丽细圆GB18030), and the maintainer's question on the thread is whether that font
is involved. It is: the font is the trigger, `libgraphics.so` exporting its bundled
FreeType 2.10.4 is the mechanism, and cairo and pango binding their `FT_*` calls to it
while painting a file name is where it goes wrong. See #2136 for the full account.

`graphics.version` localises `FT_*`, `ft_*`, `hb_*`, `_hb_*` and `Brotli*`, and
`graphics.pro` applies it under `core_linux:graphics_dynamic_library`.

Two other things in the report are separate and are **not** addressed by that:
fractional scaling (the reporter mentions `--force-scale=1.25` as a workaround for
the scaling, not the crash), and their note that pptx cannot be worked around at all
- which has no explanation yet and would need its own reproduction.

### #2230 - pasted content disappears when switching document tabs

**Not reproducible from what is on the thread**, and this one is worth someone's time
when it is: content pasted into one open spreadsheet vanishes after switching to
another tab and back. That is data loss with no error, in the one place a user has no
reason to check.

What the report has is a video on the reporter's own Nextcloud and a five-line
sequence: copy in one sheet, switch, paste, switch back, switch again, the paste is
gone. There is no file, no version of either document, and no indication whether the
destination was ever saved. Nothing in it says whether the paste reached the document
model and was later discarded, or never committed at all - and those lead to opposite
places in the code.

**What would settle it:** both files, or a browser console from a session where it
happens. Failing that, the two candidates to separate are (a) the paste completing
asynchronously and being abandoned when the view is switched away, and (b) the paste
landing but not marking the document modified, so a later reload of the tab restores
the last saved state over it. (b) would also explain why the content comes back
missing rather than partially applied.

### #2145 - random SIGSEGV in libascdocumentscore.so on Fedora

**Not actionable from what is on the thread**, and it is worth saying exactly why so
nobody re-reads it hoping otherwise.

Two crash reports, and both are a *single frame*:

    #0  0x00007fdddc4f056f n/a (.../libascdocumentscore.so + 0x2f056f)
    #0  0x00007f7d792f6522 n/a (.../libascdocumentscore.so + 0x2f6522)

No unwind past frame 0, symbols stripped ("n/a"), and the two offsets are different
in different releases (9.1.0 and 9.2.0). An offset is only meaningful against the
exact binary that produced it, which is a shipped Flatpak build, not ours. There is
nothing here to resolve.

The second reporter does give a real repro - open a spreadsheet, select a cell,
press Ctrl+; to insert the date - which is worth keeping, because it is the only
deterministic handle anyone has offered. It does not lead anywhere from source
alone: `Ctrl+;` reaches
`c_oAscSpreadsheetShortcutType.CellInsertDate` in `cell/view/EventsController.js`,
which only opens the cell editor with empty text, and a SIGSEGV is native - JS
cannot produce one. Whatever dies, dies below that.

**What would move this forward:** a backtrace with frames, from a build with
symbols, or a core file plus the exact package it came from. Failing that, driving
Ctrl+; against our own build under a debugger - the harness in `../../harness/` can
launch a build and drive the editor over CDP.

Worth noting for whoever picks it up: the first reporter's crashes are random, 1-3
a day, sometimes on resume from suspend; the second's are deterministic on one
shortcut. Those are not obviously the same defect, and treating them as one issue
may be part of why neither has moved.

### #2434 - exits silently after Qt initialisation under FreeBSD Linuxulator

Fixed, though not verified on FreeBSD - see the caveat at the end.

`CSocket` decides whether this process is the primary instance by binding a UDP
socket to `127.<uid-1000>.1` (`inetAddrFromUserId`, `csocket.cpp`), so that two
users on one machine do not fight over port 13012. Linux puts the whole of
127.0.0.0/8 on `lo`, so that address binds for any uid. **FreeBSD configures only
127.0.0.1 on `lo0`**, and the Linuxulator uses the FreeBSD network stack - so
every uid but 1000 fails that bind with `EADDRNOTAVAIL`.

`createSocket` could not tell that apart from `EADDRINUSE`: any failure meant
"somebody else is primary". So `main` took the `!app.isPrimary()` branch, tried to
hand its arguments to a primary that does not exist, and returned 0 - no window,
and nothing printed, because the one log line goes to the log file rather than the
terminal somebody is watching. That is exactly the reported "Qt/xcb platform
initializes successfully, then immediately calls `exit_group(0)`".

Two changes, `desktop-apps`:

- `initSocket` falls back to 127.0.0.1 when the uid-derived address is not present
  on this host's loopback. Inside `initSocket` rather than in its callers, so the
  receiver and the sender cannot end up on different addresses. It costs per-user
  separation on such a host - one shared instance, as it was before the unique
  address was introduced in 2024 - which is much better than not starting.
  `EADDRINUSE` is untouched, so a genuine second instance is still secondary.
- `main` no longer returns 0 when it is told it is not primary but no primary
  answers. It says so on stderr and starts normally. A second window is a visible,
  recoverable outcome; a silent exit is neither.

`fork-fix-tests/issue-2434-loopback-bind/` extracts the real `initSocket`,
`inetAddrFromUserId` and `addr_not_available` by brace matching and binds for real.
It has to resolve the `_WIN32` branches before matching, because `initSocket` opens
a brace inside `#ifdef _WIN32` and another inside its `#else` while closing only
one. **macOS has the same single-address loopback as FreeBSD**, so the host running
the test reproduces the condition rather than simulating it - on this machine uid
501 maps to 127.254.13.1 and gets `EADDRNOTAVAIL`. It checks that a first instance
becomes primary, that a second stays secondary with `EADDRINUSE` (the fallback must
not manufacture two primaries), and that `use_unique_addr=false` is unchanged.
`BASELINE=1` fails on the first two.

**Caveat, stated rather than papered over:** this does not explain the reporter's
claim that 9.2 worked and 9.4 does not. The unique-address scheme dates to
`464590931` (2024-03-01), before both releases, so if this is their fault then 9.2
should have failed too. Either something else in their environment changed, or
there is a second cause still to find. The defect fixed here is real on its own
merits and produces precisely this symptom.

### #2445 - "the procedure entry point ... could not be located in ooxmlsignature.dll"

**Not a defect in our source.** The mangled name in the reporter's dialog,
`?Encode@CBase64Converter@NSFile@@SA_NPEAEHAEAPEADAEAHK@Z`, carries `PEAE` for
its first parameter - a non-const `BYTE*`. core commit `a84491cf74` ("Fix param
type", 2025-07-10) changed `CBase64Converter::Encode`'s first parameter to
`const BYTE*`, which changes the mangled name. So the `ooxmlsignature.dll` in
that 9.4.0 install was built against a header older than the `kernel.dll` shipped
beside it, and the loader refused the import at startup.

Our own build is consistent, checked rather than assumed: `kernel` exports
`__ZN6NSFile16CBase64Converter6EncodeEPKhiRPcRim` (`PKh`, const), the
`ooxmlsignature` we build imports exactly that, and no module in the payload
imports the stale non-const form.

**What was missing is anything that would have noticed**, and that is worth
having in a fork that ships binaries: this whole class fails at launch, on the
user's machine, with a dialog and an exit. `build_tools/scripts/check_symbol_closure.py`
walks the finished payload, collects what each module imports and what the
payload as a whole exports, and reports any import belonging to one of *our own*
namespaces that nothing in the payload defines. Restricting it to our namespaces
is what keeps it quiet - libc, libstdc++, Qt, ICU and the system frameworks are
resolved from outside the payload and are not its business. It reads symbol
tables rather than linking, so `deploy_desktop.py` prints its result and does not
fail the build; run the script directly for a non-zero exit in CI. On the real
9.4 mac payload it clears 27 modules and 13,921 exported symbols in about four
seconds.

`fork-fix-tests/issue-2445-symbol-closure/` builds both halves of the mismatch
for real with clang++ - one library exporting the const signature, one importing
the pre-a84491cf74 non-const one - and checks that the script fails on the stale
pairing and passes once the importer is rebuilt.

### #2355 - Save As closes the whole application when a folder holds an emoji file name

Same defect as #2136, and closed by that fix. The reporter's account matches it
exactly: the dialog paints for about a second and the process disappears with no
error, no freeze prompt and no crash dialog - which is what a `SIGSEGV` while GTK
paints a file name looks like from the outside.

The maintainer's reply on the thread attributes it to a non-standard system font
and asks whether `segoe-ui-linux` is installed; the reporter confirmed it is not.
That does not rule this out, because the font is only the *trigger*, not the
mechanism. The mechanism is that `libgraphics.so` exported its bundled FreeType
2.10.4, so cairo and pango bound their `FT_*` calls to it, and the COLRv1 colour
glyph API that arrived in FreeType 2.11 is absent from that copy - so an emoji's
colour path fell through to the system FreeType, which then read a face laid out
by 2.10.4. Any font that routes the name down the colour path will do it; Segoe
UI is simply the one the maintainer reproduced with. See the #2136 entry below
for the full account and the runnable demonstration.

`core/DesktopEditor/graphics/pro/graphics.version` localises `FT_*`, `ft_*`,
`hb_*`, `_hb_*` and `Brotli*`, and `graphics.pro` applies it under
`core_linux:graphics_dynamic_library` - both #2136 and #2355 are Linux. Not
verified against this reporter's own font set, which was not reproduced here.

### #2368 - text duplicated and merged with the wrong font after save and reopen

**The reported symptom does not reproduce here, and the attached file cannot
show it.** `2026JUN-20-ECID-T-la208602-nicolas.docx` is the *already damaged*
file, not an input that produces damage. Round-tripping it through our shipped
x2t (`broken.docx -> Editor.bin -> out.docx`, formats 8193 then 65) is
text-lossless: 14 text-bearing parts, 1835 `w:t` runs and 94,744 characters on
both sides, zero differing runs, and the duplication profile is unchanged (66
long runs repeated, maximum multiplicity 7). So x2t reads and writes this file
faithfully; whatever produced the damage is upstream of it, in the editor.

*A caution for whoever picks this up:* a first pass here measured "550
characters lost" in that round trip. That was an artifact of matching `<w:t`
with `<w:t[^>]*>`, which also matches `<w:tab .../>` - it was counting tab
markup as text. The round trip loses nothing.

**What the file does show.** The damaged region is paragraphs 59-64 of
`word/document.xml`: three paragraphs repeated verbatim, the two copies
carrying different `w:pPr` (the first has no `w:jc` and an empty `w:rPr`, the
second `w:jc="left"` with `bCs`/`i`/`highlight`). That is the maintainer's "two
different revisions of the same paragraphs saved side by side". Their
`w14:paraId`s are revealing: the second copy's first paragraph has a fresh id
while the other two reuse the ids of the originals - exactly the shape a paste
leaves, where the first pasted paragraph merges into the paragraph at the caret
and the rest are inserted whole. It is structurally indistinguishable from a
paste of the three preceding paragraphs. That is a hint about the origin, not a
proof of a code path, and no repro was found.

**A real defect was found on the way, and is fixed** - separately, and it does
*not* explain the symptom above. `w14:paraId` must be unique within a document
(`ST_LongHexNumber`; Word keys co-authoring on it). The file carries six
duplicated ids, one of them on five paragraphs. They are not chance: ids come
from `AscCommon.CreateDurableId()`, a random 31-bit value, so 1167 ids collide
with probability ~0.0003. They come from the clipboard: the paragraph writer
emits `c_oSerParType.ParaID` (`sdkjs/word/Editor/Serialize2.js:5444`) and
`ReadParagraph` restores it with `SetParaId` (same file, ~:11626), so pasting a
paragraph or a table row inside one document leaves two paragraphs holding one
id. Three of the duplicate groups here are a copied table column whose cells
hold *different* text under one id, which is what confirms copy/paste rather
than content duplication as the source.

Fixed on the write side rather than the paste side, so it holds no matter how a
duplicate arose (paste, undo, plugin, the `SetParaId` builder API): the
paragraph writer now keeps a `usedParaIds` set on `DocSaveParams` and renumbers
a repeat claimant, which is the same thing `BinaryCommentsTableWriter` already
does for comment durable ids (`Serialize2.js:7172-7177`). The first paragraph to
claim an id keeps it; a document with no duplicates is written unchanged.
`fork-fix-tests/issue-2368-duplicate-paraid-test.js` extracts the real writer
block and the real `DocSaveParams` constructor by brace matching and drives
them over the id sequence from the reporter's file; `BASELINE=1` fails on it.

**If anyone reproduces the duplication itself:** it happens only after close and
reopen, per the reporter, but the maintainer confirmed the corruption is
physically in the saved docx - so reopening reveals it rather than causing it.
Both reporters were using the Zotero plugin and had done a bibliography refresh,
which drives many programmatic edits at once through the plugin API. That, and
the paste-shaped signature above, is where to look first.


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

**Demonstrated**, not just argued: `fork-fix-tests/issue-2490-freetype-export-gaps/` (an earlier note named an `issue-2136-emoji-folder-crash/` test that was never committed; this one checks the same version script against the real exported symbol set)
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

**Fixed** in `core` 382bf81452: `graphics/pro/graphics.version` localises `FT_*`,
`ft_*`, `hb_*`, `_hb_*` and `Brotli*`, applied on Linux for the shared build. A hide
list rather than an export whitelist, deliberately: the public surface is large and
enumerating it risks hiding something a caller needs, whereas missing a prefix here
only leaves it as exposed as it already was. `run.sh` now builds its third variant
from that file rather than a hand-written list, so the demonstration exercises the
artifact: as shipped the emoji name dies with SIGSEGV, with the hide list it exits 0.

**Still owed on a Linux box, and not done here:** no ELF linker is available in this
environment, so `-Wl,--version-script` has never been exercised and the script's GNU
syntax is unvalidated. Build it and run
`nm -D --defined-only libgraphics.so | grep -c ' T FT_'` - it must print 0 - then the
reporter's repro. Also still open: `desktop-apps/win-linux/defaults.pri:194`'s
`-Wl,-unresolved-symbols=ignore-in-shared-libs`, which is what lets seams like this
pass unnoticed at link time.


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

### #1672 - saving a pptx as PDF includes hidden slides - FIXED 2026-11-10
Localised and fixed: `asc_nativeGetPDF` (x2t/doctrenderer, so the desktop's Save as PDF) and the
desktop branch of `asc_nativePrint` drew every slide; only the slideshow and the web
`ToRendererPart` honoured `show="0"`. New `getSlidesToPrint` in `sdkjs/slide/api.js`. A 10-slide
deck with 2 hidden slides: 10 pages before, 8 after, through the app bundle's own x2t. Still open:
the print preview shows hidden slides. See the Fixed table.

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

### #2031 - the Windows installer ignores the file-association selection - EXE FIXED 2026-11-10
Inno: `DoPostInstall` honoured `isAssociateExtension`, but `AddContextMenuNewItems` (always called)
set the default ProgID of .docx/.pptx/.xlsx/.pdf on Windows 10/11 unconditionally, in HKLM and over
an existing HKCU value. Now gated on the user's choice; ShellNew keys still written. Proven by
compiling the real script with ISCC under Wine and reading the registry back (fork-fix-tests/
issue-2031-installer-assoc-selection). Trade-off: an unticked type loses its "New" menu entry.
Still open: `association.cpp:159-181` offers every extension at first launch, and the page's
"Associate selected" pre-ticks every box.

**MSI (`package/advinst/DesktopEditors.aip`) - triaged, no patch.** The .<ext> writes are
feature-gated correctly (e.g. reg_fa_ext__docx in feature FA_DOCX), but feature selection never
follows the dialog: FA_* are Level=4 raised by Condition rows `REGISTER_<EXT> = 1`, evaluated only at
CostFinalize, before FileAssociationsCustomDlg changes REGISTER_*; Next fires only NewDialog (no
AddLocal/Remove), and REGISTER_* are not in SecureCustomProperties. Fix shape: per-feature
Remove/AddLocal ControlEvents on Next plus SecureCustomProperties; needs Advanced Installer and
Windows. The .aip was never Ration-renamed, so the fork does not ship this MSI today.

### #2529 - formula bar: Ctrl+A, Ctrl+V over a long formula pastes a list of references
The reporter (10.0, Windows) retested on a reduced synthetic workbook and could not reproduce it, nor
could the assignee; there is no sample file. In our code the formula-bar paste is native:
`asc_IsFocus()` is false while `cellEditor.isTopLineActive` (cell/api.js:4341), so clipboard_base
`_private_onpaste` returns early, the textarea pastes by itself, and `_onInputTextArea`
(CellEditorView.js:3297) calls `replaceText(0, end, input.value)`. In cell-edit mode copy writes plain
text only (cell/model/clipboard.js:327). Nothing on either path emits references one per line.
Parked until a file is attached.

### #2551 - sheet content and headers go blank until a new sheet is added (Windows, 10.0)
No reproduction steps, Windows only. Row/column headers vanish too, so the whole worksheet canvas is
blank while the model is intact; adding a sheet forces `wb.showWorksheet()` -> `drawWorksheet()`, a
full repaint, which brings it back. Most likely a lost 2D canvas context in Chromium on Windows (GPU
reset, sleep/resume, RDP, display change): sdkjs has no `contextlost`/`contextrestored` handling in
cell/ or common/. Candidate fix: on `contextrestored` of the worksheet canvases call
`wb.showWorksheet()`. Not committed - cannot be verified without a Windows reproduction.

### #2490 - segfault in the GTK file chooser when a name contains an emoji (Linux)
Same defect as #2136 (and #2355/#2394), closed by core 382bf81452's `graphics.version`: the reporter's
account (190 exported FT_* from the bundled FreeType 2.10.4, cairo binding to it on the colour-glyph
path) is exactly that one. zlib and the static heif/de265/x265 are already hidden on Linux by
base.pri's -fvisibility=hidden and --exclude-libs,ALL; FreeType escapes them only through FT_EXPORT's
explicit default visibility. The remaining gap - FreeType names outside the FT_* glob (15 FTC_*,
TT_New_Context, TT_RunIns) - is now localised too (core, #2490 commit; test
fork-fix-tests/issue-2490-freetype-export-gaps). Not verified on a real Linux link.

### #2523 / #2532 - Linux: opening a file while Desktop Editors is running does nothing (exit 0)
Our single-instance path is identical to v10.0.0.176 (platform_linux/singleapplication.cpp,
update-daemon csocket.cpp, main.cpp's `!app.isPrimary()` block, the `receivedMessage` handler), so this
is not a v10 regression. The second process sends a UDP datagram to 127.<uid>.1:13012 (matches the
strace in #2532); `sendMessage()` succeeds whenever anything is bound there, and main.cpp returns 0 -
the datagram is never acknowledged. The primary closes that port only in ~SingleApplication, at the very
end of main(), after app.exec(), CloseApplication() and CefShutdown. A process that is shutting down or
stuck in shutdown (#2523: resident, no windows) still owns the port; its CSocket thread receives the
path and queues it to an event loop that never runs again. Measured with the real csocket.cpp on macOS:
`sendMessage()=1`, datagram delivered to the dying primary, no window. `DestroyCefView(-1)` waiting on a
browser that never closes, or `launchAppClose()` declining to quit
(cascapplicationmanagerwrapper.cpp:1640-1664, 655-695), give the same silence.
No quick fix: releasing the port early lets a second primary start beside the dying one, sharing
cache_path, and the old process's `EndTmpDirectory()` deletes `<cache>/work_temp` under the new one's x2t.
Next steps: a backtrace of the resident process on Linux; an acknowledgement on the instance message so
an unanswered second launch reports to stderr and exits non-zero. Separately (FIXED, desktop-apps #2523 commit): a relative path was resolved
against the primary's working directory, not the caller's (`QDir::current()` in handleInputCmd,
cascapplicationmanagerwrapper.cpp:~1122) - not the cause here (both reporters use absolute paths).

### #2485 - GETPIVOTDATA is not recalculated after refreshing a Pivot Table
Not reproduced in our tree. Ran the real sdkjs headlessly in docbuilder: build pivot -> GETPIVOTDATA on
another sheet (plain, and inside IF(ISERROR(..)) as the reporter has it) -> change source ->
Api.RefreshAllPivots() -> read. Covered date grouping by months/quarters/years+months/years+quarters
(the "Datum";4 case), two pivots on one sheet, a page filter, field headers off, and xlsx save+reopen.
Every case updated (e.g. GPD 7000 -> 103999). Our pivot code is identical to upstream release/v9.4.0,
which the reporter runs. Why it works: the formula listens to its anchor cell, and
Worksheet.updatePivotTable (cell/model/Workbook.js:10869) clears the report range with cleanAll and
rewrites it, which marks that cell changed. A recalculation lock left on by an exception gives stale
values too, but re-entering the formula then goes blank, and the reporter says re-entering fixes it.
The reporter's file went to ONLYOFFICE privately; parked until we have one.
Latent, now FIXED (sdkjs #2485 commit; fork-fix-tests/issue-2485-pivot-recalc-lock-test.js): the pivot refresh
paths in cell/api.js took the recalculation lock without try/finally (asc_refreshAllPivots :7692/:7706, _changePivotWithLockExt :7771-7773,
_changePivotAndConnectedByPivotCacheWithLock :7809-7811) - a throw there would freeze recalculation for
the session, the #2443 failure mode.

### #2512 - PDF export fails ("This file cannot be saved or created") when a print area is defined
Not present in our code. x2t + doctrenderer on our sdkjs: xlsx->pdf and Editor.bin->pdf succeed with a
print area (Sheet1!$A$1; and a 3-sheet workbook with 'Blatt N'!$A$1:$B$3 each), with no JSON params and
with desktop-style m_sJsonParams (spreadsheetLayout.sheetsProps[*].pageSetup.printArea). The PDFs hold
only the print-area cells. The reporter's standalone-x2t "TypeError ... fatal V8" is what x2t prints with
no AllFonts.js, so it proves nothing. All three commenters fixed it by deleting ~/.local/share/onlyoffice
and ~/.config/onlyoffice: stale app data from an older version. Linux 10.0-only; nothing to fix.

### #2545 - TEXT(A1;"ГГГГ-ДД-ММ ччммсс") returns garbage (10.0, Russian locale)
The 10.0 regression is not in our tree: x2t with LCID 1049 gives TEXT(A1,"ГГГГ-ДД-ММ ччммсс") ->
"2026-31-10 125333" (ДД-ММ is day then month) and "ГГГГ-ММ-ДД чч:мм:сс" -> "2026-10-31 12:53:33". Codes come
from ParseLocalFormatSymbol (common/NumFormat.js). Running it found a separate, older defect: uppercase
"СС" (seconds) was the Latin C in that table, so "ЧЧ:ММ:СС" gave "12:53:С С". Fixed (sdkjs, #2545 commit;
test fork-fix-tests/issue-2545-ru-seconds-symbol-test.js).

### #2525 - AI-inserted text disappears after saving DOCX (10.0)
Not present in our tree. The 10.0 AI plugin streams generated text through the plugin method
InsertStreamedContent plus Enterprise "GroupActions"; neither exists in any public sdkjs (upstream
removed InsertStreamedContent in 5dde32b68f; group actions are stubs, common/apiBase.js:6092), so the
visible-but-unsaved behaviour lives in closed code. Every insertion path our build does have was run
through a headless editor and the real desktop save (changes0.json replayed by x2t): PasteHtml with
tables, PasteText, ReplaceTextSmart, callCommand builder Push/InsertContent, and the old public
InsertStreamedContent - all survive save and TXT export.
Side finding, now FIXED (sdkjs #2525 commit, InsertStreamedContent and word group actions restored;
fork-fix-tests/issue-2525-ai-streamed-insert-test.js): because the method was missing, the plugin's streaming generateDocx
inserted nothing in Ration Docs (common/plugins.js:1684 ignores unknown methods). Making it work means
restoring InsertStreamedContent and removing the previous partial chunk, which upstream does with the
Enterprise group actions.

### #2456 - 'Copy Style' from/within table cells loses the font
Cannot reproduce in our code. Format painter copies GetDirectTextPr and applies it via
Paragraph.PasteFormatting -> ParaRun.Apply_Pr/Set_RFonts2, with no table-specific loss of RFonts.
Driven in a headless editor: text and cell-selection sources, cursor-only source, selected and
click targets, cell->cell / cell->text / text->cell - font, size and bold all carried over. Upstream
could not reproduce on 10.0 either. Needs the reporter's file.

### #2460 - filling a form: clicking a Signature field does nothing
Not a bug in the fixable sense: in our 9.4 tree signature fields are an unimplemented stub.
sdkjs/pdf/src/forms/signature.js:83-86 - CSignatureField.onMouseDown/onMouseUp are empty, Draw/SetValue
are no-ops; document.js:1735 excludes signature fields from the form-focus path. Upstream v10.0.0.176
signature.js is byte-identical: the 10.0 "signature dialog" is a new feature built on push-button fields
tagged isOOSignature (pushbutton.js IsOOSignature / asc_OnShowSignature -> asc_onShowFieldSignature,
handled in web-apps pdfeditor DocumentHolderExt.js and forms ApplicationController.js), created by the
editor's own CreateSignatureField. None of that exists in 9.4, and even in 10.0 a real AcroForm /FT /Sig
field from a third-party PDF still does nothing; signing one needs a PKCS#7 signing service.
Backporting means taking the whole v10 signature feature (sdkjs + web-apps dialog).

### #2496 - spelling language detection not being saved
10.0-only; not in our tree. The 10.0 start page was rewritten (desktop-apps v10.0.0.176
common/loginpage/src/routes/settings/general/index.jsx:83): it offers auto/enabled/disabled and sends
`spellcheckdetect: "disabled"`, but the native side accepts only "off" (win-linux
cascapplicationmanagerwrapper.cpp maps anything else to "default"; macOS ASCEventsController to "1"), so
"Disabled" is stored as Auto and keyboard retagging stays on - upstream bug 84571. That is also why
"Disabled" did nothing for the #2543 and #2503 reporters on 10.0. Our 9.4 panelsettings.js:265 sends
auto/off, which matches. fork-fix-tests/issue-2543-spellcheck-detect-off-live step 2b shows
`<spell-check-input-mode>0</spell-check-input-mode>` written and read back. The remaining 9.4 defect -
open documents not told - is fixed under #2543. If we ever take the 10.0 start page, map "disabled" to "off".
Correction to the #2337 note: retagging is not only on a space - CDocument EnterText sets
CheckLanguageOnTextAdd for every letter typed (sdkjs/word/Editor/Document.js:10191).

### #2453 - red underline cannot be removed
Not a formatting underline. The attached deck has no `u=` anywhere in slide, layouts or master. The line
under "Let’s" is the spell-check mark: the run is `<a:rPr lang="de-CH">`, an English word tagged Swiss
German (hunspell de_CH flags "Let", en_US accepts it). Set the text language to English in the status
bar, use Ignore, or turn spell checking off. By design.

### #2459 - Onlyoffice crashes while editing the file - PARTLY FIXED, reporter's trigger unknown
Spreadsheet editor. The screencast shows a table (style, totals row, two-line headers, conditional
fills) copied from a "Stundenzettel" xlsx and pasted into a new workbook; EditingError ("Speichern
als...") follows within seconds. The source file never reached the issue. In a headless cell-sdk harness
the same paste into a new workbook, then clicks, column resize, undo/redo, autosave and change saving,
raised nothing. Pasting into a workbook WITHOUT a styles part did crash (`Font.isNormalXfColor`, null
Normal font, cell/model/WorkbookElems.js) - fixed (sdkjs, #2459 commit; test
fork-fix-tests/issue-2459-normal-font-null-test.js). The reporter's target has a styles part, so their
trigger is still unknown; needs the original file.
Seen in the harness, since FIXED (sdkjs #2459 commits): a pasted cross-sheet VLOOKUP kept its original row
(since fixed further: a sheet missing in the target becomes an external reference to the source workbook, as in Excel); a table column name
with `[ ] # ' @` raised FrmlAnotherParsingError (-305). Pasted structured references showing #NAME? did not
reproduce once formulas are stored as Excel writes them (Table1[[#This Row],[Col]]); what was seen came from
the UI shorthand stored in a test file, from the `[` bug, and from cells depending on the VLOOKUP case.
Also fixed since: autocomplete inserts escaped column names; a pasted table keeps its totals row when the
source omits showColumnStripes; redo keeps the totals label; table refs never saved with `$` (and healed on
open); totals-row toggles and row deletes keep autoFilter/sortState on the data rows, and deleting rows past
a table's end removes its totals row instead of overwriting the last data row.
Since fixed too (2026-11-05): a sort writes its sortState and sortCondition over the data rows only, a second
sort keeps the full-width sortState, conditions follow row/column inserts and deletes, resizes and header
toggles (a resize that removes the sorted column drops its condition; undo restores it), and asking for a
totals/header row the table already has is a no-op instead of growing the table.

### #2452 - textbox does not fit text
"Go!" (Textfeld 8) has spAutoFit, 110 pt text and exact line spacing 57.99 pt. Its saved height (828399
EMU = one 57.99 pt line + 3.6 pt insets) is how PowerPoint autofits, and we keep the same box. With
exact spacing below the font size the glyphs overflow the line box (Recalculate_LineGap, linerule_Exact,
scales ascent/descent down), and "Geomanist Black" is substituted. The box size is not a bug; only the
vertical position of the overflowing text could differ from PowerPoint, which needs a PowerPoint check
first. (The slideshow clipping of such text is fixed under #2554.)

### #2502 - font size all over the place in presentations - PARTLY BY DESIGN
Fixed: deleting all text in a shape replaced the paragraph with a fresh one, so typed text fell back to
the list-style default size and lost bullets/spacing, and an emptied paragraph saved its end-run size
(sdkjs, #2502 commit). By design: "set 30 pt, shows 27 pt" is the shape's normAutofit shrinking text to fit.

## Latent problems found in passing, not yet fixed

### xlsb error cells and non-BMP text (found 2026-11-13, agent fy) - not fixed
Error cells: WriteCell (BinaryWriterS.cpp:6127-6150) writes error codes but sdkjs Serialize.js:12410 reads an Error cell's value
as a shared-string index - xlsb #DIV/0!/#N/A open blank, xlsx base64-bin errors show the first shared string; the C++ reader
(BinaryReaderS.cpp:7177) expects codes, so the encoding needs a decision. Non-BMP text: pole.h convertWStringToUtf16 sizes by
UTF-32 length (drops a trailing char per emoji on write) and convertUtf16ToWString returns trailing NULs on read; BiffString cch
is in UTF-32 units - wide blast radius (DOC/PPT/VBA). Minor: WsProp GETBIT(flags2,16) on a BYTE; CFFlag uses long.

### PPT -> PPTX writes OLE objects as external links into x2t's temp folder (found 2026-11-13, agent ex) - being fixed (fm)
Seen on POI 41246-1.ppt and others: TargetMode="External" relationships pointing at the temp dir - leaks a local path, broken link.

### Latent-problem entries reviewed 2026-11-13 (agent ey) and not fixed
CLocalFileLocker uninitialised pointer - already fixed (constructor sets m_pLocker = NULL). cefview forwards only x2t codes
89/90/91 (93 never shown) - about a day across three submodules. Font collection judged by face 0 (ApplicationFonts.cpp:1138)
- no real trigger here; needs a FreeType harness and a bitmap-first .ttc. character.js:141 binary search over an unsorted
array - only loses a cache hit. Paragraph 0.01 mm past the page bottom - layout-engine risk, no page-count change.

### Converter fuzz crashes from the 2026-11-13 corpus pass - not fixed yet (RD candidates)
LibreOffice ww6 ofz21385-1.doc wild memmove in VMLPictureMapping::CopyPicture; ww8 forcepoint50-grfanchor-1.doc NULL in
DocumentMapping::writeRun; ww8 ofz57592-1.doc FooterMapping::Apply on empty AllPapxFkps; memory blowups ww6 hang-1,
crash-4, crash-7 and ww8 hang-1.doc; POI HWPF/HSLF clusterfuzz files, Fuzzed.doc, 57272_corrupted_usereditatom.ppt;
ASan heap over-reads in PropertyExceptions::ReadExceptions and StyleSheetInformation. ww6 crash-3.doc runs out of
memory after RD-0021.

**An ODS-round-tripped form control lands at a nonsense row.** `controlPr/anchor`
comes back as `<xdr:row>18446744071562068031</xdr:row>` - an unsigned underflow.
Present on the pre-fix binary too, so it is not from the #2187 work; found while
testing it. A Button that survives the round trip is therefore placed somewhere
absurd.

**`GraphicFrame` (chart) `@macro` is still dropped on ODS.**
`PPTXFormat/Logic/GraphicFrame.h:104` has the field and the same one-line hook
used for Shape/Pic/CxnSp in #2187 would work, but the fixture does not cover it and
it could not be demonstrated, so it was left rather than changed on spec.

**`draw_frame::serialize` writes `office:event-listeners` before the frame
content**, where ODF's RNG puts it last. Pre-existing, on a live path (pptx shape
hyperlinks through `start_action`), and LibreOffice's importer is order-tolerant -
deliberately not changed while fixing #2187. Worth a look if strict ODF validation
ever matters.


**`docbuilder` aborts instead of reporting a failed open.** When x2t is not
reachable, `CV8RealTimeWorker::OpenFile` (`core/DesktopEditor/doctrenderer/docbuilder_p.cpp:347`)
still calls `NativeOpenFileData`, and `CJSObjectJSC::call_func`
(`js_internal/jsc/jsc_base.h:196`) does `[arr addObject:_val->value]` with a nil
`JSValue` - `NSInvalidArgumentException`, SIGABRT. It cost an agent an hour of
this session. Driving the real sdkjs headlessly through docbuilder is how two
fixes this week were verified, so this is worth fixing.

**`harness/bin/run-editor.sh` cannot attach to the bundle in `desktop-apps/build`.**
That bundle's `ascdocumentscore.framework` is from 08:22 on 12 September; the
remote-debugging fix landed at 09:02 the same day. No CDP endpoint ever appears,
and a second agent independently lost time to the same thing. The harness README's
"Verified" note is stale for that bundle. Related to the stale-converter problem
already fixed in `rd_x2t`: the bundle is old in more ways than one.

**A paragraph that does not fit is still placed on the page it does not fit on,**
at 0.01mm, which lets a table's bottom reach 272.10 against a `YLimit` of 272.01 -
0.09mm past the bottom margin. Does not change page count. Found while measuring
#1570.

**Rendering to PDF works - and the note that used to sit here was wrong.** It said
the PDF render path was broken because doctrenderer failed with
`ReferenceError: Can't find variable: $`. That was a symptom recorded as a defect.

The real cause: doctrenderer reads `DoctRenderer.config` from the process directory
and resolves `../editors/sdkjs/...` against it. The packaged app has that tree;
`core/build/bin/<plat>/x2t` does not. Give the fresh binary a config and an
`editors` symlink and all three formats render - `sample.docx` 551KB,
`sample.pptx` 306KB, a small xlsx 11KB. Nothing in the renderer is broken.

`harness/bin/x2t.sh` now sets this up automatically, so anything that renders works
through the harness without ceremony. **But note what the JS is:** the editors tree
is the packaged app's, dated 11 September, so a **C++ fix shows through this path
and a JS fix does not** until that tree is refreshed. `RD_EDITORS` points it
elsewhere.

**A trap worth knowing:** `desktop-apps/common/converter/DoctRenderer.config` is
stale and unused. It carries the old per-product `<DoctSdk>`/`<PpttSdk>`/`<XlstSdk>`
schema; doctrenderer now reads `<sdkjs>`, `<allfonts>` and `<dictionaries>`. Copying
that file next to a binary produces a converter that loads nothing and fails with
exactly the `$` error above - which is how the original misdiagnosis happened.
Packaging does **not** use it (both `build_tools/out` and the macOS vendor copy
carry the correct 338-byte version), so this is not a shipping defect - just a file
in the tree that looks authoritative and is not.


**A font collection is accepted or rejected on the strength of its first face
alone.** `core/DesktopEditor/fontengine/ApplicationFonts.cpp:1138-1148` opens face
index **0**, tests `FT_FACE_FLAG_SCALABLE` on it, and `return`s for the whole file
- all of this *before* the `for (nIndexFace...)` loop that enumerates the
collection. The check belongs inside that loop. It cuts both ways: a `.ttc` whose
first face is bitmap-only loses every font in it, and a non-scalable face later in
a collection is admitted with `units_per_EM == 0`. All 128 font collections on this
machine were scanned; only `Apple Color Emoji.ttc` trips it, and there both faces
are non-scalable, so there is no demonstrable real-world trigger today. Found while
root-causing #1343 and left alone rather than change shared font code for a
synthetic case - but the asymmetry is a genuine defect and worth a proper fix with
a real collection to test against.

**`character.js:141` binary-searches an unsorted array.** `this.UsedRanges` is
built by `push` in discovery order. Harmless today only because the caller
re-searches the sorted full list on a miss and range-checks the result before
returning it, so it can lose a cache hit but never return a wrong font.

**`ApplicationFontsWorker.cpp:1123` is off by one**, writing the final range's end
as `nMaxSymbol - 1` (0x10FFFE) where the loop covers through 0x10FFFF. Affects only
U+10FFFF, a noncharacter.

**Confirmed working, recorded so nobody re-derives it:** the #2433 charmap fix is
doing its job. Validating all 4437 generated ranges against the real fonts (7635
probes) misses 49, every one at an unassigned code point, a block boundary or PUA.
The same check against the *shipped* `AllFonts.js`, generated before that fix,
misses 657 - 542 of them `Heiti TC`/`Heiti SC` claiming Big5-derived ranges.


**x2t hitting its own 4GiB cap - NOW REPORTED, not fatal.** `765213f176` wraps
`main` so a `bad_alloc` returns `AVS_FILEUTILS_ERROR_CONVERT_LIMITS` (93) instead
of reaching `terminate` and dying on SIGABRT. 93 rather than 96 because
`SUCCEEDED_X2T` counts `CELLLIMITS` as *success* - returning 96 would have
reported running out of memory as a successful conversion.

**Still open, and needed for this to matter to a desktop user:** `cefview.cpp`
forwards only x2t open errors 89, 90 and 91 to the renderer. Everything else falls
through to `LocalFile_End()`, which discards `m_nLocalFileOpenError`, so 93 is
currently only visible to a CLI or server caller. That is a small change in
`desktop-sdk` and it is the missing half of this fix.

**The cap itself is unchanged and still parked** - raising or removing it is a
product decision. What follows is why it is reached so easily:

**x2t caps itself at 4GiB and cannot survive hitting the cap.** This is the other
half of #1359, and it is the half that explains the reporter's own 85MB file.
`core/X2tConverter/src/main.cpp:101` applies `X2T_MEMORY_LIMIT` (default 4GiB)
through `setrlimit(RLIMIT_DATA)`. The CSV reader materialises the whole workbook
before writing anything, at roughly **120x the input size** - measured here:
968KB to 152MB, 4.2MB to 504MB, 8.5MB to 982MB, 35.5MB to 2.7GB. There is **no
`try`/`catch` and no `set_new_handler` anywhere in x2t**, so the `bad_alloc` goes
straight to `terminate` and the editor shows its generic failure dialog.

That puts the cliff between the reporter's 9.5MB file, which opens, and their
35.6MB one, which does not - on Linux and Windows. It is invisible on this machine
because `RLIMIT_DATA` is a no-op on macOS, which was confirmed rather than assumed
(`X2T_MEMORY_LIMIT=256MiB` changes nothing here).

**This corrects an earlier note in this file**, under #1297, which said there was
no memory cliff. There is one; it is self-imposed, and it is why the failure looks
like corruption rather than an out-of-memory error.

Two things would move it, neither done here: raising or removing the rlimit, and
the dead weight below.

**~25-30% of the CSV binary output is written and never read.**
`CSVReader.cpp:216` sets `m_oCacheValue` on every cell and `BinaryWriterS.cpp:6167`
serialises it, but nothing consumes it - `sdkjs/cell/model/Serialize.js` defines
`ValueCache: 7` and its cell reader falls through to `ReadUnknown`, and core's own
`BinaryReaderS.cpp:7201` reads it into a field no writer consults. A 35.5MB CSV
produces a 271MB `Editor.bin`. Not removed: it changes the on-disk binary format,
and on its own it would not lift the 4GiB cliff for the reporter's file.

**The five other subscripts - FIXED, and the claim above was wrong about two of
them.** Landed in `core` as `765213f176`. `File.cpp`'s three sites were genuinely
unguarded and now go through `GetEncodingIndex`; nothing in core calls them, so
that is defence in depth and the test says so rather than inventing a
reproduction. But `TxtFile.cpp:99` and `:197` were **already range-checked**. What
they did instead was route every value outside 0..53 - every Windows code page our
own API documents - into a fallback that ignored the requested encoding, one of
them handing this table's row number 46 to an overload that takes a code page.

And that one **is** reachable, contrary to the earlier attempt that could not fire
it. A windows-1252 `.txt` converted to `.docx` on the pre-fix binary gives exit 0,
a file on disk, and raw 0xE9 bytes inside `word/document.xml` - a part no XML
parser will read. Same shape as #139, and silent.

**The `sep=` tautology - FIXED** in `765213f176`. It only ever bit on Windows,
where `wchar_t` is 2 bytes, when a lone high surrogate preceded a CR or LF in a
file opening with `sep=` - the newline then became part of the delimiter and every
later `<surrogate, newline>` pair split a cell and ate a row break. Proved by
compiling the extracted block both natively and with `-fshort-wchar`: the baseline
passes natively, confirming the change is a no-op off Windows, and fails under
`-fshort-wchar` on exactly the two lone-surrogate cases.


**A styled but empty cell losing its styling, and the missing clamp - BOTH FIXED.**
Landed in `sdkjs` as `ec823d0ce6`. The `getType() !== null` guard now covers only
the value, not the styling, in both the string builder and its DOM twin; the
max-row/col clamp moved into `_getRangeMaxRowCol` so all three copy paths get it.
The `else` turned out to be an optimization rather than a guard - `dc4a593072`,
"[se] Copy table optimization (html)" - and the expensive half of it is kept.
Disclosed cost: a blank `<td>` grows by a constant 61 bytes.

**Still open in the same file:** `_makeNodesFromCellValueStr` opens `<a>` for an
external hyperlink and unconditionally closes `</span>`, producing malformed
markup, and its `getLocation() != null` href branch is unreachable. The DOM twin
gets this right; the string variant was transcribed from it and lost the
distinction, which is the same way the styling bug came to exist in two places.


**The harness preferring a stale converter - FIXED.** Landed as `70aca34`.
`rd_x2t` now prefers `core/build/bin/<plat>/x2t`, the copy a rebuild actually
updates, and `rd_x2t_frameworks` supplies the `DYLD_FRAMEWORK_PATH` that made the
bundle copy seem like the only workable one. The stale bundle stays reachable
through `RD_X2T` and is genuinely useful there - several fixes this week were
proved against it as a pre-fix baseline. A second defect fixed alongside: a csv,
tsv or txt input always failed with code 89, because the harness sent no source
format, encoding or delimiter and x2t refuses to guess them.


**`setup_paths` mutating its captured variable - FIXED.** Landed in `desktop-apps`
as `2edb2ba03`. The lambda now works on a local copy, so it configures the same
directories however often it runs. Left unfixed it was correct only by
coincidence: a second call would have relocated `recover_path`, `cookie_path`,
`fonts_cache_info_path`, `user_plugins_path` and `recents.xml` to `.../data/data/`
and abandoned the user's recovery files with no error.


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

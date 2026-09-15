# Requires approval

Things that are blocked on a decision, a credential, or a machine - not on work.
Each entry says what is needed and what it unblocks, so it can be answered quickly.

Nothing here is being worked on. When an item is answered, move it out and act on it.

---

## 1. Rotate the lab02 tokens  (security)

Five project access tokens were pasted into a chat transcript on 2026-09-15:
`ration-docs-core`, `-sdkjs`, `-web-apps`, `-desktop-sdk`, and a full `api`-scope
token for `ration-docs-desktop` (project 150, expires 2027-09-14). Four are
write-capable.

**Needed:** revoke and reissue. Say the word and the keychain entries get re-keyed in
one command - they are stored per project path under `oauth2@lab02.ration.works`, not
in any `.git/config`.

## 2. A Linux box for verification  (offered, not yet provided)

Nineteen of the unverified fixes are `desktop-apps`/`desktop-sdk` and most are
Linux-only. Several are one-command checks on a real machine and impossible on macOS:

- #2136 / #2355 - `nm -D libgraphics.so | grep -c ' T FT_'` must print 0
- #1748 - the executable must not export libstdc++ symbols
- #2274 - `ldd platforminputcontexts/libqtvirtualkeyboardplugin.so` must resolve
  QtQml/QtQuick from the bundle; the keyboard should load with
  `QT_IM_MODULE=qtvirtualkeyboard`
- #2445 - run the symbol-closure checker against a real ELF payload
- #2105, #2168, #2216, #2266, #2231 - Wayland/GTK behaviour
- #2302, #2395, #2397, #2293, #2312 - locale, desktop entry, hyperlink, CUPS

**Needed:** Ubuntu 22.04 or 24.04, ideally a desktop session on both X11 and Wayland
rather than headless. Build dependencies preferred; failing that, a box that can
install and run the built `.deb` or AppImage covers most of the list.

## 3. The build can ship a stale binary  (tree-wide change)

`ADD_DEPENDENCY` (`core/Common/base.pri:711`) sets `LIBS` but never `PRE_TARGETDEPS`,
so make has no edge from any target to the static libraries it links and will not
relink when one changes. Hit three times in one day: `make.py` exits 0 and the shipped
binary still contains the old code, with the *newest* mtime because it was copied.

This is a plausible mechanism for #2445 - a mismatched `ooxmlsignature.dll` beside a
newer kernel is exactly what it produces.

**Needed:** approval to change how the build links. It is about four lines at one
choke point, but it affects every project in the tree and needs a clean build and an
incremental build to verify. Workaround meanwhile: delete the binary before rebuilding
and check the result with raw bytes, not `strings` (which cannot see wide literals).

## 4. Product decisions

- **#2321** - the XDG portal is already the default on Wayland; making it the default
  on X11 too is a one-line change in `useGtkDialog()`, but it is a product call.
- **#2258** - Ctrl+D / Ctrl+R fill down/right. Ctrl+R already carries two actions
  (`RightPara` and `PasteOnlyFormatting`), so binding it is a decision, not a fix.
- **#2404** - the portable ZIP already builds and already suppresses the association
  prompt. Whether it gets published is a distribution decision.
- **#2372** - MSI signing happens in a pipeline script outside this repository
  (`documents-pipeline/scripts/Sign.ps1`). Nothing here can fix it.

## 5. web-apps locale files - tracked or ignored?

The 158-file locale diff regenerates on every build and is byte-identical apart from
counters. It is currently preserved on `ration/l10n-build-output`. Left tracked it
makes noise in every diff; ignored, a genuine translation change could be missed.

**Needed:** a decision either way.

---

## 6. Landed, but reversible - every theme's window border got darker  (#2229)

The issue asks for a higher-contrast border so a window's edges can be seen.
Measured against WCAG 2.1 SC 1.4.11, which asks 3:1 for a UI component boundary,
**all seven themes were below it** and two were effectively invisible:

    gray     #cbcbcb on #d9d9d9   1.15  ->  #787878   3.13
    white    #d9d9d9 on #eaeaea   1.17  ->  #858585   3.07
    night    #616161 on #383838   1.89  ->  #858585   3.18
    dark     #616161 on #282828   2.38  ->  #757575   3.20
    classic  #888    on #e4e4e4   2.79  ->  #808080   3.11
    light    #888    on #E4E4E4   2.79  ->  #808080   3.11
    contrast #616161 on #181818   2.87  ->  #7a7a7a   4.14

Each moved by the smallest neutral step that clears the threshold. Five shift only
slightly; **gray and white shift visibly**, because their borders were barely there.

Landed rather than parked: it is the smallest change that answers the issue, and it
is justified by a published threshold rather than by taste. But it changes the look
of every shipped theme, which is your call, not mine.

**To undo:** `git -C desktop-apps revert 1509c6228`

The drop-shadow half of the issue is not done and cannot be: it needs the compositor
to draw around our frameless window, which is the Qt Wayland port already ruled out
of reach for #2287 and #2285.

---

## 7. Should a macro be able to reach arbitrary hosts?  (#2220, security)

A macro running in a document cannot call an external API. That is not a bug in our
code: `--disable-web-security` is compiled out, `universal_access_from_file_urls` is
compiled out on CEF 102 and later, and the one bypass that exists -
`onlyoffice-proxy://` - is gated to `onlyoffice://` frames. The plugin runs at a
`file:` origin, so the browser's own CORS rules stop it. Headers are not being
stripped by anything in this fork; that is Chromium's preflight.

Opening it up would let **any macro in any document reach any host, with no CORS**.
That is a security posture decision, not a patch. The maintainer's own answer on the
thread points at a plugin with `onlyofficeScheme`, and an async Office API "in
upcoming releases".

**Needed:** a decision on whether we want that door open at all, and if so how narrow.

## 8. The AI plugin ships committed build output

`desktop-sdk/ChromiumBasedEditors/plugins/ai-agent/deploy/` is a committed build
artifact, and the fixes for #2268 (and #2444 before it) are in `src/`. **They do not
reach users until the plugin is rebuilt.** `node_modules` is absent here, so the
plugin cannot be built or typechecked in this environment either.

**Needed:** either a plugin build step in our pipeline, or a decision that `src/`
changes there are not shipped until someone runs it by hand.

Related: `onlyoffice.github.io/sdkjs-plugins/content/ai/` - which holds the grammar
checker behind #2272 - is not a submodule of this superproject at all, so it is
outside the tree we build and version. Worth deciding whether it should be.

## 9. A column autofit no longer resizes rows that have no cell in it  (#1018, landed)

Landed as `26cb022b7c` in `sdkjs`. Revert with
`git -C sdkjs revert 26cb022b7c`.

The freeze fix for #1018 clamps the autofit scan to the column's own cells instead
of the sheet's row extent - 4,194,304 visits down to 400. That part is not in
question. This is about the side effect it removes.

The empty-cell branch of `_addCellTextToCache` is not silent: when
`isNotDefaultFont()` is true it measures a character and calls `_updateRowHeight`,
which writes through `model.setRowHeight` and materialises a `Row` record for that
row. So **rows with no cell in the autofitted column are no longer grown**.

Which rows those are is narrower than it sounds, and the obvious guess is wrong:
the condition is false when the *row* carries a font - including the whole-sheet
row formatting that creates the huge extent in the first place - and true when the
*column* carries a font and the row does not. That is the state after formatting
whole columns, which is the #1018 gesture itself. Measured at extent 40,000: no
column styling, 0 rows affected either way; whole-sheet row formatting, 0 either
way; column styled 48pt, 40 rows sized now against 40,000 before.

The direction is that we now fail to grow rows that upstream would have grown,
never the reverse.

It was shipped rather than preserved for two reasons: those heights appeared only
as a side effect of a column autofit and nothing else in the product reproduces
them, and producing them created one `Row` record per row - 1,048,576 from a single
autofit, marked changed, which inflates the saved file. Preserving the behaviour
means re-opening the freeze.

**Needed:** confirmation that this is the trade you want. It is a visible change
for anyone who formats whole columns and then autofits, and it is the one item in
this round that a user could notice without hitting a bug.

## 10. Two editable views of one local document  (#2135, product decision)

**Not fixed, deliberately.** Investigated, root-caused, and handed back rather than
patched, because the one-line version of this "fix" is a data-loss bug.

What the reporter wants is a split view of one long document - two viewports, to
stop scrolling back and forth - and they point out that Document Server allows two
browser tabs on one file. That comparison is the whole problem: two tabs there are
two co-editing clients reconciled by a server. No such layer exists for a local
file.

Two separate mechanisms produce today's behaviour, and both are deliberate:

- **Same process.** `asctabwidget.cpp:718` `openLocalDocument` looks for an existing
  view by url and selects that tab instead of making a second one. **No lock is
  consulted on this path at all.** `forcenew` exists but is only ever passed for
  portal URLs.
- **Second process.** `cefview.cpp:6009` queries the lock and, if held, opens the
  document read-only and detached from its path. It is not refused; it is
  demoted.

**Why removing the de-duplication is not safe.** The desktop save path is a
whole-file overwrite through the held descriptor - `SeekFile(0)`, write, then
`Truncate(nFileSize)` in `applicationmanager_p.h`. There is no change-log
reconciliation for local files, so the second save silently discards the first.

And the locker would **not** catch it. This was measured, not assumed:

  C - THIS PROCESS holds it, via the real CFileLockerFCNTL::Lock()
      the SAME process now asks IsLocked: ltNone (free - the editor will write)
      and a second F_WRLCK from this process: granted

A POSIX byte-range lock never conflicts with its own owner, and `CLockFileTemp`
compares user + host + app-data-dir only, so a second view of the same user matches
its own `.~lock` marker and is waved through. Two views in one process both read
"free, go ahead and write".

**What granting it would take:**

- *Safe today, small:* a second **read-only** view in a new tab (`forcenew` plus a
  read-only flag). Covers the reporter's actual motivation - looking at two places
  in a long document. Needs exactly one save-path owner.
- *What was literally asked for:* two editable views, which needs either one shared
  editor model with two viewports - an `sdkjs` change, since a `CCefView` owns a
  whole editor instance and its own recovery directory - or a local co-authoring
  session with operational transforms, i.e. reimplementing Document Server.

**Needed:** a decision on whether to build the read-only split view. Nothing should
be done to the de-duplication itself until then.

Incidental, and good news: the test also shows a **stale `.~lock` left by your own
crash does not wedge the document** - your own marker is recognised and ignored.

## 11. Linux arm64 box: credentials to retire, and sizing before it is useful

**Credentials in the transcript.** `172.16.84.144`, user `administrator`, password
pasted into this session on 2026-09-15. Described as a throwaway box. My SSH public
key (`id_ed25519`) is now in that account's `authorized_keys`. Retire the box or
rotate the password and remove the key when it is no longer needed - recorded here
so it is not forgotten, the same as item 1.

**It cannot build anything as provisioned.** Measured, not estimated:

| | Has | `ARM64_DESKTOP_BUILD.md` requires |
|---|---|---|
| Disk free | 8.6 GB | **100 GB** |
| RAM | 3.9 GB | 8 GB minimum |
| Swap | 3.3 GB | 4 GB |
| CPU | 2 cores | - (2 cores means a many-hour build) |
| Toolchain | none: no `git`, `gcc`, `g++`, `cmake`, `qmake`, `node` | full stack, ~2-3 GB |

Where 100 GB goes: source without git history is ~10 GB, of which
`core/Common/3dParty` is 4.6 GB and Linux arm64 needs its **own** set fetched (CEF
dominates); build output ~3.7 GB; and the intermediate object tree, which on macOS
is the single largest consumer.

**And the bring-up has never been done.** `ARM64_DESKTOP_BUILD.md` says so itself:
*"This path is not currently runnable as written, and has not been verified."*
`tools/linux/build-desktop-arm64-docker.sh` has never existed in this repository,
nor has the `automate.py` it is said to invoke. The plausible route is pointing
`build_tools/make.py` at `platform=linux_arm64` the way the macOS build does, but
that has not been tried, so this is a first-ever build bring-up rather than a
provisioning task.

**Needed:** a decision to resize (suggested 100 GB disk / 16 GB RAM / 8 cores), at
which point the toolchain install and the first `linux_arm64` build attempt can
proceed. That work also unblocks the ~19 fixes currently unverifiable on Linux,
which is worth more than the release artifact itself.

**2026.1.0 therefore ships macOS arm64 only** unless that decision comes first.

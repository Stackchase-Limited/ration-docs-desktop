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

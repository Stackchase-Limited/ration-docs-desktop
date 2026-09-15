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

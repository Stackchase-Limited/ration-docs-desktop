# Ration Docs editor harness

Runs the desktop editor with our own `sdkjs` in it, and drives it from Node over
the Chrome DevTools Protocol. The point is to turn "the editor shows *An error
occurred during the work with the document*" into a stack trace.

Most bugs in the upstream tracker cannot be confirmed by reading code alone. The
editor is a CEF browser, so it can be attached to and scripted like any page.

## Why this works, and what the bug was

Debug-info support is enabled by `ascdesktop-support-debug-info-keep` in
`settings.xml` (see `LoadSettings` / `CheckSetting` in
`applicationmanager_p.h`), or by `--ascdesktop-support-debug-info` on the
command line. Two things hang off it:

**F1 opens DevTools.** `OnPreKeyEvent` in `cefview.cpp` calls `ShowDevTools()`
for key code 112 when `GetDebugInfoSupport()` is true.

**Remote debugging was pinned to port 8080 and failed silently.**
`CAscClientAppBrowser::OnBeforeCommandLineProcessing` in `client_app.h`
appended the port as a command-line switch with the value hardcoded:

```cpp
if (m_manager->GetDebugInfoSupport())
    command_line->AppendSwitchWithValue("--remote-debugging-port", "8080");
```

That switch **overrides** `CefSettings.remote_debugging_port`, so
`--remote-debugging-port` could not be honoured - whatever you asked for, CEF
used 8080. And 8080 collides with all sorts of ordinary dev servers. When the
bind fails the DevTools server just does not start, and because `Init_CEF` set
`settings.log_severity = LOGSEVERITY_DISABLE` there was no message anywhere:

```
ERROR:socket_posix.cc(147)] bind() failed: Address already in use (48)
ERROR:devtools_http_handler.cc(309)] Cannot start http server for devtools.
```

Two changes in `desktop-sdk` fix it:

- `client_app.h` supplies the 8080 default only when no port was requested, so
  `--remote-debugging-port=<n>` works.
- `Init_CEF` keeps CEF's own logging at `WARNING` when debug info is requested,
  instead of silencing it. The failure above was invisible for hours; it should
  never be again.

`Init_CEF` also sets `CefSettings.remote_debugging_port`. That is belt and
braces only - the command-line switch wins over it - but it makes the outcome
independent of when the manager happens to read its settings.

Both need a build from this tree. On a build without them, use F1, or free up
port 8080.

### Verified

Verified on 2026-09-12 against a packaged build from this tree, end to end:
`/json` lists an editor page target, `editor-eval.js` evaluates inside it, and
`repros/2418-conditional-formatting.js` produced the stack trace behind #2418.

Getting there turned up three things that all look like a broken build and are
not. Each is now handled by a script, but they are worth knowing:

**The "no window at all" app was never a framework mismatch.** An earlier
attempt swapped a fresh `ascdocumentscore.framework` into an existing bundle and
got an app that launched with no window, which was read as an old-binary /
new-framework mismatch. It is not. `AppDelegate.mm`'s
`applicationDidFinishLaunching` calls `PFMoveToApplicationsFolderIfNecessary`,
and `PFMoveApplication.m` puts up a **modal** "Move to Applications folder?"
alert whenever the bundle is not in an Applications folder - which a bundle in
`desktop-apps/build` never is. Launched from a terminal the alert usually never
gets drawn, so the app sits there alive, foreground, with no window and no CEF
browser. `sample <pid>` shows it plainly, parked in `-[NSAlert runModal]` under
`PFMoveToApplicationsFolderIfNecessary`. LetsMove's own suppression key gets
past it, and `run-editor.sh` sets it:

```sh
defaults write com.stackchase.rationdocs moveToApplicationsFolderAlertSuppress -bool YES
```

**A document must arrive as an Apple Event, not as argv.** `open -a <app>
<file>` opens an editor; a path on the command line does not - the app starts,
shows the start window, and never creates an editor. `run-editor.sh` launches
bare and then sends the document.

**The start window is CEF, not native.** This file used to say the opposite. On
the packaged build `/json` lists `login/index.html` as soon as the app is up,
before any document exists. So an empty `/json` means the app has not finished
starting (or is blocked on the alert above) - it does not mean "no document
open".

One more layout fact matters for scripting: the page target is web-apps'
*wrapper*, `apps/api/documents/index.html`. The editor - and with it `Asc`,
`AscCommon`, `AscCommonExcel` and `Asc.editor` - lives in a child iframe
(`apps/spreadsheeteditor/main/index.html` and friends) which CEF does not expose
as a target of its own. `editor-eval.js` reaches into it; see below.

## Setup

```sh
harness/bin/build-app.sh                      # package a launchable .app
harness/bin/enable-debug.sh                   # once; writes the flag into settings.xml
harness/bin/blank-doc.sh xlsx /tmp/blank.xlsx # the app's "new document" flow is not scriptable
harness/bin/run-editor.sh /tmp/blank.xlsx     # launches, sends the doc, waits for a page target
```

### Packaging the app

`build-app.sh` drives the `ONLYOFFICE-arm` target of
`desktop-apps/macos/ONLYOFFICE.xcodeproj` and writes to `desktop-apps/build`,
which is where `lib/env.sh` looks for `RD_APP`. Signing is ad-hoc, because a dev
machine has no identities; the bundle is for local use only.

Only the Xcode target does the packaging properly: its phases copy the CEF
framework and the three `editors_helper` apps in, rewrite Chromium's load path
from `@executable_path` to `@rpath`, stage `Vendor/ONLYOFFICE` (gitignored) into
`Resources`, and re-sign everything in dependency order. Dropping a framework
into an existing bundle does none of that.

The payload is whatever `build_tools` produced, by default
`build_tools/out/mac_arm64/onlyoffice/desktopeditors`. Two knobs:

| Variable | Meaning |
|---|---|
| `RD_PAYLOAD` | payload to package (default: `build_tools/out/mac_arm64/...`) |
| `RD_BUILD_DIR` | where the `.app` lands (default: `desktop-apps/build`) |
| `RD_TARGET` | Xcode target (default: `ONLYOFFICE-arm`) |

`RD_PAYLOAD` reaches the project's script phases as `RD_CORE_PAYLOAD`, a
`desktop-apps` change made for this: the phases had the `build_tools/out` path
hardcoded. **If someone else is running a `build_tools` build, that directory is
rewritten underneath you mid-package.** Take an APFS clone first - it is
near-instant and costs no disk - and package the clone:

```sh
cp -Rc build_tools/out/mac_arm64/onlyoffice/desktopeditors /tmp/payload
RD_PAYLOAD=/tmp/payload harness/bin/build-app.sh
```

The target's "Increment Build Number" phase edits the *tracked*
`Info.plist` on every Release build; `build-app.sh` puts `CFBundleVersion` back
afterwards, so a harness build leaves no diff.

The harness asks for port 9222 rather than the app's built-in 8080, which
collides with common dev servers. Override with `RD_PORT`. `run-editor.sh`
distinguishes "debugging is off" from "someone else owns that port", because
they look identical from the outside.

`run-editor.sh` takes an optional document path and sends it with `open -a`
once CDP answers, then waits for an `apps/api/documents` page target and fails
loudly if none appears. It will not relaunch over a running instance: quit the
app first if it was started without debugging.

To run **our** editor code rather than the shipped bundle:

```sh
harness/bin/inject-sdkjs.sh cell     # build sdkjs + install into the app bundle
harness/bin/inject-sdkjs.sh --restore
```

Injection keeps a `.orig` backup per product and re-signs the bundle ad-hoc,
because replacing resources breaks the code signature. Local harness only - not
a distributable build.

## Driving the editor

```sh
node --experimental-websocket harness/bin/editor-eval.js --expr 'Asc.editor.editorId'
node --experimental-websocket harness/bin/editor-eval.js --file harness/repros/<name>.js --watch 10
```

Node 20 needs `--experimental-websocket`; Node 22+ has `WebSocket` built in.

Both `--expr` and `--file` run in the **editor iframe**, not the page target
`editor-eval.js` attaches to: it walks the wrapper page's iframes for one with
`Asc.editor` and evaluates through that window's own `eval`, so free names like
`AscCommonExcel` resolve in the scope where they actually exist. `--top`
evaluates in the wrapper page instead. Without this, everything reports
`Asc.editor missing`.

`editor-eval.js` subscribes to `Runtime.exceptionThrown`, console errors and
`Log.entryAdded` before evaluating, and exits non-zero if anything went
uncaught. **An uncaught exception is the thing that matters**: `apiBase.js`
turns it into `c_oAscError.ID.EditingError` and then calls
`asc_setViewMode(true)`, which is why one bad rule leaves a document
uneditable. `--watch N` keeps listening for N seconds afterwards, for failures
that only appear on a later render.

Script files are evaluated wrapped in a function, so they can `return` a value;
it comes back as JSON.

The result crosses CDP **by value**, so never return a live sdkjs model object.
They are deeply cyclic and CDP answers `Object reference chain is too long`
instead of returning anything at all - the script looks like it failed when it
ran fine. Return names, counts and plain objects.

## Converting without the editor

`x2t` ships inside the app bundle and runs headlessly, which covers the
file-format and converter bugs - the ones where the question is what landed in
the output, not what the UI did:

```sh
harness/bin/x2t.sh in.xlsx out.csv     # format inferred from the extension
harness/bin/x2t.sh in.docx out.bin     # .bin is the editors' internal format
harness/bin/x2t.sh in.xlsx out.x 8193  # or pass a format id outright
```

Format ids come from `core/Common/OfficeFileFormats.h`; note the bases are
`DOCUMENT 0x40`, `PRESENTATION 0x80`, `SPREADSHEET 0x100`, `CROSSPLATFORM
0x200`, `CANVAS 0x2000`. x2t exits 0 on success, non-zero otherwise, so it
works in a test loop.

## Repros

| File | Upstream issue | Status |
|---|---|---|
| `repros/2418-conditional-formatting.js` | #2418 - formula-based conditional formatting rule makes the editor unusable | reproduces; root cause found |

A repro should reproduce the reported steps *and* then poke the suspected code
path directly, so the failure is attributable rather than just observable.

### What #2418 turned out to be

```
TypeError: Cannot read properties of undefined (reading 'setDirtyConditionalFormatting')
    at CConditionalFormattingFormulaParent.onFormulaEvent (sdk-all.js:432648)
    at parserFormula.notify (sdk-all.js:305079)
    at DependencyGraph._broadcastNotifyListeners (sdk-all.js:392099)
    at DependencyGraph._broadcastCellsByCells (sdk-all.js:391703)
    at DependencyGraph._broadcastCells (sdk-all.js:391314)
    at DependencyGraph.calcTree (sdk-all.js:391019)
    at Workbook.sortDependency (sdk-all.js:394390)
    at Cell.setValue (sdk-all.js:404873)
```

`cell/model/Workbook.js` builds the rule's formula parent inside
`_updateConditionalFormatting` as
`new AscCommonExcel.CConditionalFormattingFormulaParent(this, oRule, true)` -
but for `Asc.ECfType.expression` that line sits in the local `doExpression`,
which is invoked as a bare `doExpression()`. The file is `"use strict"`, so
`this` is `undefined` and the parent is built with **no worksheet**. Every other
branch of the same `switch` writes that `this` straight in the method body,
where it really is the worksheet, which is why only formula-based rules break.

Then `onFormulaEvent` does `this.ws.setDirtyConditionalFormatting(...)` on the
`Change` notification, and editing any cell the rule's formula refers to throws.
Confirmed at runtime: the installed rule's `aRuleElements[0]._f.parent.ws` is
`undefined`. Left uncaught it reaches `apiBase.js`, becomes `EditingError` and
forces view mode - measured, `canEdit()` goes `true` -> `false`.

This is why the containment in `getSafeCompareFunction` did not cure it. The
throw is not on the compare/render path it wraps; it is on the dependency-graph
notify path, which nothing guards. `doExpression.call(this)` - or using the
method's existing `t` - is the actual fix.

## Limits

- Scripted CDP needs a build from this tree (see above). On an older build,
  either use F1 or make sure port 8080 is free.
- Needs a document open and editable; the scripts say so rather than guessing.
- Only exercises `sdkjs` / `web-apps`. Changes to `core`, `desktop-sdk` or
  `desktop-apps` are C++ and still need a full build.
- Injection modifies an installed app bundle in place. `--restore` undoes it.
- `enable-debug.sh --off` puts `settings.xml` back.
- `build-app.sh` packages only; it does **not** build `core`/`sdkjs`. Run
  `build_tools` yourself first, or point `RD_PAYLOAD` at a payload someone else
  built.
- `build-app.sh` is macOS/arm64 only in practice. The `ONLYOFFICE-x86_64` and
  `ONLYOFFICE-v8` targets take `RD_CORE_PAYLOAD` too, but neither was built or
  launched here, so treat `RD_TARGET` as untested.
- The bundle is ad-hoc signed. Good enough to run and to load CEF; not
  notarized, not distributable.
- `run-editor.sh` writes `moveToApplicationsFolderAlertSuppress` into the user's
  defaults for the app's bundle id, once. That is a real change to the user's
  environment, not a temporary one; `defaults delete <bundle-id>
  moveToApplicationsFolderAlertSuppress` undoes it.

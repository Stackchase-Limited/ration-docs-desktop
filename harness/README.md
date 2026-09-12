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

### Verified, and what is still missing

Verified on 2026-09-12 against a build from this tree: launching with
`--remote-debugging-port=9222` prints

```
DevTools listening on ws://127.0.0.1:9222/devtools/browser/<id>
```

and `http://127.0.0.1:9222/json/version` answers, reporting
`AscDesktopEditor/9.4.0.0`. Before the fix nothing bound any port.

What is **not** yet demonstrated is attaching to an editor *page*. `/json`
reports zero targets, because a CEF browser only exists once a document is
open - the start window is native. Two things stand in the way, neither of them
about the port:

- Swapping a freshly built `ascdocumentscore.framework` into an existing app
  bundle is not enough to get a usable app: the resulting mixture of an older
  app binary and a new framework launched with no window at all. Testing pages
  needs a properly packaged build from `desktop-apps/macos`, not an injected
  framework.
- In that broken bundle neither a file path on the command line nor an
  `open -a <app> <file>` Apple Event opened a document. Which of those works on
  a properly packaged build is untested.

So `editor-eval.js` and `repros/` are ready and the transport is proven, but
running a repro end to end still needs a packaged app with a document open.

## Setup

```sh
harness/bin/enable-debug.sh                   # once; writes the flag into settings.xml
harness/bin/blank-doc.sh xlsx /tmp/blank.xlsx # the app's "new document" flow is not scriptable
harness/bin/run-editor.sh /tmp/blank.xlsx     # launches the app, waits for CDP
```

The harness asks for port 9222 rather than the app's built-in 8080, which
collides with common dev servers. Override with `RD_PORT`. `run-editor.sh`
distinguishes "debugging is off" from "someone else owns that port", because
they look identical from the outside.

`run-editor.sh` takes an optional document path. The app is a
`SingleApplication`, so a second launch forwards arguments to the running
instance - quit it first if it was started without debugging.

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

`editor-eval.js` subscribes to `Runtime.exceptionThrown`, console errors and
`Log.entryAdded` before evaluating, and exits non-zero if anything went
uncaught. **An uncaught exception is the thing that matters**: `apiBase.js`
turns it into `c_oAscError.ID.EditingError` and then calls
`asc_setViewMode(true)`, which is why one bad rule leaves a document
uneditable. `--watch N` keeps listening for N seconds afterwards, for failures
that only appear on a later render.

Script files are evaluated wrapped in a function, so they can `return` a value;
it comes back as JSON.

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

| File | Upstream issue |
|---|---|
| `repros/2418-conditional-formatting.js` | #2418 - formula-based conditional formatting rule makes the editor unusable |

A repro should reproduce the reported steps *and* then poke the suspected code
path directly, so the failure is attributable rather than just observable.

## Limits

- Scripted CDP needs a build from this tree (see above). On an older build,
  either use F1 or make sure port 8080 is free.
- Needs a document open and editable; the scripts say so rather than guessing.
- Only exercises `sdkjs` / `web-apps`. Changes to `core`, `desktop-sdk` or
  `desktop-apps` are C++ and still need a full build.
- Injection modifies an installed app bundle in place. `--restore` undoes it.
- `enable-debug.sh --off` puts `settings.xml` back.

# Ration Docs editor harness

Runs the desktop editor with our own `sdkjs` in it, and drives it from Node over
the Chrome DevTools Protocol. The point is to turn "the editor shows *An error
occurred during the work with the document*" into a stack trace.

Most bugs in the upstream tracker cannot be confirmed by reading code alone. The
editor is a CEF browser, so it can be attached to and scripted like any page.

## Why this works, and what upstream got wrong

Debug-info support is enabled by `ascdesktop-support-debug-info-keep` in
`settings.xml` (see `LoadSettings` / `CheckSetting` in
`applicationmanager_p.h`), or by `--ascdesktop-support-debug-info` on the
command line. Two things hang off it:

**F1 opens DevTools.** `OnPreKeyEvent` in `cefview.cpp` calls `ShowDevTools()`
for key code 112 when `GetDebugInfoSupport()` is true. That check happens at
runtime, so **this works on the shipped build today** - it is just manual.

**Remote debugging did not work at all.** `client_app.h` appends the port from
`OnBeforeCommandLineProcessing`:

```cpp
if (m_manager->GetDebugInfoSupport())
    command_line->AppendSwitchWithValue("--remote-debugging-port", "8080");
```

but `main.cpp` calls `Init_CEF` *before* `initializeApp()` loads `settings.xml`,
so `GetDebugInfoSupport()` is still false when the browser command line is
built. The switch only ever landed on child process command lines - and the
DevTools HTTP server runs in the **browser** process. Verified on the shipped
9.0.4 build: the renderer had `--remote-debugging-port=8080` and nothing was
listening.

CEF starts that server from `CefSettings.remote_debugging_port`, which the app
never set. Our `desktop-sdk` now reads the port from the command line in
`Init_CEF` and sets it.

**That is necessary but not yet sufficient on macOS.** Built from this tree and
tested on 2026-09-12, still nothing binds the port. Established, so nobody has
to redo it:

- the fix is in the loaded binary (the new `--remote-debugging-port=` literal is
  present in `ascdocumentscore.framework`, absent from the previous build)
- macOS does reach it: `mac_application.mm` `Start:argv:` passes argc/argv to
  `Init_CEF`, and the process command line carries the port
- `settings.remote_debugging_port` is assigned before
  `MainContextImpl::Initialize`, which forwards the settings straight to
  `CefInitialize`, and nothing reassigns it in between
- the bundled CEF does contain the DevTools server (`/json/version`,
  `devtools_remote`)

So something after `CefInitialize` declines to start the server, and the cause
is not yet known. `settings.log_severity = LOGSEVERITY_DISABLE` in `Init_CEF`
means CEF logs nothing, so raising that temporarily is the obvious next probe.

**Until this is closed out, scripted CDP does not work on macOS.** Use F1 for
interactive debugging, and `bin/x2t.sh` for anything that can be expressed as a
conversion - that path is fully working.

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

- Scripted CDP does not work on macOS yet (see above) - `editor-eval.js` and
  `repros/` are written and ready, but blocked. F1 works; so does `x2t.sh`.
- Needs a document open and editable; the scripts say so rather than guessing.
- Only exercises `sdkjs` / `web-apps`. Changes to `core`, `desktop-sdk` or
  `desktop-apps` are C++ and still need a full build.
- Injection modifies an installed app bundle in place. `--restore` undoes it.
- `enable-debug.sh --off` puts `settings.xml` back.

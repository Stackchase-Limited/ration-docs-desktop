# CEF upgrade plan: CEF 109 -> current stable (Ration Docs)

Author: agent "ca", 2026-11-11 (security hardening round). Research and planning only: no product code
was changed and nothing was pushed.

Legend: **[V]** = verified here by running something (download + hash, compile, grep of the shipped
binary, index lookup). **[M]** = from memory / general CEF knowledge, NOT verified here; check it
before relying on it.

Scratch evidence lives in `.rd-work/wt/ca-tmp/`:
`dl/index.json` (CEF builds index, fetched 2026-11-11), `dl/x109/d/include` and `dl/x156/d/include`
(stock headers), `dl/s156/d/tests` (stock 156 cefclient sources), `cc/b109/*.log` and `cc/t156/*.log`
(compiler output), `scripts/syncheck.sh` (the compile check, rerunnable), `scripts/elfsec.py`.

---

## 0. Summary

| | |
|---|---|
| What we ship | CEF 109.1.18+gf1c41e4 / Chromium 109.0.5414.120 on every platform [V] |
| Recommended target | **CEF 156.0.27+ga10dae3 / Chromium 156.0.8078.88** (stable, published 2026-11-10 for macosarm64, macosx64, windows64, windowsarm64, linux64, linuxarm64) [V], then follow stable |
| Can we use the official (Spotify-hosted) binaries? | **Yes.** ONLYOFFICE's mac_arm64 and win_64 CEF archives are **byte-identical** to the official 109.1.18 builds [V]. Linux is a rebuild of the same version, flags unknown (see 1.3). |
| Do we lose proprietary codecs? | Not relevant for slides: slide audio/video plays in **native** players (AVPlayer on macOS, QMediaPlayer/libVLC in Qt), not in Chromium [V]. mac/win today already ship the codec-less official build [V]. |
| Size of the port (compile) | Our own sources compiled against 156 headers: **199 unique compiler errors** (about 170 distinct source sites after header duplicates) in 7 of 9 files, against **0** on 109 [V]. ~85% are mechanical (int64 types, frame id int64 -> string). |
| Hard blockers / big decisions | macOS minimum rises to **13.0** (109 framework: 11.0) [V]; C++20 required (CEF 156 headers do not compile as C++17) [V]; Alloy *runtime* is gone, Chrome bootstrap is mandatory, Alloy *style* is kept for our native-parent windows [V headers, M behaviour]. |
| Effort (one engineer who knows the code) | macOS arm64 shippable: **7-11 weeks**; Windows + Linux on top: **+4-6 weeks**; then ~2-4 days per monthly CEF bump. |
| Go / no-go | **Go**, provided we accept macOS 13+ (or keep a frozen 109 "legacy" build for macOS 11-12 with a clear security warning) and staff a real regression pass (Section 5, phase 3). |

---

## 1. How CEF is consumed today

### 1.1 Fetch: `build_tools/scripts/core_common/modules/cef.py` [V]
- Downloads `https://github.com/ONLYOFFICE-data/build_tools_data/raw/refs/heads/master/cef/<dir>/<platform>/cef_binary.7z`
  with `<dir>` = `5414` (CEF 109) for everything except: `*_xp` -> `4280`, option `cef_version_107` -> `5304`,
  `mac_64` + `use_v8` -> `5060` (CEF 103). Upstream's data repo has only those four dirs (4280, 5060, 5304,
  5414) - nothing newer exists upstream [V, `gh api repos/ONLYOFFICE-data/build_tools_data/contents/cef`].
- Unpacks into `core/Common/3dParty/cef/<platform>/build` (mac: just the framework; others: `Release/*` +
  `Resources/*`). Re-download is keyed on the URL's Last-Modified (`cef_binary.7z.data`).
- Archive sizes: mac_arm64 69.5 MB, win_64 95.5 MB, linux_64 92.2 MB, linux_arm64 89.8 MB (7z) [V].
- Deploy: `build_tools/scripts/deploy_desktop.py:112-136` copies the build dir and converts the
  framework into a versioned bundle (Versions/A + symlinks).

### 1.2 Headers and wrapper sources: `desktop-sdk/ChromiumBasedEditors/lib`
- `src/cef/{mac,linux,windows}/include`, `.../libcef_dll`, `.../tests` (cefclient/cefsimple/shared/gtest)
  are a vendored copy of the CEF 109.1.18 binary distribution. `cef_pri/cef_base.pri` compiles
  libcef_dll_wrapper from source into ascdocumentscore; `cef_pri/cef_client.pri` compiles **~45 files
  of the cefclient sample app** (`tests/cefclient/browser/*`, `tests/shared/*`) - desktop-sdk subclasses
  `client::ClientHandler`, `client::ClientAppBrowser`, `client::ClientAppRenderer`, `client::MainContextImpl`.
  `cef_pri_103/`, `cef_pri_107/`, `src/cef_103`, `src/cef_107` are older variants selected by
  `ascdocumentscore.pri:31-64` (`CEF_VERSION_ABOVE_86`, `CEF_VERSION_ABOVE_102`, `CEF_VERSION_103/107`).
- **Diff against stock 109.1.18** (official `cef_binary_109.1.18+gf1c41e4+chromium-109.0.5414.120_macosarm64{,_minimal}.tar.bz2`) [V]:
  - `include/` (mac): identical. linux/windows: only the expected platform files (`cef_config.h` adds
    `CEF_X11`, generated `cef_pack_resources.h` / `cef_pack_strings.h`, platform headers).
  - `libcef_dll/`: identical (minus the mac-only loader on win/linux).
  - `tests/` (mac): 4 tiny patches, all to let desktop-sdk subclass the samples:
    `private:` -> `protected:` in `cefclient/browser/client_handler.h`, `shared/browser/client_app_browser.h`,
    `shared/renderer/client_app_renderer.h`; `root_window_mac.mm` drops the OSR window and retitles
    "cefclient" -> "ONLYOFFICE".
  - Conclusion: **ONLYOFFICE does not patch the CEF API.** Everything custom is in desktop-sdk's own code.

### 1.3 The binaries
- **mac_arm64**: `Chromium Embedded Framework` sha1 `a1ad64bc...` is byte-identical to the official
  109.1.18 macosarm64 build (same size 160,329,496) [V].
- **win_64**: all 71 files (`Release/*`, `Resources/*`) byte-identical to the official 109.1.18 windows64
  minimal distribution [V].
- **linux_64**: same version string, same DT_NEEDED list, same max GLIBC symbol (2.17), but `libcef.so`
  differs: `.text` 163.1 MB vs 151.8 MB stock, `.rodata` 15.4 vs 15.0 MB; the paks and
  chrome-sandbox/libEGL/libGLESv2/libvulkan/libvk_swiftshader also differ [V]. So ONLYOFFICE rebuilt
  Chromium for Linux with different GN args. **Which** args is not known: string probes for
  H.264/AAC/MP4 give identical counts in all builds (inconclusive) [V]. Proprietary codecs are a
  plausible reason for the extra code [M, unverified].
- macOS app bundling: `desktop-apps/macos/ONLYOFFICE.xcodeproj/project.pbxproj` (shell build phases
  at ~2256/2293/2342) copies `Chromium Embedded Framework.framework` and three helpers
  `editors_helper.app`, `editors_helper (GPU).app`, `editors_helper (Renderer).app` into
  `Contents/Frameworks`, then codesigns `Libraries/libEGL.dylib`, `libGLESv2.dylib`,
  `libswiftshader_lib{EGL,GLESv2}.dylib`, `libvk_swiftshader.dylib`. The helpers are made by
  `build_tools/scripts/base.py:1529-1542` by copying `editors_helper.app` (which links ascdocumentscore
  and all core libraries; the renderer process runs desktop-sdk code).

### 1.4 Media playback (decides whether codec-less stock CEF is acceptable) [V]
- `sdkjs/common/apiBase.js:3513-3563` `showVideoControl` calls `AscDesktopEditor.MediaStart(...)`;
  renderer `client_renderer_wrapper.cpp:3676` sends `media_start`; browser `cefview.cpp:4082` opens the
  native player: `src/mac_cefviewmedia.mm` + `src/mac_videoplayer/*` (AVPlayer) on macOS,
  `ChromiumBasedEditors/videoplayerlib` (QMediaPlayer, or libVLC with `libvlc`) on Windows/Linux.
- No `<video>`/`<audio>` element is created by sdkjs or the presentation editor UI (grep of
  sdkjs/common, sdkjs/slide, web-apps presentationeditor + common lib: none).
- So H.264/AAC in Chromium only matters for web content inside plugins/iframes (e.g. an MP4 in a plugin
  page). mac/win users already have no proprietary codecs today. YouTube embeds work without them [M].
  => **Official stock CEF is acceptable.** Re-check Linux plugin media once (Phase 3).

---

## 2. Upstream's stalled attempt: desktop-sdk `feature/cef-update` (CEF 138) [V]

Ref present locally as `upstream/feature/cef-update`; 26 commits by Alexey Nagaev, 2025-07-23 ..
2025-08-06, merge-base `465a2027` (develop @ hotfix v9.0.4). Last commit 2025-08-06 (also via `gh api`).
No matching build_tools branch upstream and no CEF 138 archive in ONLYOFFICE-data, i.e. it never got a
binary pipeline.

What it changed (2036 files, +559k lines, almost all vendored `src/cef_138/{windows,linux}`):
- **No macOS port at all** - only `cef_138/windows` and `cef_138/linux`; `cef_base.pri` references
  `cef_138/mac` which does not exist.
- `ascdocumentscore.pri`: forces `CEF_VERSION_138` unconditionally (the `cef_version_138 {` guard is
  commented out) - debugging state, not mergeable as is.
- New `src/support.h`: `NSSupport::CFrameId` wrapper - frame id is `CefString` in new CEF, `int64` in
  old; `GetFrameByName` / `GetFrameByIdentifier` helpers. Removes `NSArgumentList::GetInt64/SetInt64`
  and sends frame ids as strings in every process message.
- Public API change: `CAscApplicationManager::SpellCheck(..., std::string frameId)`,
  `spellchecker.h AddTask`, `applicationmanager_events.h` `CAscSpellCheckType` / `CAscEditorScript`
  `m_nFrameId` long long -> std::string (class layout change - fine only because everything is rebuilt).
- `int64`/`uint32`/`uint64` -> `int64_t`/`uint32_t`/`uint64_t` everywhere.
- `cefapplication.cpp`: `cef::logging::ScopedEarlySupport` around pre-init code (new CEF asserts if
  logging is used before CefInitialize); `CefEnableHighDPISupport()` dropped; `user_data_path` ->
  `root_cache_path`; appends cefclient switch `use-native` (= native parent window, not Views);
  turns logging ON (`LOGSEVERITY_INFO`) - debugging leftover.
- `cefview.cpp`: `OnFileDialog` new signature (accept_extensions/descriptions),
  `OnBeforePopup(..., int popup_id, ...)`, `CEF_WOD_*`, `OnRenderProcessTerminated(..., error_code,
  error_string)`, message routing via `BaseClientHandler::OnProcessMessageReceived`,
  handler overrides `UseViews()=false`, `UseAlloyStyle()=false` (Chrome style on Win/Linux),
  `OnContentsBounds`, `GetTypeKey`.

What remains / is broken in that branch:
- `OnBeforeDownload` returns `true` unconditionally with `// TODO` (downloads are short-circuited),
  `CefDownloadItem` stubs `IsInterrupted/GetInterruptReason` are TODO, `OnBeforeClose` delegates to
  the sample with `// TODO`; macOS untouched; packaging untouched; no tests. Treat it as a useful
  map of the API delta (and the `CFrameId` idea), not as a base to merge.

---

## 3. Target choice [V unless marked]

From `https://cef-builds.spotifycdn.com/index.json` on 2026-11-11:

| channel | version | Chromium | platforms |
|---|---|---|---|
| stable (newest) | 156.0.27+ga10dae3 | 156.0.8078.88 | macosarm64, macosx64, windows64, windowsarm64, linux64, linuxarm64 (2026-11-10) |
| beta | 156.0.7+g47dbc1d | 156.0.8078.17 | same |
| previous stable | 154.0.34 / 152.0.15 | | |
| 150 branch (extended-stable-like) | 150.0.23 on win/linux (2026-10-31) but only 150.0.21 on macOS (2026-09-23) | 150.0.7871.x | uneven |

Sizes (compressed): macosarm64 standard 297 MB / minimal 128 MB; windows64 minimal 166 MB;
linux64 minimal 317 MB, standard 665 MB; linuxarm64 minimal 411 MB.

Recommendation:
- **Target CEF 156 stable** and use the **official binaries** directly (they are what ONLYOFFICE already
  ships on mac/win). The 150 branch is not kept up on macOS, so it is not a usable "ESR".
- Replace `cef.py`'s ONLYOFFICE-data URL with the Spotify CDN URL for an exact version, verified against
  the `sha1` from `index.json` (pin version + sha1 in the repo; do not resolve "latest" at build time).
- Use the **minimal** distribution for binaries + headers + libcef_dll; vendor only the few cefclient
  sample files we still need from the **standard** distribution (see 4.6) - or better, stop depending
  on cefclient (Phase 2b).
- Pin `CEF_API_VERSION` (new in CEF 133+: `include/cef_api_versions.h` lists 13300 .. 15600) [V]: with an
  explicit API version, later CEF binaries keep source/ABI compatibility for a range of versions, which
  makes the monthly bumps cheap [V header doc; range in practice M].
- What we would lose vs. ONLYOFFICE's builds: on mac/win nothing (identical). On Linux, whatever GN
  args ONLYOFFICE used (unknown; possibly proprietary codecs) - not needed for slides (1.4).

---

## 4. API migration 109 -> 156, by category

Method: `scripts/syncheck.sh` runs `clang++ -fsyntax-only -std=gnu++20` with the Makefile.core defines
over 9 desktop-sdk sources (client_scheme_wrapper, client_renderer_wrapper,
client_resource_handler_async, applicationmanager, spellchecker, cefapplication, cefview,
mac_cefview.mm, mac_application.mm). Against the vendored 109 tree: **0 errors** (C++20 is fine for
our code on mac, with `-Wno-register` as today). Against stock 156 include + tests: [V]

| file | errors |
|---|---|
| client_renderer_wrapper.cpp | 98 |
| cefview.cpp | 69 |
| cefapplication.cpp | 19 |
| client_scheme_wrapper.cpp | 13 |
| applicationmanager.cpp / spellchecker.cpp | 9 each (the same `applicationmanager_p.h` lines) |
| client_resource_handler_async.cpp, mac_cefview.mm, mac_application.mm | 0 |

199 unique error lines. Caveat: `-fsyntax-only` stops at the first error per construct, so behavioural
changes (handlers that silently stop being called, Chrome-bootstrap differences) are NOT counted.

### 4.1 Integer typedefs (mechanical, ~95 sites) [V]
`int64`, `uint32`, `uint64` no longer exist in CEF base. Sites: `applicationmanager_p.h:279-284,495-503,548-549`,
`cors_resource_hanler.h`, `client_scheme_wrapper.cpp:278,443`, `cefapplication.cpp:122-162` (message
pump `OnScheduleMessagePumpWork(int64)`), `cefwrapper/client_app.h:363`, `cefview.cpp:180,999,2575`, and
the many `int64` locals in `client_renderer_wrapper.cpp`. Pure search/replace.

### 4.2 Frame identifiers int64 -> CefString (~65 sites, the real work) [V]
`CefFrame::GetIdentifier()` returns `CefString`; `CefBrowser::GetFrame(int64)`/`GetFrame(name)` are
replaced by `GetFrameByIdentifier` / `GetFrameByName`; `GetFrameIdentifiers` fills `vector<CefString>`.
Sites: renderer `client_renderer_wrapper.cpp` 1180, 1672, 3089-3613, 3961, 4051-4380, 4809-5624,
6677-6808, 7091-7821; browser `cefview.cpp` (CEditorFrameId, crypto images map, downloaded-files frame,
TxtToDocx, upload files, `8908-8949` frame iteration), `applicationmanager_p.h` (CEditorFrameId,
NSRequest), public `include/applicationmanager_events.h` + `spellchecker.h`.
The renderer<->browser message protocol already sends frame ids as strings
(`NSArgumentList::GetInt64/SetInt64` parse/format strings), so the wire format barely changes; adopt
upstream's `NSSupport::CFrameId` idea but **without** dual-version `#ifdef`s (we will not go back).
Public header member types change -> desktop-apps (Qt + macOS app) must be rebuilt in lockstep; desktop-apps
itself does not reference FrameId or CEF headers [V grep], so no desktop-apps source changes.

### 4.3 Handler signature changes (silent-breakage risk) [V]
- `CefLifeSpanHandler::OnBeforePopup` gained `int popup_id` (`cefview.cpp:2310`); `WOD_*` -> `CEF_WOD_*`
  (`cefview.cpp:2340,2355`).
- `CefRequestHandler::OnRenderProcessTerminated` gained `error_code, error_string` (`cefview.cpp:5541`).
- `CefDownloadHandler::OnBeforeDownload` returns `bool` (`cefview.cpp:5591`; return false = we handle it /
  continue - check doc carefully, upstream got it wrong).
- `CefDownloadItem` new pure virtuals `IsInterrupted`, `GetInterruptReason` (our fake
  `CefDownloadItemAborted`, `cefview.cpp:293`).
- `CefDialogHandler::OnFileDialog` gained `accept_extensions`, `accept_descriptions`.
  **Side finding:** our `cefview.cpp:1934` `OnFileDialog(..., int selected_accept_filter, ...)` already
  does NOT match the 109 signature (109 has no `selected_accept_filter`) and is not marked override,
  so on 109 it is dead code today - Chromium's default file dialog is used. Decide during the port
  whether that handler (cloud upload crash workaround, non-mac only) is still wanted.
- Policy for the port: compile with `OVERRIDE=override` (already) **and** mark every CEF callback
  `override`; add `-Werror=inconsistent-missing-override` so a future signature change is a build error,
  not a silently ignored handler. Handlers currently lacking override: `cefview.cpp` OnLoadingStateChange
  4859, OnLoadStart 4910, OnLoadEnd 4925 (these match 109 today) and OnFileDialog 1934 (does not).

### 4.4 Settings, init, logging [V headers]
- `CefSettings.user_data_path` removed (`cefapplication.cpp:502`) -> `root_cache_path`; `cache_path` must
  be equal to or a child of `root_cache_path`, and new CEF holds a process-singleton lock on it (two
  instances with the same root fail to start) [V header text].
- `CefSettings.chrome_runtime` removed (109 had it at `cef_types.h:202`) - Chrome bootstrap is the only
  bootstrap [V].
- `CefEnableHighDPISupport()` gone on Windows [V upstream diff; M exact version].
- Logging before `CefInitialize` needs `cef::logging::ScopedEarlySupport` (upstream had hangs/crashes
  without it) [V upstream diff].
- `CefBrowserSettings`: `web_security`, `file_access_from_file_urls`, `universal_access_from_file_urls`,
  `plugins` were already gone in 109 (our code `#ifndef CEF_VERSION_ABOVE_102`s them, `cefview.cpp:6996-7006`);
  156 additionally removes `accept_language_list` (unused by us) and renames `databases` [V].

### 4.5 Command-line switches (`cefwrapper/client_app.h:255-339`) [V: switch names grepped in the 109 vs 156 mac framework binaries]
- Still present in 156: disable-gpu, disable-accelerated-2d-canvas, force-color-profile, disable-lcd-text,
  disable-extensions, disable-pinch, enable-aggressive-domstorage-flushing, log-severity,
  disable-component-update, disable-background-networking, disable-domain-reliability, no-pings,
  **disable-site-isolation-trials**, **allow-file-access-from-files**, use-mock-keychain,
  product-version, user-agent-product, force-device-scale-factor, remote-debugging-port,
  disable-web-security.
- Already dead in 109 and 156: `--disable-plugins`, `--enable-file-cookies`,
  `--enable-color-correct-rendering` (not in either binary) - delete them. (`--disable-d3d11`,
  `--password-store` are Windows/Linux-only, not checkable in the mac binary.)
- `ENABLE_CEF_EXTENSIONS` (`ascdocumentscore.pri:37`, mac) only suppresses `--disable-extensions`; the
  CEF extension API (`cef_extension.h`, `CefExtensionHandler`, `extension_util.*`) is **removed** in 156
  [V]; we do not call it ourselves, the cefclient samples did.
- Remote debugging in recent Chrome refuses the default profile dir [M]; we set our own
  `root_cache_path`, so it should keep working - test.

### 4.6 Runtime / style, windowing, cefclient dependence [V headers + M behaviour]
- 109 runs the **Alloy runtime**. In 156 there is only the Chrome bootstrap; each browser has a
  *runtime style* (`cef_types_runtime.h`). Our browsers are windowed children of a native view
  (`cefview.cpp:7014` `info.SetAsChild(...)`), not OSR and not Views.
- macOS: "Alloy style will always be used if ... `parent_view` is provided" (`cef_types_mac.h:150-155`)
  [V]. cefclient 156 `main_context_impl.cc:94-112`: "MacOS does not support Chrome style with native
  parent. See issue #3294" [V]. So on macOS we get Alloy style automatically; set
  `CefWindowInfo.runtime_style = CEF_RUNTIME_STYLE_ALLOY` explicitly on all platforms for consistency
  (upstream chose Chrome style on Win/Linux via `UseAlloyStyle()=false`; Alloy keeps the client callbacks
  we rely on and the closest behaviour to 109) [M].
- Even with Alloy style, the process now runs ChromeContentBrowserClient, Chrome profile prefs and more
  Chrome services [M]. Expect differences in: permission prompts, downloads UI, context menus, PDF
  viewer, print preview, background network (re-verify #2235 with a net-log), storage partitioning and
  third-party cookies (cloud portal SSO in iframes), Private/Local Network Access (plugins and the AI
  agent calling `http://localhost` LLM servers from `file://` pages may now hit a permission/block)
  [M - all must be tested].
- cefclient sample internals: 13 errors in `cefview.cpp:4790-4849, 5123` (`message_router_`,
  `message_handler_set_`, `browser_count_`, `delegate_`, `NotifyBrowserClosed/Closing` are now private
  members of the new `client::BaseClientHandler`/`ClientHandler`) and `client_app.h:365`
  (`OnScheduleMessagePumpWork` private). Re-applying the private->protected patch works short-term;
  **Phase 2b** should replace the subclassing with our own small handler (the sample changes shape every
  few releases - this dependency is the main reason each bump costs more than headers).
- Only file genuinely gone from the cef_client.pri list (mac): `tests/shared/browser/extension_util.*`
  [V; the other "missing" entries are win/gtk files absent from a mac distribution].
- libcef_dll: 363 -> 411 files, 29 removed (mostly V8 wrapper files renamed `v8_*`, extension files
  deleted, x509 renamed), 77 added [V] -> regenerate `cef_base.pri` from the distribution's
  `cmake/libcef_dll_wrapper` list instead of hand-editing.

### 4.7 V8 / renderer API [V]
CefV8Value (219 uses), CefV8Context (89), CefV8Handler, CefV8Exception, CefRenderProcessHandler,
CefMessageRouterRendererSide: **zero** compile errors against 156. The `window.AscDesktopEditor` bridge
(`client_renderer_wrapper.cpp`, injection ~6560) ports unchanged except for frame ids.

### 4.8 Toolchain and platform floor [V unless marked]
- CEF 156 headers need **C++20** (`cef_scoped_refptr.h:101` uses `std::same_as`; fails as gnu++17).
  desktop-sdk builds as `-std=gnu++1z` today (Makefile.core). Our 9 files pass as gnu++20 on mac.
  Linux builds use an Ubuntu 16.04 sysroot (`build_tools/tools/linux/sysroot/fetch.py:12-13`) and its
  toolchain - needs a GCC >= 10 / clang toolchain for C++20 [M].
- **macOS minimum 13.0**: 156 framework `LC_BUILD_VERSION minos 13.0` vs 109 `minos 11.0` [V].
  Xcode project deployment targets are 10.10-11.0 today. Dropping macOS 11 and 12 is a product decision.
- Windows 10+ (Chromium dropped 7/8.1 at 110) [M]. Linux glibc floor of official CEF 156 builds is
  higher than 109's 2.17 (Chromium's sysroot is Debian Bullseye class) [M - check with the 156 linux64
  minimal before committing to a distro list].

### 4.9 macOS bundle and sandbox [V]
- Helpers: 156 cmake `CEF_HELPER_APP_SUFFIXES` = base, **(Alerts)**, (GPU), **(Plugin)**, (Renderer)
  (109: base, GPU, Plugin, Renderer). We ship only base/GPU/Renderer (`base.py:1529-1542`): add Alerts
  (Chrome bootstrap notifications) and Plugin.
- Framework `Libraries/` in 156: `libcef_sandbox.dylib`, `libvk_swiftshader.dylib`, `libvulkan.dylib`,
  `vk_swiftshader_icd.json` - **no libEGL/libGLESv2** (109 had them). The Xcode signing phase codesigns
  `Libraries/libEGL.dylib`, `libGLESv2.dylib` and `libswiftshader_lib*.dylib` explicitly (the swiftshader
  ones do not exist in 109 either) -> rewrite to sign whatever is in `Libraries/`.
- `cef_sandbox.a` (109) became `libcef_sandbox.dylib` (156).
- Sandbox: `settings.no_sandbox = true` (`cefapplication.cpp:411`) can stay for the upgrade. Turning the
  sandbox on is a **separate** project: the renderer process does direct file I/O (203
  `NSFile`/`NSDirectory` calls in `client_renderer_wrapper.cpp`) which would have to move to the browser
  process over IPC.

---

## 5. Phased plan

Estimates are engineer-weeks for one person familiar with desktop-sdk; ranges include debugging.

**Phase 0 - decisions (2-3 days)**
- Decide macOS floor (13+), Windows 10+, Linux distro floor; decide what happens to macOS 11-12 users
  (frozen 109 legacy build with an in-app "unsupported, insecure" notice, or drop).
- Toolchain: C++20 for desktop-sdk (and anything including CEF headers); Linux toolchain/sysroot plan.
- Branch: `ration/cef-156` in desktop-sdk + build_tools + desktop-apps worktrees (no dual-version ifdefs).

**Phase 1 - mac arm64 spike (1-2 weeks)**
- Build stock `cefsimple`/`cefclient` from the 156 standard distribution; load a static copy of the
  editor (`web-apps/deploy` + sdkjs) from `file://` with `--allow-file-access-from-files`, inside a
  native NSView parent, Alloy style. Confirms: editor JS + WASM run, fonts, canvas, clipboard.
- Then compile ascdocumentscore against 156 with the mechanical fixes (4.1, 4.2, 4.4) and the
  private->protected sample patches; build `editors_helper` x5; run in the persistent test-app recipe
  (`rationdocs/.rd-work`, separate bundle ID). Exit: open/edit/save docx/xlsx/pptx/pdf locally.

**Phase 2 - port desktop-sdk properly (2-3 weeks)**
- 2a: all handler signatures (4.3) with `override` everywhere + `-Werror=inconsistent-missing-override`;
  downloads (`OnBeforeDownload` semantics), popups, render-process-terminated recovery, file dialog
  decision, settings (4.4), switches cleanup (4.5), logging early-support.
- 2b: drop the cefclient sample dependency (own `CefClient`/`CefApp` + message router), or at minimum
  vendor only the handful of sample files we still use with a documented patch list.
- 2c: `cef_base.pri` generated from the distribution file list; `cef.py` -> official URL + sha1 pin.

**Phase 3 - behavioural regression pass (2-4 weeks; the real risk)**
Enumerate and test every consumer: local open/save/recovery, print, drag-drop, IME, DPI/multi-monitor,
spellcheck, plugins + plugin store, macros, PDF forms (AF* scripts), AI agent (cloud and localhost
providers), cloud portals + SSO login popups, cookies persistence, crypto (cloud_crypto), video/audio in
slides (native players), external links to system browser, DevTools (`--remote-debugging-port`),
keychain, net-log for background traffic (#2235), memory/CPU baseline vs 109.
Add fork-fix-tests where a behaviour is scriptable.

**Phase 4 - packaging per platform**
- macOS (1 week): helpers (+Alerts, +Plugin), signing phase rewrite, entitlements, notarization,
  Sparkle update path (update from 109-based build keeps user data: cache dir layout changes).
- Windows (1.5-2.5 weeks): build + installer file lists (`libcef.dll`, `chrome_elf.dll`, paks,
  `v8_context_snapshot.bin`, swiftshader/vulkan, `dxcompiler`/`dxil` if present [M]), HiDPI manifest.
- Linux (2-3 weeks): toolchain/sysroot for C++20, glibc floor, `chrome-sandbox` SUID or user-namespace
  handling, Ozone/X11 vs Wayland with a native XID parent (force `--ozone-platform=x11` under Wayland
  likely needed [M]), deb/rpm/AppImage.

**Phase 5 - stay current (ongoing)**
- Pin `CEF_API_VERSION`; bump CEF every stable (4 weeks) or at least for every Chromium security
  release with in-the-wild exploitation; budget 2-4 days per bump once Phase 2b is done.
- CI job: syncheck against the newest CEF beta to see API breaks a month early.

**Totals:** macOS arm64 shippable 7-11 weeks (Phases 0-4 mac); Windows + Linux +4-6 weeks.

### Risks
1. macOS 13 floor strands macOS 11/12 users (high product impact).
2. Chrome-bootstrap behaviour differences that compile fine but change runtime (cookies/SSO, Local
   Network Access for localhost AI, file:// treatment, downloads) - only a manual pass catches them.
3. cefclient sample churn - each bump breaks our subclasses until Phase 2b removes the dependency.
4. Linux toolchain jump (Ubuntu 16 sysroot -> C++20) touches the whole core build, not only desktop-sdk.
5. Linux codec/flag parity with ONLYOFFICE's custom build is unknown (low impact given native players).
6. Interaction with this round's hardening (site isolation on, bridge origin gating): do those first on
   109 so the upgrade is a pure engine swap, then re-test them on 156.

---

## 6. Interim mitigations until 156 ships

Already identified in UPSTREAM_TRIAGE.md #1664 (do first, engine-independent):
1. Isolate PDF form JavaScript from the page global / `AscDesktopEditor` (formActions.js EvalScript).
2. Gate `window.AscDesktopEditor` injection by origin (client_renderer_wrapper.cpp ~6560): only our
   editor/start pages and an allowlist; nothing for YouTube/plugin-store/third-party frames.
3. Macro warning default button -> "No"; close the AsyncFunction escape in `_safePluginEval`.
4. Remove `--disable-site-isolation-trials` (`client_app.h:290`) once consumers are tested; try dropping
   `--allow-file-access-from-files` (`client_app.h:294`) behind a resource handler that serves editor
   files over our own scheme.

Engine-exposure reducers (candidates, need testing):
5. **WebP (CVE-2023-4863 class):** in the scheme/resource path that serves document media to the
   editor, sniff `RIFF....WEBP` and transcode to PNG natively (core already decodes images) or refuse;
   make x2t stop passing WebP through as `media/*.png`.
6. Restrict navigation: keep all top-level and frame navigations to remote origins out of privileged
   views; open links in the system browser (already done for document links).
7. Reduce V8 optimizing-tier attack surface with `--js-flags=--no-opt` (TurboFan off; keeps Sparkplug/
   Ignition and WebAssembly, which sdkjs needs - `--jitless` would also disable WASM, so not usable) [M];
   measure editor performance before shipping it.
8. Plugin store / remote plugin content: allowlist origins; consider disabling remote plugin install in
   the interim.
9. Keep `--disable-background-networking` etc. (#2235) - fewer remote inputs to the old engine.
10. Communicate: release notes stating the engine version and that untrusted documents should not be
    opened until the engine update ships.

---

## 7. Verified vs from-memory index

Verified here: everything in 1.1-1.4, 2, the version/size table in 3, API-version header, compile
error counts and sites (4.1-4.3, 4.7), removed settings fields (4.4), switch presence (4.5), extension
API removal and libcef_dll file churn (4.6), Alloy-style-on-mac rule from headers and cefclient,
C++20 requirement, macOS minos 13.0, helper suffixes, framework Libraries contents, renderer file-I/O
count (4.9), media pipeline (1.4), upstream branch contents/dates.

From memory (verify before relying): Chrome-bootstrap behavioural differences list (4.6), Windows 10
floor, Linux glibc floor and Ozone/Wayland behaviour, remote-debugging default-profile rule,
`--js-flags=--no-opt` effect, CEF_API_VERSION compatibility range in practice, exact CEF versions in
which individual APIs changed, YouTube without proprietary codecs.

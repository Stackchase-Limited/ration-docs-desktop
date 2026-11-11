# User plugins in their own origin (#1664 follow-up) - plan

Status: IMPLEMENTED 2026-11-11 (desktop-sdk c9b26fcebc, sdkjs ff6eb2e4e3; see UPSTREAM_TRIAGE.md #1664). Written from agent cj's assessment.

## Problem
User-installed plugins load from file:// (or the shared onlyoffice://plugin origin). With
--allow-file-access-from-files every file:// page is one origin, so a third-party plugin can script the
editor page and reach the AscDesktopEditor bridge as if it were our code.

## What makes it feasible
- Marketplace plugins never touch parent/top directly; web-apps never touches a plugin frame's document.
- The plugin API is postMessage only: sdkjs common/plugins.js posts with "*" (:501, :544, :1025) and
  checkOrigin (:1461-1481) already accepts a foreign origin that prefixes baseUrl.

## Steps
1. New scheme `rdplugin` (standard, secure, CORS + fetch) beside onlyoffice in desktop-sdk
   client_scheme_wrapper.cpp:618 + factory registration. Origin per plugin: rdplugin://<guid-lower>/.
   Map <guid>/<path> to user_plugins_path/{GUID}/<path>; map shared v1/, pluginBase.js, plugins.css to
   the user plugins root (plugins use ../v1/plugins.js). Check with NSFileAccess::ResolvePath that the
   resolved file stays inside that plugin's folder.
2. sdkjs common/Local/common.js:432-455 (UpdateInstallPlugins): baseUrl for user plugins (k==1) ->
   rdplugin://<guid>/, incl. the onlyofficeScheme branch (:450-453). Iframes are made at
   sdkjs common/plugins.js:1161 and web-apps apps/common/main/lib/view/PluginDlg.js:101.
3. cefview.cpp:5096-5100: external (isUser) plugin sSrc -> rdplugin.
4. bridge_access.h: drop the user plugins dir from the file:// trusted dirs
   (client_renderer_wrapper.cpp:6876 AddDir(user_plugins_path); Check at bridge_access.h:311-322);
   exclude it from the onlyoffice://plugin/ branch (:324-329). Give rdplugin:// frames an ALLOWLIST tier
   (not the deny-list of IsPluginFrame :365 / IsPluginRestrictedMethod :389, enforced at
   client_renderer_wrapper.cpp:1417, :6454, :6767): OpenFilenameDialog, GetImageBase64 only for
   picked files, GetSupportedScaleValues, theme/language getters, plus what an inventory of user
   plugins shows is needed.
5. file:// gate: keep the user plugins dir readable to our pages (plugin manager reads config.json and
   icons), but refuse file:// main/sub-frame navigations into it (cefview.cpp GetResourceHandler).
6. Plugin store / installer are bundled system plugins: unchanged; verify install/update/uninstall live.
7. User-visible: a user plugin's localStorage moves to the new origin (e.g. a user-installed AI plugin's
   API keys) - migrate or tell users. Plugins needing more bridge than the allowlist break until added.
   Known bridge users: OCR (onlyoffice.github.io sdkjs-plugins/content/ocr/scripts/ocr.js:78,101),
   AI (ai/scripts/code.js:385), speechrecognition (scripts/code.js:36).
8. Tests: extend fork-fix-tests/issue-1664-bridge-origin with rdplugin chains, add a scheme path test,
   live-check that a user plugin cannot read parent.AscDesktopEditor / parent.document and that OCR,
   AI and the Plugin Manager work.

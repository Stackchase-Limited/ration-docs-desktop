# Shared environment discovery for the harness. Source this, do not run it.
# Override anything by exporting it first.

# Which .app to drive. Prefer our own build, fall back to an installed ONLYOFFICE.
# Prefer our own in-tree build: that is the one carrying our fixes. Fall back to
# an installed Ration Docs, then to a stock ONLYOFFICE (useful for comparing
# behaviour against upstream, but it does not contain our changes).
RD_ROOT="${RD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
if [ -z "${RD_APP:-}" ]; then
	for candidate in \
		"$RD_ROOT/desktop-apps/build/Ration Docs.app" \
		"/Applications/Ration Docs.app" \
		"$HOME/Applications/Ration Docs.app" \
		"/Applications/ONLYOFFICE.app" \
		"$HOME/Applications/ONLYOFFICE.app"
	do
		if [ -d "$candidate" ]; then RD_APP="$candidate"; break; fi
	done
fi

# x2t from our own build. core/build/bin/<plat>/x2t comes FIRST because it is the
# one a rebuild updates - the copy inside the app bundle is only refreshed when
# somebody repackages, so preferring it (as this did until #1359) silently tests a
# converter that predates the fix you are trying to verify, and reports success.
#
# The bundle copy is self-contained; the core/build one resolves its frameworks
# through @rpath and aborts on its own, which is why it was skipped. That is fixable
# rather than fatal: rd_x2t also sets RD_X2T_FRAMEWORKS, and callers put it in
# DYLD_FRAMEWORK_PATH.
#
# Export RD_X2T to pin a specific binary - point it at the bundle copy deliberately
# when you want a pre-fix baseline to compare against.
rd_x2t() {
	if [ -n "${RD_X2T:-}" ]; then echo "$RD_X2T"; return; fi
	for plat in mac_arm64 mac_x86_64 linux_x86_64; do
		if [ -x "$RD_ROOT/core/build/bin/$plat/x2t" ]; then
			echo "$RD_ROOT/core/build/bin/$plat/x2t"; return
		fi
	done
	for candidate in \
		"$RD_ROOT/desktop-apps/build/Ration Docs.app/Contents/Resources/converter/x2t" \
		"$RD_APP/Contents/Resources/converter/x2t" \
		"$RD_ROOT/build_tools/out/mac_arm64/onlyoffice/desktopeditors/converter/x2t"
	do
		if [ -x "$candidate" ]; then echo "$candidate"; return; fi
	done
}

# Where that binary's frameworks live. Derived from the path rather than set inside
# rd_x2t, because rd_x2t is called as $(rd_x2t) - a subshell, whose variable
# assignments are discarded. core/build/bin/<plat>/x2t resolves @rpath against
# core/build/lib/<plat>; every other copy keeps its frameworks beside it.
rd_x2t_frameworks() {
	local x2t="$1"
	case "$x2t" in
		"$RD_ROOT"/core/build/bin/*)
			echo "$RD_ROOT/core/build/lib/$(basename "$(dirname "$x2t")")" ;;
		*)
			dirname "$x2t" ;;
	esac
}

# 8080 is the app's built-in default but collides with common dev servers,
# so the harness asks for 9222 explicitly. Override with RD_PORT.
RD_PORT="${RD_PORT:-9222}"

rd_require_app() {
	if [ -z "${RD_APP:-}" ] || [ ! -d "$RD_APP" ]; then
		echo "harness: no editor app found. Install one, or export RD_APP=/path/to/App.app" >&2
		return 1
	fi
}

rd_bundle_id() {
	/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$RD_APP/Contents/Info.plist" 2>/dev/null
}

rd_app_version() {
	/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$RD_APP/Contents/Info.plist" 2>/dev/null
}

rd_executable() {
	local exe
	exe=$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$RD_APP/Contents/Info.plist" 2>/dev/null)
	echo "$RD_APP/Contents/MacOS/$exe"
}

# settings.xml lives next to the font cache: <app support>/data/settings.xml.
# See CAscApplicationManager_Private::LoadSettings in desktop-sdk.
rd_settings_file() {
	local id
	id=$(rd_bundle_id)
	if [ "$(uname)" = "Darwin" ]; then
		echo "$HOME/Library/Application Support/$id/data/settings.xml"
	else
		echo "$HOME/.local/share/${id##*.}/data/settings.xml"
	fi
}

rd_editors_dir() {
	echo "$RD_APP/Contents/Resources/editors"
}

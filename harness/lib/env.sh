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

# x2t from our own build, preferring the copy inside the app bundle: that one is
# self-contained, while core/build/bin/x2t needs the bundle's @rpath framework
# layout and aborts on its own.
rd_x2t() {
	for candidate in \
		"$RD_ROOT/desktop-apps/build/Ration Docs.app/Contents/Resources/converter/x2t" \
		"$RD_APP/Contents/Resources/converter/x2t" \
		"$RD_ROOT/build_tools/out/mac_arm64/onlyoffice/desktopeditors/converter/x2t"
	do
		if [ -x "$candidate" ]; then echo "$candidate"; return; fi
	done
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

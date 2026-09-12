# Shared environment discovery for the harness. Source this, do not run it.
# Override anything by exporting it first.

# Which .app to drive. Prefer our own build, fall back to an installed ONLYOFFICE.
if [ -z "${RD_APP:-}" ]; then
	for candidate in \
		"/Applications/Ration Docs.app" \
		"$HOME/Applications/Ration Docs.app" \
		"/Applications/ONLYOFFICE.app" \
		"$HOME/Applications/ONLYOFFICE.app"
	do
		if [ -d "$candidate" ]; then RD_APP="$candidate"; break; fi
	done
fi

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

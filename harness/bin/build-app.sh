#!/bin/bash
# Package a launchable macOS .app from desktop-apps/macos around a built
# desktop-sdk payload.
#
#   harness/bin/build-app.sh
#   RD_PAYLOAD=/somewhere/desktopeditors harness/bin/build-app.sh
#   RD_BUILD_DIR=/tmp/app harness/bin/build-app.sh
#
# Why this exists: injecting a freshly built ascdocumentscore.framework into an
# existing bundle is not a substitute for packaging. Only the Xcode target runs
# the phases that copy the CEF framework and the three editors_helper apps,
# rewrite the Chromium load path from @executable_path to @rpath, copy
# Vendor/ONLYOFFICE into Resources, and re-sign the lot in dependency order.
#
# The payload is whatever build_tools produced. When someone else is running a
# build_tools build at the same time, that directory is rewritten underneath
# you: take an APFS clone first (near-instant, no extra disk) and point
# RD_PAYLOAD at the clone.
#
#   cp -Rc build_tools/out/mac_arm64/onlyoffice/desktopeditors /tmp/payload
#
# There are no code-signing identities on a dev machine, so everything is signed
# ad-hoc. That is fine locally; it is not distributable.
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh

MACOS_DIR="$RD_ROOT/desktop-apps/macos"
PROJECT="$MACOS_DIR/ONLYOFFICE.xcodeproj"
TARGET="${RD_TARGET:-ONLYOFFICE-arm}"
PLIST="$MACOS_DIR/ONLYOFFICE/Resources/$TARGET/Info.plist"
PAYLOAD="${RD_PAYLOAD:-$RD_ROOT/build_tools/out/mac_arm64/onlyoffice/desktopeditors}"
BUILD_DIR="${RD_BUILD_DIR:-$RD_ROOT/desktop-apps/build}"

[ -d "$PROJECT" ] || { echo "build-app.sh: no Xcode project at $PROJECT" >&2; exit 1; }
if [ ! -d "$PAYLOAD/ascdocumentscore.framework" ]; then
	echo "build-app.sh: $PAYLOAD does not look like a desktopeditors payload" >&2
	echo "              (no ascdocumentscore.framework). Build it, or set RD_PAYLOAD." >&2
	exit 1
fi

echo "target:  $TARGET"
echo "payload: $PAYLOAD"
echo "output:  $BUILD_DIR"

# The "Increment Build Number" phase edits the *tracked* Info.plist on every
# Release build. A local harness build is not a release, so put it back.
BUILDNO=""
[ -f "$PLIST" ] && BUILDNO=$(/usr/libexec/PlistBuddy -c "Print CFBundleVersion" "$PLIST" 2>/dev/null || true)
restore_buildno() {
	if [ -n "$BUILDNO" ] && [ -f "$PLIST" ]; then
		/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $BUILDNO" "$PLIST" >/dev/null 2>&1 || true
	fi
}
trap restore_buildno EXIT

LOG="${TMPDIR:-/tmp}/ration-build-app.log"
echo "log:     $LOG"
echo

set +e
# RD_CORE_PAYLOAD is read by the "Copy Library" and "Rename symbols" phases; it
# defaults to build_tools/out inside the project when unset.
#
# CODE_SIGN_IDENTITY=- is an ad-hoc signature. The phases sign only when
# EXPANDED_CODE_SIGN_IDENTITY is non-empty and signing is not disabled, so this
# has to stay switched on rather than being turned off: an unsigned CEF
# framework will not load.
xcodebuild \
	-project "$PROJECT" \
	-target "$TARGET" \
	-configuration Release \
	RD_CORE_PAYLOAD="$PAYLOAD" \
	CONFIGURATION_BUILD_DIR="$BUILD_DIR" \
	CODE_SIGN_IDENTITY=- \
	CODE_SIGN_STYLE=Manual \
	DEVELOPMENT_TEAM= \
	PROVISIONING_PROFILE_SPECIFIER= \
	build > "$LOG" 2>&1
RC=$?
set -e

if [ $RC -ne 0 ]; then
	echo "build-app.sh: xcodebuild failed ($RC). Last lines of $LOG:" >&2
	grep -E "error:|\*\* BUILD" "$LOG" | tail -20 >&2 || tail -30 "$LOG" >&2
	exit $RC
fi

APP=$(/bin/ls -d "$BUILD_DIR"/*.app 2>/dev/null | head -1)
[ -n "$APP" ] || { echo "build-app.sh: build succeeded but no .app in $BUILD_DIR" >&2; exit 1; }

# A bundle whose signature does not verify tends to fail in ways that look like
# a code bug, so check rather than assume.
codesign --verify --deep --strict "$APP" || {
	echo "build-app.sh: signature does not verify - re-signing ad-hoc" >&2
	codesign --force --deep --sign - "$APP"
	codesign --verify --deep --strict "$APP"
}

echo "** BUILD SUCCEEDED **"
echo "app: $APP"
echo
echo "Next: harness/bin/enable-debug.sh && harness/bin/run-editor.sh <doc>"

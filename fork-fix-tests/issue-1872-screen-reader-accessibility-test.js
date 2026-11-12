/*
 * #1872 "No Screen Reader Support" (macOS, VoiceOver) - desktop-sdk
 * ChromiumBasedEditors/lib/src/{accessibility_state.h, mac_application.mm, cefview.cpp}.
 *
 * Bug: with VoiceOver on, the app read the window title and "button" and
 * nothing else. The editors' interface is HTML with roles and aria-labels
 * (web-apps Common.UI.Button sets aria-label from the hint of icon-only
 * buttons, the header is a labelled role=menubar), but Chromium keeps the
 * accessibility tree of a page off until the embedder enables it: CEF's
 * CefBrowserHost::SetAccessibilityState doc says "the client needs only to
 * detect the screen reader and call this method ... on macOS the client can
 * handle the @"AXEnhancedUserInterface" accessibility attribute". Nothing in
 * desktop-sdk called SetAccessibilityState and no --force-renderer-accessibility
 * is passed, so no page was ever exposed.
 *
 * Fix: NSAscApplication (the NSApp) overrides accessibilitySetValue:forAttribute:
 * for AXEnhancedUserInterface / AXManualAccessibility and passes the state to
 * NSAscAccessibility (accessibility_state.h), which remembers it and applies it
 * to every browser the client handler registered in OnAfterCreated (and drops
 * in OnBeforeClose) - open browsers and the ones created later.
 *
 * This test:
 *   - compiles the REAL accessibility_state.h against a stub cef_browser.h that
 *     records SetAccessibilityState calls;
 *   - extracts the REAL accessibilitySetValue:forAttribute: method from
 *     mac_application.mm and compiles it into an NSApplication subclass
 *     (Objective-C++, Cocoa);
 *   - extracts the NSAscAccessibility:: statements of the REAL OnAfterCreated /
 *     OnBeforeClose of cefview.cpp (and fails if they are not there);
 *   - checks: no call while no screen reader; VoiceOver on -> an open browser
 *     and a browser created afterwards get STATE_ENABLED; a closed browser is
 *     not touched again; VoiceOver off -> STATE_DISABLED; an unrelated
 *     attribute does nothing.                                (baseline: FAILS)
 *
 * NOT claimed: that VoiceOver now reads everything well - that needs a GUI
 * check with VoiceOver in the app (toolbar, menus, dialogs). The document
 * itself is drawn on a canvas and stays unreadable. Linux (Orca, #1828) and
 * Windows are unchanged. macOS only (needs clang and Cocoa).
 *
 * Env: RD_REPO   desktop-sdk checkout (default ../desktop-sdk)
 *      BASELINE=1 reads the sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

if (process.platform !== 'darwin') {
	console.log('SKIP #1872: macOS only (Objective-C++ / Cocoa)');
	process.exit(0);
}

const SDK = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-sdk'));
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '61e4e166^';
const SRC = 'ChromiumBasedEditors/lib/src/';

function read(rel) {
	if (process.env.BASELINE) {
		try {
			return execFileSync('git', ['-C', SDK, 'show', `${BASE_REF}:${SRC}${rel}`],
				{ encoding: 'utf8', maxBuffer: 1 << 26, stdio: ['ignore', 'pipe', 'ignore'] });
		} catch (e) {
			return null;
		}
	}
	const p = path.join(SDK, SRC, rel);
	return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const header = read('accessibility_state.h');
const macApp = read('mac_application.mm');
const cefview = read('cefview.cpp');
assert.ok(macApp && cefview, 'mac_application.mm / cefview.cpp not found - test is stale');

assert.ok(header, 'accessibility_state.h is missing: nothing ever calls CefBrowserHost::SetAccessibilityState, so VoiceOver sees no page');

const impl = macApp.indexOf('@implementation NSAscApplication');
const mAt = macApp.indexOf('- (void)accessibilitySetValue:', impl);
assert.ok(impl !== -1, '@implementation NSAscApplication not found - test is stale');
assert.ok(mAt !== -1 && mAt < macApp.indexOf('@end', impl),
	'NSAscApplication does not handle accessibilitySetValue:forAttribute: - VoiceOver turning on never reaches the browsers');
const method = block(macApp, mAt);

// The NSAscAccessibility statements of the client handler's life-span callbacks.
function hookLines(sig) {
	const at = cefview.indexOf(sig);
	assert.ok(at !== -1, sig + ' not found in cefview.cpp - test is stale');
	const lines = block(cefview, at).split('\n').filter((l) => /NSAscAccessibility::/.test(l));
	assert.ok(lines.length, sig + ' does not register the browser with NSAscAccessibility');
	return lines.join('\n');
}
const afterCreated = hookLines('virtual void OnAfterCreated(CefRefPtr<CefBrowser> browser)');
const beforeClose = hookLines('virtual void OnBeforeClose(CefRefPtr<CefBrowser> browser)');

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1872-'));
try {
	fs.mkdirSync(path.join(tmp, 'include'));
	// Minimal stand-in for CEF: ref-counted pointer, browser, host recording the state.
	fs.writeFileSync(path.join(tmp, 'include', 'cef_browser.h'), `
#pragma once
#include <vector>
#include <utility>
typedef enum { STATE_DEFAULT = 0, STATE_ENABLED, STATE_DISABLED } cef_state_t;
template <class T> class CefRefPtr {
public:
	CefRefPtr() : p(0) {}
	CefRefPtr(T* t) : p(t) {}
	T* operator->() const { return p; }
	T* get() const { return p; }
	operator bool() const { return p != 0; }
private:
	T* p;
};
extern std::vector<std::pair<int, int>> g_calls;   // (browser id, state)
class CefBrowserHost {
public:
	int id;
	void SetAccessibilityState(cef_state_t s) { g_calls.push_back(std::make_pair(id, (int)s)); }
};
class CefBrowser {
public:
	CefBrowserHost host;
	explicit CefBrowser(int i) { host.id = i; }
	int GetIdentifier() { return host.id; }
	CefRefPtr<CefBrowserHost> GetHost() { return CefRefPtr<CefBrowserHost>(&host); }
};
`);
	fs.writeFileSync(path.join(tmp, 'accessibility_state.h'), header);
	fs.writeFileSync(path.join(tmp, 'drv.mm'), `
#import <Cocoa/Cocoa.h>
#include <cstdio>
#include "accessibility_state.h"
std::vector<std::pair<int, int>> g_calls;

@interface TestApp : NSApplication
@end
@implementation TestApp
${method}
@end

static void AfterCreated(CefRefPtr<CefBrowser> browser) {
${afterCreated}
}
static void BeforeClose(CefRefPtr<CefBrowser> browser) {
${beforeClose}
}
static void dump(const char* what) {
	printf("%s:", what);
	for (size_t i = 0; i < g_calls.size(); i++)
		printf(" %d=%s", g_calls[i].first, g_calls[i].second == STATE_ENABLED ? "ENABLED" : g_calls[i].second == STATE_DISABLED ? "DISABLED" : "DEFAULT");
	printf("\\n");
	g_calls.clear();
}
int main() {
	@autoreleasepool {
		TestApp* app = (TestApp*)[TestApp sharedApplication];
		CefBrowser b1(1), b2(2), b3(3);
		AfterCreated(&b1);
		AfterCreated(&b2);
		dump("created-no-reader");
		[app accessibilitySetValue:@YES forAttribute:@"AXFocusedUIElement"];
		dump("other-attribute");
		[app accessibilitySetValue:@YES forAttribute:@"AXEnhancedUserInterface"];
		dump("voiceover-on");
		AfterCreated(&b3);
		dump("created-with-reader");
		BeforeClose(&b2);
		[app accessibilitySetValue:@NO forAttribute:@"AXEnhancedUserInterface"];
		dump("voiceover-off");
		[app accessibilitySetValue:@YES forAttribute:@"AXManualAccessibility"];
		dump("manual-on");
	}
	return 0;
}
`);
	const bin = path.join(tmp, 'drv');
	execFileSync('clang++', ['-std=c++17', '-x', 'objective-c++', '-Wno-deprecated-declarations', '-I', tmp,
		'-o', bin, path.join(tmp, 'drv.mm'), '-framework', 'Cocoa'], { stdio: 'inherit' });
	const out = execFileSync(bin, { encoding: 'utf8' }).trim().split('\n');
	const step = {};
	for (const l of out) { console.log('  ' + l); const i = l.indexOf(':'); step[l.slice(0, i)] = l.slice(i + 1).trim(); }

	assert.strictEqual(step['created-no-reader'], '', 'browsers created without a screen reader were touched (behaviour must not change)');
	assert.strictEqual(step['other-attribute'], '', 'an unrelated accessibility attribute changed the state');
	assert.strictEqual(step['voiceover-on'], '1=ENABLED 2=ENABLED', 'VoiceOver on did not enable accessibility in the open browsers');
	assert.strictEqual(step['created-with-reader'], '3=ENABLED', 'a browser created while VoiceOver runs was not enabled');
	assert.strictEqual(step['voiceover-off'], '1=DISABLED 3=DISABLED', 'VoiceOver off: open browsers not disabled, or a closed one touched');
	assert.strictEqual(step['manual-on'], '1=ENABLED 3=ENABLED', 'AXManualAccessibility did not enable accessibility');

	console.log('PASS #1872: screen reader on/off reaches every browser via SetAccessibilityState; no change without one');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}

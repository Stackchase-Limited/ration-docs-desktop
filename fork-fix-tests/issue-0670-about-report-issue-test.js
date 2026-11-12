/*
 * #670 - '"Report issue" button/link in About': the About screen gave no way
 * to find where to report a problem.
 *
 * Cause: desktop-apps common/loginpage/src/panelabout.js (ViewAbout
 * paneltemplate) renders version, changelog, site and the open-source
 * notices, but no support/report link.
 * Fix: a "Report an issue" link to https://ration.works/support - the
 * product's support address already defined as SUPPORT_URL in
 * package/Makefile - under the changelog link; and the same link in the
 * native macOS About window (macos/.../About/ASCAboutController.m), which is
 * what Mac users see instead of the start page panel.
 *
 * This test extracts the real paneltemplate (brace matching), renders it with
 * stub options/strings, and checks the About HTML has a link to the support
 * URL read from package/Makefile, with a caption (baseline: no such link ->
 * FAILS); then checks (source only, compiled but not run) that the macOS
 * About controller adds a button whose action opens that URL.
 *
 * NOT claimed: how the link opens in the running app (target="popup" like
 * the changelog and source links; GUI check), that the page at that URL
 * exists (it is the address our packaging already publishes).
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      BASELINE=1 reads it from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || 'ab21b214c8^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', APPS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(APPS, rel), 'utf8');
}

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}

const supportUrl = (src('package/Makefile').match(/^SUPPORT_URL\s*\?=\s*(\S+)/m) || [])[1];
assert.ok(supportUrl, 'no SUPPORT_URL in package/Makefile - test is stale');

const about = src('common/loginpage/src/panelabout.js');
const at = about.indexOf('ViewAbout.prototype.paneltemplate = function(args)');
assert.ok(at !== -1, 'paneltemplate not found - test is stale');

// every string key resolves to "[key]" so we can see which caption is used
const Lang = new Proxy({}, { get: (t, k) => typeof k === 'string' ? `[${k}]` : undefined });
const window = { utils: { inParams: {} } };
const tpl = new Function('utils', 'window', 'navigator', 'version',
	'return function(args) ' + block(about, at) + ';')(
	{ Lang }, window, { appVersion: '' }, () => 'Version');
const html = tpl({ opts: { appname: 'Ration Docs', version: '9.4.0', changelog: 'https://ration.works/releases',
	link: 'https://ration.works', site: 'ration.works', rights: '(c)', logocls: '' } });
assert.ok(/ossViewSource/.test(html), 'stub harness broken: About not rendered');

const links = [...html.matchAll(/<a\b[^>]*href="([^"]*)"[^>]*>([^<]*)<\/a>/g)].map((m) => ({ href: m[1], text: m[2].trim() }));
const report = links.find((l) => l.href === supportUrl);
console.log('SUPPORT_URL', supportUrl, '| About links:', links.map((l) => l.href).join(' '));
assert.ok(report, 'About has no link to the support page');
assert.ok(report.text.length > 0, 'the report link has no caption');
console.log('report link caption:', report.text);
const loc = src('common/loginpage/src/locale.js');
const key = report.text.replace(/[[\]]/g, '');
assert.ok(new RegExp(`\\b${key}:\\s*'[^']+'`).test(loc), `caption key ${key} missing from locale.js`);

// macOS shows its own native About window (ASCAboutController), not the start page panel.
// Source check only: the Objective-C was compiled (-fsyntax-only) but not run here.
const mac = src('macos/ONLYOFFICE/Code/Controllers/About/ASCAboutController.m');
const loadAt = mac.indexOf('- (void)viewDidLoad');
const viewDidLoad = mac.slice(loadAt, mac.indexOf('\n}', loadAt));
const act = (viewDidLoad.match(/setAction:@selector\((\w+):\)/) || [])[1];
const actAt = act ? mac.indexOf(`- (void)${act}:`) : -1;
const opens = actAt !== -1 && mac.slice(actAt, mac.indexOf('\n}', actAt)).includes(`URLWithString:@"${supportUrl}"`);
const added = /infoStackView (addArrangedSubview|insertArrangedSubview):reportButton/.test(viewDidLoad);
console.log(`macOS About: button action ${act || '-'} opens support URL: ${opens}, added to the window: ${added}`);
assert.ok(opens && added, 'the macOS About window has no link to the support page');

console.log('PASS #670: About has a "Report an issue" link to ' + supportUrl);

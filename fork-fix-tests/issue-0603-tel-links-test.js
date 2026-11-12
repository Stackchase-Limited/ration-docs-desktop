/*
 * #603 - "tel:+910000000000" could not be used as a hyperlink: the dialog said
 * the link must look like "http://www.example.com".
 *
 * Cause (sdkjs common/editorscommon.js): every place that decides whether a
 * link already carries a protocol - getUrlType (the hyperlink dialogs of all
 * editors, through api.asc_getUrlType), prepareUrl (PDF viewer links, cell
 * autoformat), the builder API - uses AscCommon.rx_allowedProtocols, which
 * knew http(s), ftp(s), file, tessa, joplin, smb and mailto. "tel:..." was
 * Invalid (the dialog error; the desktop only lets it through for a local
 * file, by its IsLocalFile exception in apiBase.js) and prepareUrl made it
 * "http://tel:...". In the desktop app a click on a tel: link then reached
 * the #1664 link policy (desktop-sdk link_policy.h), which asked "Open this
 * link in another application?" on every click.
 *
 * Fix:
 * - sdkjs: "^tel:" is an allowed protocol like mailto:. getUrlType reports it
 *   as Unsafe (not a web address: the dialogs keep it as typed, the browser
 *   editors still warn before opening it), prepareUrl leaves it alone.
 * - desktop-sdk: NSLinkPolicy::Classify opens "tel:" + a phone number
 *   (digits, RFC 3966 visual separators, optional ;param=value) like mailto:;
 *   other text after tel: is still asked about, and "tel:x.exe" is refused.
 *
 * This extracts the REAL regexes, getUrlType and prepareUrl from
 * editorscommon.js and runs them, and compiles the REAL link_policy.h with
 * c++ and runs Classify on a table of links.
 *
 * NOT claimed: the dialog as drawn and the system's handling of tel: (which
 * application opens, whether it asks before dialling) - needs a GUI check.
 *
 * RD_REPO overrides the sdkjs checkout (default ../sdkjs), RD_SDK the
 * desktop-sdk one (default ../desktop-sdk). BASELINE=1 reads the parents of
 * the fix commits (BASE_REF, SDK_BASE_REF), where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const SDK = process.env.RD_SDK || path.resolve(__dirname, '..', 'desktop-sdk');
// Pinned to the parents of the commits that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'f7223cbbb5^';
const SDK_BASE_REF = process.env.SDK_BASE_REF || '9cda0a45^';

function read(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
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
function extract(source, marker) {
	const at = source.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(source, at);
}
function regexLine(source, name) {
	const m = new RegExp('\\n\\s*' + name + '\\s*=\\s*(/.*/[a-z]*),[ \\t]*(//[^\\n]*)?\\n').exec(source);
	assert.ok(m, name + ' not found');
	return m[1];
}

let failed = 0;
function check(what, fn) {
	try { fn(); console.log('ok   ' + what); }
	catch (e) { failed++; console.log('FAIL ' + what + ': ' + e.message); }
}

/* ---------- sdkjs: getUrlType / prepareUrl ---------- */
const ec = read(SDKJS, BASE_REF, 'common/editorscommon.js');
const names = ['emailRe', 'ipRe', 'hostnameRe', 'localRe', 'fileRe', 'rx_allowedProtocols'];
const c_oAscUrlType = { Invalid: 0, Http: 1, Email: 2, Unsafe: 3 };
String.prototype.strongMatch = function (reg) {
	const m = this.match(reg);
	return !!(m && m.length > 0 && m[0].length === this.length);
};
const src = 'var ' + names.map(n => n + ' = ' + regexLine(ec, n)).join(',\n') + ';\n' +
	extract(ec, 'function isValidFileUrl(') + '\n' +
	extract(ec, 'function getUrlType(') + '\n' +
	extract(ec, 'function prepareUrl(') + '\n' +
	'return { getUrlType: getUrlType, prepareUrl: prepareUrl, rx_allowedProtocols: rx_allowedProtocols };';
const lib = new Function('AscCommon', 'AscBrowser', src)({ c_oAscUrlType }, { isIE: false });

for (const url of ['tel:+910000000000', 'tel:+1-201-555-0123', 'TEL:5550123;ext=12']) {
	check(`getUrlType("${url}") is a link (Unsafe, kept as typed by the dialogs)`, () =>
		assert.strictEqual(lib.getUrlType(url), c_oAscUrlType.Unsafe));
	check(`prepareUrl("${url}") keeps it`, () =>
		assert.strictEqual(lib.prepareUrl(url, lib.getUrlType(url)), url));
}
/* unchanged on both trees */
check('http and mailto unchanged', () => {
	assert.strictEqual(lib.getUrlType('www.example.com'), c_oAscUrlType.Http);
	assert.strictEqual(lib.prepareUrl('www.example.com', c_oAscUrlType.Http), 'http://www.example.com');
	assert.strictEqual(lib.prepareUrl('a@example.com', c_oAscUrlType.Email), 'mailto:a@example.com');
	assert.strictEqual(lib.prepareUrl('mailto:a@example.com', c_oAscUrlType.Email), 'mailto:a@example.com');
});
check('"tel:" only counts at the start of the link', () =>
	assert.strictEqual(lib.rx_allowedProtocols.test('hotel:123'), false));

/* ---------- desktop-sdk: link policy ---------- */
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rd603-'));
try {
	fs.writeFileSync(path.join(tmp, 'link_policy.h'), read(SDK, SDK_BASE_REF, 'ChromiumBasedEditors/lib/src/link_policy.h'));
	fs.writeFileSync(path.join(tmp, 'main.cpp'), `#include "link_policy.h"
#include <cstdio>
int main(int argc, char** argv) {
	for (int i = 1; i < argc; ++i) printf("%d\\n", (int)NSLinkPolicy::Classify(argv[i]).Kind);
	return 0;
}
`);
	execFileSync('c++', ['-std=c++11', '-o', path.join(tmp, 'lp'), path.join(tmp, 'main.cpp')]);
	const table = [
		['tel:+910000000000', 0], ['tel:+1-201-555-0123', 0], ['tel:+1%20(201)%20555-0123', 0],
		['tel:5550123;ext=12;phone-context=example.com', 0], ['TEL:*21#', 0],
		['tel:', 1], ['tel:call-me', 1], ['tel:+1/../x', 1], ['tel:x.exe', 2],
		['mailto:a@example.com', 0], ['https://example.com', 0], ['zoommtg:123', 1],
	];
	const out = execFileSync(path.join(tmp, 'lp'), table.map(t => t[0]), { encoding: 'utf8' }).trim().split('\n').map(Number);
	const kinds = ['open', 'ask', 'refuse'];
	table.forEach(([url, want], i) => check(`link policy: ${url} -> ${kinds[want]}`, () =>
		assert.strictEqual(kinds[out[i]], kinds[want])));
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}

if (failed) {
	console.log(`${failed} check(s) FAILED`);
	process.exit(1);
}
console.log('PASS #603 tel: links');

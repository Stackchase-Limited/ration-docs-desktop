/*
 * RD-0052 (found in passing, UPSTREAM_TRIAGE.md "Latent problems") - copying
 * spreadsheet cells that carry an external hyperlink put malformed HTML on the
 * clipboard.
 *
 * _makeNodesFromCellValueStr (cell/model/clipboard.js) is the string builder
 * behind _generateHtmlDocStr, the HTML a range copy puts on the clipboard. For
 * a cell with an external link it opened `<a href=...` and closed every
 * fragment with `</span>`, so the <a> was never closed; and it pasted
 * hyperlink.Hyperlink / hyperlink.Tooltip into the attributes raw, so a
 * double quote in a URL or tooltip (both user data - HYPERLINK() builds the
 * URL from cell text) ended the attribute and the rest became markup. Its DOM
 * twin _makeNodesFromCellValue gets both right (createElement, .href, .title).
 * Fix: a link fragment ends with </a>; href and title go through
 * CopyPasteCorrectString like the fragment text.
 *
 * Runs the REAL _makeNodesFromCellValueStr (extracted by brace matching) and the
 * REAL CopyPasteCorrectString (common/wordcopypaste.js) against stub fragments
 * and a stub cell.
 * Claimed: link markup is <a ...>text</a> per fragment with href/title that
 * decode to the original strings, and nothing outside the attributes; plain
 * cells still give <span ...>text</span>.
 * NOT claimed: how a target application parses it, or internal-location links
 * (still copied as plain spans, as in the DOM twin - by design upstream).
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the sources at
 * BASE_REF with git show, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '63d44e1c43^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
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
function extract(rel, marker) {
	const src = read(rel);
	const at = src.indexOf(marker);
	assert.notStrictEqual(at, -1, marker + ' not found in ' + rel);
	return block(src, at);
}

const correct = new Function('return function (str) ' +
	extract('common/wordcopypaste.js', 'function CopyPasteCorrectString(str)'))();
const makeStr = new Function('Asc', 'AscCommon', 'number2color', 'CopyPasteCorrectString',
	'return function (val, defFN, defFS, cell) ' +
	extract('cell/model/clipboard.js', '_makeNodesFromCellValueStr: function (val, defFN, defFS, cell)'))(
	{ EUnderline: { underlineNone: 0 } },
	{ vertalign_SubScript: 1, vertalign_SuperScript: 2 },
	(rgb) => '#' + rgb.toString(16).padStart(6, '0'),
	correct);

function frag(text) {
	return {
		getFragmentText: () => text,
		format: {
			getSkip: () => false, getName: () => 'Arial', getSize: () => 10, getColor: () => null,
			getVerticalAlign: () => 0, getBold: () => false, getItalic: () => false,
			getUnderline: () => 0, getStrikeout: () => false,
		},
	};
}
function cellWith(link) {
	return { getEffectiveHyperlink: () => link };
}
function unescape(s) {
	return s.replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

let failed = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + ': ' + e.message); }
}

const URL = 'https://example.com/q?a="x" onmouseover="alert(1)';
const TIP = 'say "hi" <b>';
const link = { Hyperlink: URL, Tooltip: TIP, getLocation: () => null };

check('external link: each fragment is <a ...>text</a> with href/title intact', () => {
	const html = makeStr([frag('one'), frag('two')], 'Arial', 10, cellWith(link));
	const re = /<a href="([^"<>]*)" title="([^"<>]*)"\s*style="[^"<>]*">([^<]*)<\/a>/g;
	const parts = [];
	let m, rest = html;
	while ((m = re.exec(html))) parts.push(m);
	rest = html.replace(re, '');
	assert.strictEqual(rest, '', 'markup outside the link elements: ' + JSON.stringify(rest) + ' in ' + html);
	assert.strictEqual(parts.length, 2, html);
	for (const p of parts) {
		assert.strictEqual(unescape(p[1]), URL, 'href');
		assert.strictEqual(unescape(p[2]), TIP, 'title');
	}
	assert.deepStrictEqual(parts.map((p) => p[3]), ['one', 'two']);
});
check('control: a cell without a link is <span ...>text</span>', () => {
	const html = makeStr([frag('a<b')], 'Arial', 10, cellWith(null));
	assert.match(html, /^<span\s+style="[^"]*">a&lt;b<\/span>$/);
});

console.log(failed ? `FAIL: ${failed} check(s)` : 'PASS: copied link markup is well formed');
process.exit(failed ? 1 : 0);

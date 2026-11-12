/*
 * #1952 - "Home Dashboard: Preview File Name and File Path on Hover": in the
 * start page Recent list, files with similar or cut-off names in long folders
 * could not be told apart; the reporter asked for the full name and location
 * on hover.
 *
 * Cause: desktop-apps common/loginpage/src/panelrecent.js listitemtemplate gave
 * the name column title="<file name>" and the location column title="<folder>",
 * so no tooltip held the whole path, and the search-history rows (_render_history)
 * did not even pass the path to the template.
 * Fix: the name column's title is the full path (info.path for files, info.full
 * for recent folders, the name when neither is known); _render_history passes
 * row.path.
 *
 * This test extracts the real listitemtemplate and escapeHtml and renders
 *  1. a recent file row: the name tooltip must be the full path (baseline: just
 *     the name -> FAILS);
 *  2. a recent folder row: the tooltip must be the folder's full path;
 *  3. a row with no path (fallback): the tooltip is the name, as before;
 *  4. a path with markup and quotes stays escaped in the attribute;
 *  5. the real _render_history info literal carries path (baseline: no).
 *
 * NOT claimed: how the native tooltip looks in the app (CEF shows title
 * attributes itself; not GUI-checked); no middle-ellipsis of the visible text.
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || 'a1c23fcfb^';

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
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.ok(at !== -1, marker + ' not found - test is stale');
	return block(text, at);
}

const recent = src('common/loginpage/src/panelrecent.js');
const esc = extract(src('common/loginpage/src/htmlutils.js'), 'function escapeHtml(value)');
const tpl = 'function ' + extract(recent, 'listitemtemplate: function (info)').replace(/^listitemtemplate: function /, '');
const listitemtemplate = new Function('isSvgIcons', esc + '\nreturn ' + tpl + ';')(true);

function nameTitle(info) {
	const html = listitemtemplate(info);
	const m = /class="col-name" title="([^"]*)"/.exec(html);
	assert.ok(m, 'no col-name title in row');
	return m[1];
}

let failed = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failed++; console.log('FAIL ' + label + ': ' + e.message); }
}

check('file row: name tooltip is the full path', () => {
	const t = nameTitle({ uid: 'a', name: 'MyFile_Draft-1.docx', descr: '/Users/me/Projects/Long folder/2024',
		path: '/Users/me/Projects/Long folder/2024/MyFile_Draft-1.docx', type: 65, format: 'docx', date: '' });
	console.log('     title="' + t + '"');
	assert.strictEqual(t, '/Users/me/Projects/Long folder/2024/MyFile_Draft-1.docx');
});
check('folder row: tooltip is the folder path', () => {
	const t = nameTitle({ uid: 'f', type: 'folder', name: '2024', full: 'C:\\Work\\2024', descr: 'C:\\Work' });
	assert.strictEqual(t, 'C:\\Work\\2024');
});
check('no path known: tooltip falls back to the name', () => {
	assert.strictEqual(nameTitle({ uid: 'b', name: 'x.xlsx', descr: '', type: 257, format: 'xlsx', date: '' }), 'x.xlsx');
});
check('path stays escaped in the attribute', () => {
	const t = nameTitle({ uid: 'c', name: 'a.docx', descr: '/t', path: '/t/"><img src=x>a.docx', type: 65, format: 'docx', date: '' });
	assert.ok(!/[<>"]/.test(t), 'unescaped markup in title: ' + t);
});
check('search-history rows pass the path to the template', () => {
	const hist = extract(recent, 'function _render_history(rows, terms)');
	const lit = block(hist, hist.indexOf('const info = {'));
	assert.ok(/\bpath:\s*row\.path\b/.test(lit), 'history info has no path');
});

if (failed) { console.log(failed + ' check(s) failed'); process.exit(1); }
console.log('PASS #1952 recent list tooltips give the full path');

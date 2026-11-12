/*
 * #1363 - "Be transparent about opening a webpage when clicking on buttons"
 * (editor part: the button the report shows; the start page's About links are
 * issue-1363-start-page-web-links-test.js).
 *
 * In every editor the left bar has a "Feedback & Support" button among buttons
 * that act on the document (search, comments, navigation, ...). Its click does
 * window.open(customization.feedback.url or SUPPORT_URL), which the desktop app
 * hands to the system's web browser, but its tooltip - also its caption when
 * the bar overflows into the "more" menu (SideMenu uses btn.hint) - was just
 * "Feedback & Support".
 *
 * Fix: web-apps apps/<editor>/main/app/view/LeftMenu.js, for documenteditor,
 * spreadsheeteditor, presentationeditor, pdfeditor and visioeditor: the hint is
 * tipSupport + ' (' + tipOpensInBrowser + ')' -> "Feedback & Support (opens in
 * your web browser)"; new key <P>.Views.LeftMenu.tipOpensInBrowser in en.json.
 *
 * This test extracts, for each editor, the real `this.btnSupport = new
 * Common.UI.Button({...})` options object by brace matching, evaluates it with
 * `this` set to the view's real string defaults (the "name: '...'" members of
 * the same file) and checks that the hint says the browser opens (baseline: it
 * does not -> FAILS); and that en.json carries any new string the hint uses.
 *
 * NOT claimed: rendering of the tooltip (GUI check); other languages show the
 * English note until translated.
 *
 * Env: RD_REPO  web-apps checkout (default ../web-apps)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '73e0f992ea^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
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

const editors = { documenteditor: 'DE', spreadsheeteditor: 'SSE', presentationeditor: 'PE', pdfeditor: 'PDFE', visioeditor: 'VE' };
let failed = 0;
for (const [ed, prefix] of Object.entries(editors)) {
	const text = src(`apps/${ed}/main/app/view/LeftMenu.js`);
	const at = text.indexOf('this.btnSupport = new Common.UI.Button(');
	assert.ok(at !== -1, `${ed}: btnSupport not found - test is stale`);
	const optsSrc = block(text, at);

	// the view's string members, as the view object has them
	const view = {};
	for (const m of text.matchAll(/^\s+(\w+)\s*:\s*'((?:[^'\\]|\\.)*)'\s*,?\s*$/gm)) view[m[1]] = m[2];
	const $markup = { elementById: () => null };
	const opts = new Function('$markup', 'return ' + optsSrc + ';').call(view, $markup);
	const locale = JSON.parse(src(`apps/${ed}/main/locale/en.json`));

	const used = [...optsSrc.matchAll(/this\.(\w+)/g)].map(m => m[1]).filter(k => k !== 'tipSupport');
	const missing = used.filter(k => locale[`${prefix}.Views.LeftMenu.${k}`] === undefined);

	const ok = /web browser/i.test(opts.hint) && /Feedback & Support/.test(opts.hint) && !missing.length;
	console.log(`${ed}: hint ${JSON.stringify(opts.hint)}${missing.length ? ' (missing in en.json: ' + missing.join(', ') + ')' : ''} -> ${ok ? 'ok' : 'FAIL'}`);
	ok || failed++;
}
assert.strictEqual(failed, 0, `${failed} editor(s): "Feedback & Support" opens the web browser but its tooltip does not say so`);
console.log('PASS #1363: the editors\' Feedback & Support button says it opens the web browser');

/*
 * ONLYOFFICE 10.0 security backport - "Fixed XSS vulnerability in the HTML
 * plugin when pasting into a document" (sdkjs aa931c1380, bug 83739).
 *
 * Plugins insert HTML with executeMethod("PasteHtml", [html]) (the HTML
 * plugin, macros, AI plugins). sdkjs common/apiBase_plugins.js
 * _pluginMethod_PasteHtml built a <div> in the EDITOR's own document and set
 * its innerHTML to that text before handing it to the paste processor, so an
 * event handler in it - <img src=x onerror=...> - ran in the editor frame,
 * with the editor's window and window.AscDesktopEditor. Upstream now builds
 * the element inside a hidden iframe with sandbox="allow-same-origin" (no
 * allow-scripts): the paste processor can still read it, nothing in it runs.
 * Cherry-picked with one conflict (our 9.4 function has no `options` / native
 * branch).
 *
 * This lifts the REAL _pluginMethod_PasteHtml by brace matching and runs it
 * in headless Chromium (a real DOM, so the sandbox is real) with a stub api
 * whose asc_PasteData records what it was handed.
 *
 * Claimed: an onerror handler in pasted HTML does not run; the element the
 * paste processor receives still carries the HTML (text, <b>) and the
 * caller's callback fires; the helper element is removed afterwards.
 * NOT claimed: the real paste processor's output for every construct (checked
 * once in the headless word editor, see the report); the GUI app.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the source
 * with `git show $BASE_REF:` and must FAIL. PLAYWRIGHT / RD_CHROME as in
 * issue-1664-paste-webp-test.js.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'b468963a2e^';
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const src = read('common/apiBase_plugins.js');
const marker = 'Api.prototype._pluginMethod_PasteHtml = function';
const at = src.indexOf(marker);
if (at < 0) { console.log('FAIL _pluginMethod_PasteHtml not found - the extractor needs updating'); process.exit(1); }
const fnSrc = matched(src, src.indexOf('function', at));

(async () => {
	const { chromium } = require(PLAYWRIGHT);
	const browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
	const page = await browser.newPage();
	await page.setContent('<!DOCTYPE html><html><head><style>body{font-family:Arial}</style></head><body class="theme-light"></body></html>');
	const r = await page.evaluate(async (fnSrc) => {
		window.AscCommon = {
			g_clipboardBase: { bSaveFormat: true },
			c_oEditorId: { Word: 0, Spreadsheet: 1, Presentation: 2 },
			c_oAscClipboardDataFormat: { HtmlElement: 4 },
		};
		window.__ran = 0;
		const seen = {};
		const api = {
			editorId: 1, // spreadsheet: no logic-document cursor update after the paste
			canEdit: () => true,
			asc_getCellInfo: () => ({ font: { size: 11, bold: false, italic: false } }),
			executeGroupActionsStart() {}, executeGroupActionsEnd() {},
			incrementCounterLongAction() {}, decrementCounterLongAction() {},
			checkLongActionCallback: () => true,
			getEditorId() { return 1; },
			asc_PasteData(fmt, elem, a, b, c, done) {
				seen.inEditorDoc = elem.ownerDocument === document;
				seen.html = elem.innerHTML;
				seen.text = elem.textContent;
				seen.hasBold = !!elem.querySelector('b');
				// the processor runs after a tick in the editors; let an onerror fire meanwhile
				setTimeout(done, 300);
			},
		};
		const paste = eval('(' + fnSrc + ')');
		const done = await new Promise(res => {
			paste.call(api, '<b>Hello</b> world<img src="x:broken" onerror="(window.top||window).__ran=1">', () => res(true));
			setTimeout(() => res(false), 3000);
		});
		await new Promise(r => setTimeout(r, 300));
		return { done, ran: window.__ran, seen, leftover: !!document.getElementById('pmpastehtml') ||
			[...document.querySelectorAll('iframe')].some(f => f.contentDocument && f.contentDocument.getElementById('pmpastehtml')) };
	}, fnSrc);
	await browser.close();

	let failures = 0;
	const check = (name, ok, detail) => { if (!ok) failures++; console.log((ok ? 'ok   ' : 'FAIL ') + name + (detail ? ': ' + detail : '')); };
	check('an onerror handler in pasted HTML does not run in the editor', r.ran === 0, 'handler ran=' + r.ran + ', element in editor document=' + r.seen.inEditorDoc);
	check('the paste processor still gets the HTML', r.seen.text === 'Hello world' && r.seen.hasBold, JSON.stringify(r.seen.text));
	check('the caller callback fires and the helper element is removed', r.done && !r.leftover);
	console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed');
	process.exit(failures ? 1 : 0);
})().catch(e => { console.log('FAIL ' + (e && e.stack || e)); process.exit(1); });

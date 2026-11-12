/*
 * #206 - "paste paragraphs correctly from LibreOffice": bold/italic came across from a
 * LibreOffice Writer copy, the gaps between paragraphs did not.
 *
 * LibreOffice puts HTML on the clipboard with the paragraph style's spacing in the
 * document's style sheet, not on each paragraph:
 *     <style> p { line-height: 115%; margin-bottom: 0.25cm; background: transparent } </style>
 *     <p style="line-height: 100%; margin-bottom: 0cm">Default Paragraph Style</p>
 *     <p>Text Body</p>
 * PasteProcessor._set_pPr (common/wordcopypaste.js) read margin-top/margin-bottom only from
 * the paragraph's inline style (node.style) - on purpose, as the computed value includes
 * the browser's own 1em <p> margins - so a Text Body paragraph got no space after; its
 * line height came from the computed px value as an "at least" height. The pasted text
 * then took the destination document's spacing (in 9.4's blank template 10pt after, so a
 * new document hides it; a document with no spacing shows the reported run-together text).
 * Now, when there is no inline value, margins and line-height declared for the paragraph by
 * the pasted HTML's own style sheets are used (_getDeclaredStyle); browser defaults are
 * still ignored.
 *
 * What runs: the REAL _getDeclaredStyle (when present), _getStyle, _isEmptyProperty and the
 * Spacing part of _set_pPr, extracted by brace matching, plus the REAL valueToMmType /
 * valueToMm (editorscommon.js), in headless Chromium (Playwright) on paragraphs of a
 * LibreOffice-style HTML written into an iframe with document.write - as
 * CommonIframe_PasteStart does. The paragraph is a stub recording Set_Spacing.
 *
 * Claimed: Text Body -> After 2.5 mm, line 1.15 (auto); inline Default style -> After 0,
 * line 1.0; a bare <p> with no style sheet gets no spacing (no browser 1em leak); an inline
 * value still beats the sheet. NOT claimed: the exact LibreOffice clipboard of every LO
 * version (the sample follows LO 6/7 HTML export; no LibreOffice on this machine), the GUI
 * paste, CSS specificity (later matching rules win), RTF paste.
 *
 * RD_REPO=<sdkjs> (default ../sdkjs). PLAYWRIGHT / RD_CHROME as in issue-1664-paste-webp-test.js.
 * BASELINE=1 reads the sources at BASE_REF (parent of the fix) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
// Pinned to the parent of the fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '19a6e7a7bd^';
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
function blockEnd(text, open) {
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return i + 1;
	}
	throw new Error('unbalanced braces');
}
/* `marker ... {...}` (unique), or null when absent */
function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return null;
	assert.notStrictEqual(at, -1, marker + ' not found');
	assert.strictEqual(text.indexOf(marker, at + 1), -1, marker + ' is not unique');
	return text.slice(at, blockEnd(text, text.indexOf('{', at)));
}

const paste = src('common/wordcopypaste.js');
const common = src('common/editorscommon.js');

/* PasteProcessor methods are object-literal members: "name: function (...) {...}" */
const methods = ['_getDeclaredStyle: function', '_getStyle: function', '_isEmptyProperty: function']
	.map((m) => extract(paste, m, m.startsWith('_getDeclaredStyle')))
	.filter(Boolean);
const spacingStart = paste.indexOf('var Spacing = new AscWord.ParaSpacing();');
assert.notStrictEqual(spacingStart, -1, 'Spacing block not found');
const setAt = paste.indexOf('if (false === this._isEmptyProperty(Spacing)) {', spacingStart);
const spacingBlock = paste.slice(spacingStart, blockEnd(paste, paste.indexOf('{', setAt)));
assert(/Para\.Set_Spacing\(Spacing\)/.test(spacingBlock), 'Spacing block does not end in Set_Spacing');
const valueFns = extract(common, 'function valueToMmType(value)') + '\n' + extract(common, 'function valueToMm(value)');

const LO_HTML = `<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">
<html><head><meta http-equiv="content-type" content="text/html; charset=utf-8"/><title></title>
<meta name="generator" content="LibreOffice 7.3.7.2 (Linux)"/>
<style type="text/css">
	@page { size: 21cm 29.7cm; margin: 2cm }
	p { line-height: 115%; margin-bottom: 0.25cm; background: transparent }
</style></head>
<body lang="en-US" link="#000080" vlink="#800000" dir="ltr">
<p id="def" style="line-height: 100%; margin-bottom: 0cm">Default <b>paragraph</b> style</p>
<p id="body">Text body <i>paragraph</i></p>
<p id="inline" style="margin-bottom: 0.5cm">inline beats the sheet</p>
</body></html>`;
const PLAIN_HTML = '<html><body><p id="plain">no style sheet</p></body></html>';

(async () => {
	const { chromium } = require(PLAYWRIGHT);
	const browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
	const page = await browser.newPage();
	const run = (html, id) => page.evaluate(({ html, id, methods, spacingBlock, valueFns }) => {
		const AscCommon = { g_dKoef_pix_to_mm: 25.4 / 96 };
		const AscCommonWord = { g_dKoef_in_to_mm: 25.4, g_dKoef_pt_to_mm: 25.4 / 72, g_dKoef_pc_to_mm: 25.4 / 6, g_dKoef_em_to_mm: 25.4 / 6 };
		new Function('AscCommon', 'AscCommonWord', valueFns + '\nAscCommon.valueToMmType = valueToMmType; AscCommon.valueToMm = valueToMm;')(AscCommon, AscCommonWord);
		const proc = new Function('return {' + methods.join(',\n') + '};')();
		const iframe = document.createElement('iframe');
		document.body.appendChild(iframe);
		iframe.contentWindow.document.open();
		iframe.contentWindow.document.write(html);
		iframe.contentWindow.document.close();
		const node = iframe.contentWindow.document.getElementById(id);
		let got = null;
		const Para = { Set_Spacing(s) { got = { Before: s.Before, After: s.After, Line: s.Line, LineRule: s.LineRule }; } };
		function ParaSpacing() { this.Line = undefined; this.LineRule = undefined; this.Before = undefined; this.After = undefined; }
		const computedStyle = iframe.contentWindow.getComputedStyle(node, null);
		new Function('node', 'Para', 'computedStyle', 'AscCommon', 'AscWord', 'Asc', spacingBlock)
			.call(proc, node, Para, computedStyle, AscCommon, { ParaSpacing }, { linerule_Auto: 'auto', linerule_AtLeast: 'atLeast' });
		iframe.remove();
		return got;
	}, { html, id, methods, spacingBlock, valueFns });

	let failures = 0;
	const near = (a, b) => typeof a === 'number' && Math.abs(a - b) < 1e-6;
	async function check(name, fn) {
		try { await fn(); console.log('ok   ' + name); }
		catch (e) { failures++; console.log('FAIL ' + name + '\n     ' + e.message); }
	}

	await check('LibreOffice Text Body paragraph keeps 0.25 cm after and 115% line spacing', async () => {
		const s = await run(LO_HTML, 'body');
		assert(s, 'no spacing set at all');
		assert(near(s.After, 2.5), 'After = ' + s.After + ' mm, want 2.5');
		assert(near(s.Line, 1.15) && s.LineRule === 'auto', 'Line = ' + s.Line + ' ' + s.LineRule + ', want 1.15 auto');
	});
	await check('LibreOffice Default Paragraph Style (inline) keeps 0 after and single spacing', async () => {
		const s = await run(LO_HTML, 'def');
		assert(near(s.After, 0), 'After = ' + s.After);
		assert(near(s.Line, 1) && s.LineRule === 'auto', 'Line = ' + s.Line + ' ' + s.LineRule);
	});
	await check('an inline margin still beats the style sheet', async () => {
		const s = await run(LO_HTML, 'inline');
		assert(near(s.After, 5), 'After = ' + s.After);
	});
	await check('a bare <p> without a style sheet gets no margins (browser 1em default ignored)', async () => {
		const s = await run(PLAIN_HTML, 'plain');
		assert(!s || (s.After == null && s.Before == null), 'got ' + JSON.stringify(s));
	});

	await browser.close();
	console.log(failures ? `\n${failures} check(s) failed` : '\nall checks passed');
	process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

/*
 * #2180 - "SVG clipboard support": a picture copied in Inkscape cannot be
 * pasted as a picture.
 *
 * Inkscape offers the copy as image/svg+xml, image/png and text/plain - and its
 * text/plain is the whole SVG document (src/ui/clipboard.cpp _onGet maps the
 * text target to image/x-inkscape-svg). Chromium 109 (our CEF) does not expose
 * image/svg+xml to the page's paste event, and sdkjs common/clipboard_base.js
 * _private_onpaste takes text/plain before picture items, so the SVG SOURCE
 * was pasted as text.
 *
 * Fix: when text/plain is a whole SVG document and the clipboard also holds a
 * picture item, the desktop editor inserts the SVG as an image
 * (checkSvgDocumentPaste: data:image/svg+xml -> LocalFileGetImageUrl ->
 * Api._addImageUrl), like #676 does for file-manager images.
 *
 * This runs the REAL _private_onpaste, checkFileManagerImagePaste,
 * getFileManagerImagePaths, isSvgDocumentText and checkSvgDocumentPaste,
 * brace-matched out of clipboard_base.js, against a synthetic DataTransfer.
 *
 * Claimed: Inkscape's payload inserts one image whose data: URL decodes to the
 * exact SVG text (UTF-8 kept), and nothing is pasted as text; SVG code without
 * a picture alongside, ordinary text with a picture, and an SVG the native side
 * refuses all paste as text as before; non-desktop (no bridge) is unchanged.
 * NOT claimed: Chromium's real clipboard on Linux/Windows/macOS, the native
 * GetLocalImageUrl/CImageFileFormatChecker run on an SVG data: URL, how the
 * picture is drawn (needs a GUI check with Inkscape).
 *
 * RD_REPO=<sdkjs> (default ../sdkjs). BASELINE=1 reads clipboard_base.js at
 * BASE_REF with git show; it must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const REL = 'common/clipboard_base.js';
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '8c1cd0c54a^';
const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function extractMethod(src, name) {
	const at = src.indexOf('\n\t\t' + name + ' : function');
	if (at === -1) return null;
	const fnAt = src.indexOf('function', at);
	const open = src.indexOf('{', fnAt);
	let depth = 0;
	for (let i = open; i < src.length; i++) {
		if (src[i] === '{') depth++;
		else if (src[i] === '}' && --depth === 0) return src.slice(fnAt, i + 1);
	}
	throw new Error('unbalanced braces in ' + name);
}

const methods = {};
for (const n of ['_private_onpaste', 'getFileManagerImagePaths', 'checkFileManagerImagePaste',
	'isSvgDocumentText', 'checkSvgDocumentPaste'])
	methods[n] = extractMethod(source, n);
assert.ok(methods._private_onpaste && methods._private_onpaste.includes('let checkImages = function'),
	'_private_onpaste not found');

const SVG = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<!-- Created with Inkscape -->\n' +
	'<svg width="10mm" height="10mm" viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg">' +
	'<text x="1" y="5">Grüße</text><rect width="5" height="5" fill="#f00"/></svg>\n';
const pngItem = { kind: 'file', type: 'image/png', getAsFile: () => ({ name: 'x.png' }) };

function run(flavours, items, opts = {}) {
	const log = { pasteData: [], addImageUrl: [], localFileGetImageUrl: [], iframeHtml: [] };
	const clipboardData = {
		items, files: [],
		getData: (t) => (Object.prototype.hasOwnProperty.call(flavours, t) ? flavours[t] : ''),
	};
	const AscCommon = {
		c_oAscClipboardDataFormat: { Text: 1, Html: 2, Internal: 4, HtmlElement: 8 },
		g_specialPasteHelper: { specialPasteData: {} },
		g_oDocumentUrls: { getImageUrl: (u) => 'docurl/' + u },
	};
	const windowStub = {
		btoa: (s) => Buffer.from(s, 'latin1').toString('base64'),
		AscDesktopEditor: opts.web ? undefined : {
			IsImageFile: () => false,
			LocalFileGetImageUrl(u) {
				log.localFileGetImageUrl.push(u);
				return opts.refuse ? 'error' : 'media/image1.svg';
			},
		},
	};
	const cb = {};
	const make = (src) => new Function('g_clipboardBase', 'AscCommon', 'window',
		'"use strict"; return (' + src + ');')(cb, AscCommon, windowStub);
	cb.Api = {
		asc_IsFocus: () => true, isLongAction: () => false, incrementCounterLongAction() {},
		asc_PasteData(f, d) { log.pasteData.push([f, d]); },
		_addImageUrl(u) { log.addImageUrl.push(u); },
	};
	cb.IsNeedDivOnPaste = false;
	cb.ClosureParams = { _e: null, getData(t) { return this._e.clipboardData.getData(t); } };
	cb._console_log = () => {};
	cb.CommonIframe_PasteStart = (h) => log.iframeHtml.push(h);
	cb.Paste_End = () => {};
	for (const n in methods) if (methods[n]) cb[n] = make(methods[n]);
	// globals the extracted code reads
	global.unescape = unescape;
	cb._private_onpaste({ clipboardData, preventDefault() {} });
	return log;
}

let failed = 0;
function check(name, fn) {
	try { fn(); console.log('ok   - ' + name); } catch (e) { failed++; console.log('FAIL - ' + name + ': ' + e.message.split('\n')[0]); }
}

check('Inkscape copy (SVG as text/plain + a PNG) inserts the SVG as an image', () => {
	const log = run({ 'text/plain': SVG }, [pngItem]);
	assert.deepStrictEqual(log.pasteData, [], 'the SVG source was pasted as text');
	assert.deepStrictEqual(log.addImageUrl, [['docurl/media/image1.svg']]);
	const u = log.localFileGetImageUrl[0] || '';
	assert.ok(u.startsWith('data:image/svg+xml;base64,'), 'not an SVG data: URL');
	assert.strictEqual(Buffer.from(u.split(',')[1], 'base64').toString('utf8'), SVG.trim(), 'SVG bytes changed');
});

check('SVG code copied from a text editor (no picture) still pastes as text', () => {
	const log = run({ 'text/plain': SVG }, []);
	assert.deepStrictEqual(log.addImageUrl, []);
	assert.deepStrictEqual(log.pasteData, [[1, SVG]]);
});

check('ordinary text with a picture alongside still pastes as text', () => {
	const log = run({ 'text/plain': 'just <svg> text' }, [pngItem]);
	assert.deepStrictEqual(log.addImageUrl, []);
	assert.deepStrictEqual(log.pasteData, [[1, 'just <svg> text']]);
});

check('an SVG the native side refuses falls back to the text paste', () => {
	const log = run({ 'text/plain': SVG }, [pngItem], { refuse: true });
	assert.deepStrictEqual(log.addImageUrl, []);
	assert.deepStrictEqual(log.pasteData, [[1, SVG]]);
});

check('HTML on the clipboard still wins', () => {
	const log = run({ 'text/plain': SVG, 'text/html': '<html><body><b>x</b></body></html>' }, [pngItem]);
	assert.deepStrictEqual(log.addImageUrl, []);
	assert.strictEqual(log.iframeHtml.length, 1);
});

console.log(failed ? `${failed} check(s) failed` : 'all checks passed');
process.exit(failed ? 1 : 0);

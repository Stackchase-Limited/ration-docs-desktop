/*
 * DesktopEditors #1760 - "Onlyoffice desktop did not paste the image correctly"
 * (and #1740, same defect: "copying an image ... paste it on facebook showed a
 * camera icon"). Both on Linux Mint/Xorg: select a picture in a document, Ctrl+C,
 * paste into Facebook Messenger / a Facebook post / Google Lens in a browser ->
 * nothing, or a placeholder.
 *
 * Cause: the desktop copy goes through CClipboardBase.Copy_New
 * (common/clipboard_base.js), which asks api.asc_CheckCopy for Text | Html |
 * Internal | Image and writes ONE ClipboardItem; Image becomes image/png. Only
 * the spreadsheet asc_CheckCopy ever pushed Image. word/api.js and slide/api.js
 * asc_CheckCopy pushed text/html only, with the picture as
 * <img src="data:image/png;base64,..."> inside it. Targets that take images
 * only from image flavours (web uploaders, chat apps, image editors) saw no
 * image. Measured in headless Chromium with the real word and slide sdk: the
 * ClipboardItem had ["text/html"] (slide: ["text/plain","text/html"]); and in
 * rd-linux-verify (Xvfb, headed Chromium 138, x11) the X11 CLIPBOARD then offers
 * only text/html, and a web page's paste event gets no File.
 *
 * Fix: word and slide asc_CheckCopy push Image when drawings are selected
 * (word: IsDrawingSelected; slide: focus on the slide), from the new
 * baseEditorsApi.getSelectedDrawingsPng (common/apiBase.js), which renders the
 * selection like "Save as picture" (getImageDataForSaving(true, "image/png")).
 *
 * This extracts the REAL Copy_New, word and slide asc_CheckCopy and
 * getSelectedDrawingsPng by brace matching and drives them with stubs for the
 * editor model, the drawing controller and navigator.clipboard, and checks
 * which flavours reach the ClipboardItem.
 *
 * Claimed: picture selected -> image/png with exactly the rendered PNG bytes,
 * next to text/html; text selection, text inside a shape, slide thumbnails ->
 * no image/png. NOT claimed: the rendering itself (getImageDataForSaving is
 * stubbed - it was checked in the headless editor, 76x57 red PNG for a 76x57
 * red picture), or what the desktop CEF writes to the native clipboard (checked
 * for upstream Chromium 138 on X11 only, not in our CEF build or on Wayland).
 *
 *   node fork-fix-tests/issue-1760-copy-picture-image-png-test.js
 *   RD_REPO=<sdkjs checkout>   (default ../sdkjs)
 *   BASELINE=1                 runs against BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || '9f3cc5dd87^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
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

/* returns the function expression after `marker` (e.g. "X.prototype.f = function") */
function fn(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1) {
		if (optional) return null;
		throw new Error(marker + ' not found');
	}
	const start = text.indexOf('function', at);
	return block(text, start);
}

/* --- stubs --- */
const F = { Text: 1, Html: 2, Internal: 4, HtmlElement: 8, Rtf: 16, Image: 32 };
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==', 'base64');
const AscCommon = {
	c_oAscClipboardDataFormat: F,
	AscBrowser: { isWindows: false }, // read by word asc_CheckCopy since #927
	FOCUS_OBJECT_MAIN: 1,
	FOCUS_OBJECT_THUMBNAILS: 0,
	Base64: { decode: s => new Uint8Array(Buffer.from(s, 'base64')) },
	CopyProcessor: function () {
		this.Start = () => 'BINARY';
		this.getInnerHtml = () => '<img src="data:image/png;base64,' + PNG.toString('base64') + '">';
	},
};
const window = {};

const apiBase = src('common/apiBase.js');
const getSelectedDrawingsPngSrc = fn(apiBase, 'baseEditorsApi.prototype.getSelectedDrawingsPng = function', true);
const getSelectedDrawingsPng = getSelectedDrawingsPngSrc
	? new Function('AscCommon', 'return ' + getSelectedDrawingsPngSrc)(AscCommon)
	: function () { return null; }; // absent before the fix
const make = (file, marker) => new Function('AscCommon', 'window', 'return ' + fn(src(file), marker))(AscCommon, window);
const wordCheckCopy = make('word/api.js', 'asc_docs_api.prototype.asc_CheckCopy = function');
const slideCheckCopy = make('slide/api.js', 'asc_docs_api.prototype.asc_CheckCopy = function');

const written = [];
function ClipboardItem(o) { this.o = o; }
const navigator = { clipboard: { write(items) { written.push(items[0].o); return Promise.resolve(); } } };
const Copy_New = new Function('navigator', 'ClipboardItem', 'c_oAscClipboardDataFormat', 'Blob',
	'return ' + fn(src('common/clipboard_base.js'), '\n\t\tCopy_New : function'))(navigator, ClipboardItem, F, Blob);

function controller(opts) {
	return {
		getSelectedArray: () => (opts.selected ? [{}] : []),
		getTargetDocContent: () => (opts.inText ? {} : null),
		getImageDataForSaving: (force, fmt) => {
			assert.strictEqual(fmt, 'image/png');
			return { src: 'data:image/png;base64,' + PNG.toString('base64'), width: 1, height: 1 };
		},
	};
}

async function copy(checkCopy, logicDoc, ctl) {
	const api = {
		WordControl: { m_oLogicDocument: logicDoc },
		asc_CheckCopy: checkCopy,
		getGraphicController: () => ctl,
		getSelectedDrawingsPng,
		asc_IsFocus: () => true,
	};
	const base = {
		Api: api, isCopyEnabled: () => true, isCopyOutEnabled: () => true,
		lastCopyPush() {}, SendCopyEvent() {}, _isUseMobileNewCopy: () => false,
	};
	written.length = 0;
	assert.strictEqual(Copy_New.call(base, false, true), true, 'Copy_New threw inside');
	assert.strictEqual(written.length, 1, 'one ClipboardItem written');
	const out = {};
	for (const k of Object.keys(written[0])) out[k] = Buffer.from(await written[0][k].arrayBuffer());
	return out;
}

const wordDoc = drawing => ({ GetSelectedText: () => '', IsDrawingSelected: () => drawing, GetDocPosType: () => (drawing ? 3 : 0) });
const slideDoc = focus => ({ GetSelectedText: () => '', GetFocusObjType: () => focus });

(async () => {
	/* 1. document editor, picture selected: image/png with the rendered bytes, html still there */
	let item = await copy(wordCheckCopy, wordDoc(true), controller({ selected: true }));
	assert.ok(item['text/html'], 'text/html kept');
	assert.ok(item['image/png'], 'document editor: copied picture has no image/png flavour (only <img> inside text/html)');
	assert.ok(item['image/png'].equals(PNG), 'image/png carries the rendered PNG bytes');

	/* 2. document editor: text selection, or text inside a shape -> no image/png */
	item = await copy(wordCheckCopy, wordDoc(false), controller({ selected: true }));
	assert.ok(!item['image/png'], 'text selection must not put out an image');
	item = await copy(wordCheckCopy, wordDoc(true), controller({ selected: true, inText: true }));
	assert.ok(!item['image/png'], 'text being edited inside a shape must not put out an image');

	/* 3. presentation editor: object on the slide -> image/png; thumbnails focus -> none */
	item = await copy(slideCheckCopy, slideDoc(AscCommon.FOCUS_OBJECT_MAIN), controller({ selected: true }));
	assert.ok(item['image/png'], 'presentation editor: copied object has no image/png flavour');
	assert.ok(item['image/png'].equals(PNG));
	item = await copy(slideCheckCopy, slideDoc(AscCommon.FOCUS_OBJECT_THUMBNAILS), controller({ selected: true }));
	assert.ok(!item['image/png'], 'copying slides from the thumbnails must not put out an object image');

	console.log('PASS #1760: a copied picture goes out as image/png as well as text/html' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));
})().catch(e => { console.error('FAIL #1760:', e.message); process.exit(1); });

/*
 * #2095 (as briefed: "dragging a file into the editor does nothing for anything
 * but an image").
 *
 * Drag a .docx / .xlsx / .pdf / .csv from Finder, Explorer or a Linux file
 * manager onto an OPEN document and nothing happens; only images work.
 *
 * Cause: the desktop drag handlers in sdkjs/common/Local/common.js. ondragover
 * sets dropEffect from AscCommon.CanDropFiles() (common/editorscommon.js), which
 * accepts a "Files" drag only when an item has an image/* type, so for a
 * document it is 'none' and Chromium never fires the drop. ondrop itself only
 * looked for images.
 *
 * Fix: in the desktop app a non-image file drag is accepted (no inline drop
 * caret) and ondrop hands non-image files to AscDesktopEditor.DropOfficeFiles(),
 * the route the start page's drop already uses (native side filters with
 * COfficeFileFormatChecker and both shells open each file in a tab).
 *
 * This extracts the REAL InitDragAndDrop + IsDesktopFilesDrag (Local/common.js)
 * and the REAL CanDropFiles + isValidImageDragItem (editorscommon.js) by brace
 * matching and drives them with a synthetic drag. The AscDesktopEditor stub
 * models the renderer-side native semantics from
 * desktop-sdk/.../client_renderer_wrapper.cpp: GetDropFiles returns AND clears
 * the drop list, SetDropFiles replaces it, DropOfficeFiles sends whatever the
 * list holds at that moment. The "browser" only delivers ondrop when ondragover
 * left dropEffect !== 'none', as Chromium does.
 *
 * NOT claimed here: that the native side opens the tab (that is existing code
 * the start page already exercises; needs the GUI check), nor which formats
 * isOfficeFile2 accepts. Nor does this cover PASTING a copied file (see report).
 *
 *   node fork-fix-tests/issue-2095-drop-document-opens-tab-test.js
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
const BASE_REF = process.env.BASE_REF || '74d274f7d2^';
const BASELINE = !!process.env.BASELINE;

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match the block that starts at `marker`; null when absent. */
function extract(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) return null;
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}

const local = src('common/Local/common.js');
const common = src('common/editorscommon.js');

const initSrc = extract(local, 'AscCommon.InitDragAndDrop = function');
assert.ok(initSrc && initSrc.includes('GetDropFiles') && initSrc.includes('ondragover'), 'wrong InitDragAndDrop block');
const filesDragSrc = extract(local, 'AscCommon.IsDesktopFilesDrag = function'); // absent on baseline
const canDropSrc = extract(common, 'function CanDropFiles(event)');
const imgItemSrc = extract(common, 'function isValidImageDragItem(item)');
assert.ok(canDropSrc && imgItemSrc, 'CanDropFiles / isValidImageDragItem not found');

/* ------------------------------------------------------------------ harness */

const IMAGES = new Set(['/Users/x/photo.png']); // what the native magic-byte sniff says is an image

function run(opts) {
	const log = { inserted: [], opened: null, pasteText: [], pasteHtml: [], inlineBegin: 0, dropDelivered: false };
	let nativeDropList = [];
	const AscDesktopEditor = {
		SetDropFiles(arr) { nativeDropList = arr.slice(); },
		GetDropFiles() { const r = nativeDropList; nativeDropList = []; return r; },
		IsImageFile(p) { return IMAGES.has(p); },
		LocalFileGetImageUrl(p) { return 'media/' + path.basename(p); },
		DropOfficeFiles() { log.opened = nativeDropList.slice(); },
	};
	const editor = {
		isEnabledDropTarget: () => opts.dropTarget !== false,
		beginInlineDropTarget() { log.inlineBegin++; },
		endInlineDropTarget() {},
		_addImageUrl(urls) { log.inserted.push(...urls); },
		pluginMethod_PasteText(t) { log.pasteText.push(t); },
		pluginMethod_PasteHtml(h) { log.pasteHtml.push(h); },
	};
	const window = { Asc: { editor }, AscDesktopEditor };
	const AscCommon = {
		AscBrowser: { isSafari: false },
		g_oDocumentUrls: { getImageUrl: (u) => 'docurl/' + u },
	};
	new Function('window', 'AscCommon', 'FileReader',
		imgItemSrc + '\n' + canDropSrc + '\nAscCommon.CanDropFiles = CanDropFiles;\n' +
		(filesDragSrc ? filesDragSrc + ';\n' : '') + initSrc + ';')(window, AscCommon, function FileReader() {});

	const el = {};
	AscCommon.InitDragAndDrop(el, () => {});

	/* OnDragEnter (cefview.cpp) pushes the native paths before any JS event */
	AscDesktopEditor.SetDropFiles(opts.paths || []);
	const dt = {
		types: opts.types,
		items: opts.items,
		dropEffect: 'none',
		getData: (t) => (opts.data && opts.data[t]) || '',
	};
	const ev = { dataTransfer: dt, preventDefault() {} };
	el.ondragover(ev);
	if (dt.dropEffect !== 'none') {
		log.dropDelivered = true;
		el.ondrop(ev);
	}
	return log;
}

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const fileItem = (type) => ({ kind: 'file', type });

const cases = [
	{
		name: 'A. a .docx dropped on an open document opens in a new tab',
		opts: { types: ['Files'], items: [fileItem(DOCX_MIME)], paths: ['/Users/x/report Q3.docx'] },
		check(l) {
			assert.ok(l.dropDelivered, 'dragover refused the drop (dropEffect none) - the reported bug');
			assert.deepStrictEqual(l.opened, ['/Users/x/report Q3.docx'], 'document not handed to DropOfficeFiles');
			assert.deepStrictEqual(l.inserted, []);
			assert.strictEqual(l.inlineBegin, 0, 'inline text-drop caret shown for a file that will not be inserted');
		},
	},
	{
		name: 'B. several documents (xlsx + pdf + csv) all go to DropOfficeFiles',
		opts: { types: ['Files'], items: [fileItem('application/pdf'), fileItem('text/csv'), fileItem('application/vnd.ms-excel')],
			paths: ['/Users/x/a.xlsx', '/Users/x/b.pdf', '/Users/x/c.csv'] },
		check(l) { assert.deepStrictEqual(l.opened, ['/Users/x/a.xlsx', '/Users/x/b.pdf', '/Users/x/c.csv']); },
	},
	{
		name: 'C. image + document: the image is inserted AND the document opens',
		opts: { types: ['Files'], items: [fileItem('image/png'), fileItem(DOCX_MIME)], paths: ['/Users/x/photo.png', '/Users/x/r.docx'] },
		check(l) {
			assert.deepStrictEqual(l.inserted, ['docurl/media/photo.png']);
			assert.deepStrictEqual(l.opened, ['/Users/x/r.docx']);
		},
	},
	{
		name: 'D. PDF editor (drop target disabled): a document still opens, nothing is inserted',
		opts: { dropTarget: false, types: ['Files'], items: [fileItem(DOCX_MIME)], paths: ['/Users/x/r.docx'] },
		check(l) { assert.deepStrictEqual(l.opened, ['/Users/x/r.docx']); assert.deepStrictEqual(l.inserted, []); },
	},
	/* --- unchanged behaviour --- */
	{
		name: 'E. an image alone is still inserted (with the inline caret) and nothing is opened',
		regression: true,
		opts: { types: ['Files'], items: [fileItem('image/png')], paths: ['/Users/x/photo.png'] },
		check(l) {
			assert.deepStrictEqual(l.inserted, ['docurl/media/photo.png']);
			assert.strictEqual(l.opened, null);
			assert.strictEqual(l.inlineBegin, 1);
		},
	},
	{
		name: 'F. text dragged from another app is still pasted as text',
		regression: true,
		opts: { types: ['text/plain'], items: [{ kind: 'string', type: 'text/plain' }], paths: [], data: { 'text/plain': 'hello' } },
		check(l) { assert.deepStrictEqual(l.pasteText, ['hello']); assert.strictEqual(l.opened, null); },
	},
	{
		name: 'G. PDF editor: an image is not inserted (as before)',
		regression: true,
		opts: { dropTarget: false, types: ['Files'], items: [fileItem('image/png')], paths: ['/Users/x/photo.png'] },
		check(l) { assert.deepStrictEqual(l.inserted, []); assert.strictEqual(l.opened, null); },
	},
];

let failed = 0;
for (const c of cases) {
	try {
		c.check(run(c.opts));
		console.log('ok   ' + c.name);
	} catch (e) {
		failed++;
		console.log('FAIL ' + c.name + ' :: ' + e.message.split('\n')[0]);
	}
}
if (failed) {
	console.log(`FAIL #2095: ${failed}/${cases.length} cases` + (BASELINE ? ' (BASELINE, expected)' : ''));
	process.exit(1);
}
console.log('PASS #2095: non-image file drops reach DropOfficeFiles; image/text drops unchanged' + (BASELINE ? ' (BASELINE?!)' : ''));

/*
 * #2561 - dragging an image from Explorer into a PPTX across an open DOCX: the
 * next click in the DOCX inserts a paragraph break where it lands ("handing"
 * -> "handin" / "g out lemons"). Only when the drag passed over the DOCX.
 *
 * Cause: ondragover in InitDragAndDrop (sdkjs common/Local/common.js for the
 * desktop app, common/editorscommon.js for the web) calls
 * editor.beginInlineDropTarget(), which in the word editor (word/api.js) turns
 * on the inline text track: DrawingDocument.StartTrackText ->
 * InlineTextTrackEnabled = true. Only ondrop ended it; there was no
 * ondragleave, so a drag that left the view and dropped elsewhere left the
 * track on. The next mouse up goes through checkMouseUp_Drawing
 * (word/Drawing/DrawingDocument.js), which ends an enabled track with
 * EndTrackText() -> CDocument.OnEndTextDrag(): a text drag-n-drop of the
 * collapsed selection to the click point, i.e. a paragraph split there.
 *
 * Fix: both InitDragAndDrop handle ondragleave (unless it is a move between the
 * editor's own children) with editor.cancelInlineDropTarget(); word cancels the
 * track (CancelTrackText, as Escape does).
 *
 * This extracts the REAL InitDragAndDrop of both files, the REAL word
 * begin/end/cancelInlineDropTarget (word/api.js), the REAL Start/End/Cancel/
 * IsTrackText (word/Drawing/DrawingDocument.js) and the REAL "track enabled"
 * branch of checkMouseUp_Drawing, and drives: dragover over the text, dragleave
 * to outside the view (relatedTarget null, what Chromium sends when the drag
 * leaves the window), then a mouse up. CDocument.OnEndTextDrag is a stub that
 * records the call (that call IS the paragraph split).
 *
 * The full chain was also reproduced end to end in headless Chromium with real
 * drag events (CDP Input.dispatchDragEvent) on the built word editor: before
 * the fix the click split "handing" into "handin" / "g out lemons", after it
 * the document is unchanged (.rd-work/wt/at-tmp/h/repro.js).
 *
 * NOT claimed: that Windows/CEF delivers dragleave to the DOCX view when the
 * cursor moves on to another window (standard Chromium OLE drop-target
 * behaviour; desktop-sdk OnDragEnter returns false and does not intercept) -
 * needs the GUI check on Windows. The slide/cell editors never start an inline
 * drop target (base no-op), so they were not affected.
 *
 *   node fork-fix-tests/issue-2561-drag-leave-drop-target-test.js
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
const BASE_REF = process.env.BASE_REF || 'fe553e8d21^';
const BASELINE = !!process.env.BASELINE;

function src(rel) {
	return BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match the block that starts at `marker` (from `from`); null when absent. */
function extract(text, marker, from) {
	const at = text.indexOf(marker, from || 0);
	if (at === -1) return null;
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}
function need(text, marker, from) {
	const s = extract(text, marker, from);
	assert.ok(s, marker + ' not found');
	return s;
}

const local = src('common/Local/common.js');
const web = src('common/editorscommon.js');
const wordApi = src('word/api.js');
const drDoc = src('word/Drawing/DrawingDocument.js');

const localInit = need(local, 'AscCommon.InitDragAndDrop = function');
const webInit = need(web, 'function InitDragAndDrop(oHtmlElement, callback)');

/* The word API drop-target methods; cancelInlineDropTarget is absent on baseline. */
const apiMethods = ['beginInlineDropTarget', 'endInlineDropTarget', 'cancelInlineDropTarget']
	.map(n => extract(wordApi, 'asc_docs_api.prototype.' + n + ' = function'))
	.filter(Boolean).join(';\n');

/* DrawingDocument track methods, and the track branch of checkMouseUp_Drawing. */
const trackMethods = ['StartTrackText', 'EndTrackText', 'IsTrackText', 'CancelTrackText']
	.map(n => need(drDoc, 'this.' + n + ' = function')).join(';\n');
const mouseUpAt = drDoc.indexOf('this.checkMouseUp_Drawing = function');
assert.notStrictEqual(mouseUpAt, -1, 'checkMouseUp_Drawing not found');
const mouseUpTrack = need(drDoc, 'if (this.InlineTextTrackEnabled && !this.contentControls.getInlineMoveTrack())', mouseUpAt);

/* ------------------------------------------------------------------ harness */

function makeEditor() {
	const log = [];
	const logicDocument = {
		Get_NearestPos(page, x, y) { return { Paragraph: { Cursor_MoveToNearPos() {}, Document_SetThisElementCurrent() {} }, page, x, y }; },
		OnEndTextDrag(nearPos) { log.push('OnEndTextDrag'); }, // the paragraph split
		Document_UpdateSelectionState() {}, Document_UpdateInterfaceState() {}, Document_UpdateRulersState() {},
	};
	const wordControl = {
		m_oLogicDocument: logicDocument,
		StartUpdateOverlay() {}, EndUpdateOverlay() {}, ShowOverlay() {}, OnUpdateOverlay() {},
		// HtmlPage.onMouseMove -> DrawingDocument.checkMouseMove_Drawing: with the track on, it sets the near pos
		onMouseMove(e) { const d = this.m_oDrawingDocument; if (d.InlineTextTrackEnabled) d.InlineTextTrack = logicDocument.Get_NearestPos(0, e.pageX, e.pageY); },
	};
	function DrawingDocument() {
		this.m_oWordControl = wordControl;
		this.InlineTextTrackEnabled = false;
		this.InlineTextTrack = null;
		this.contentControls = { getInlineMoveTrack() { return null; } };
		new Function('AscCommon', trackMethods + ';').call(this, { global_keyboardEvent: { CtrlKey: false } });
		// the real branch of checkMouseUp_Drawing, wrapped so it can run alone
		this.mouseUp = new Function('oWordControl', 'pos', mouseUpTrack + '\nreturn false;');
	}
	const dd = new DrawingDocument();
	wordControl.m_oDrawingDocument = dd;

	function asc_docs_api() { this.WordControl = wordControl; }
	asc_docs_api.prototype.isEnabledDropTarget = function () { return true; };
	asc_docs_api.prototype.cancelInlineDropTarget = function () {}; // baseEditorsApi default (no-op)
	new Function('asc_docs_api', apiMethods + ';')(asc_docs_api);
	return { api: new asc_docs_api(), dd, wordControl, log };
}

function makeElement() {
	const children = new Set();
	return { children, contains(n) { return n === this || children.has(n); } };
}

function install(initSrc, isDesktop) {
	const ed = makeEditor();
	const el = makeElement();
	const window = { Asc: { editor: ed.api }, editor: ed.api };
	if (isDesktop) window.AscDesktopEditor = { GetDropFiles: () => [], IsImageFile: () => true, LocalFileGetImageUrl: () => '' };
	const AscCommon = {
		CanDropFiles: () => true, // an image file drag (what CanDropFiles accepts)
		IsDesktopFilesDrag: () => false,
		AscBrowser: {},
	};
	const g = { FileReader: function () {} };
	const fn = isDesktop
		? new Function('window', 'AscCommon', 'FileReader', 'CanDropFiles', 'el', initSrc + '; AscCommon.InitDragAndDrop(el, null);')
		: new Function('window', 'AscCommon', 'FileReader', 'CanDropFiles', 'el', initSrc + '; InitDragAndDrop(el, null);');
	fn(window, AscCommon, g.FileReader, AscCommon.CanDropFiles, el);
	return { ed, el };
}

function dragEvent(extra) {
	return Object.assign({ preventDefault() {}, pageX: 233, pageY: 163, dataTransfer: { dropEffect: 'none', types: ['Files'] } }, extra);
}

const results = [];
for (const [name, initSrc, isDesktop] of [['desktop (Local/common.js)', localInit, true], ['web (editorscommon.js)', webInit, false]]) {
	const { ed, el } = install(initSrc, isDesktop);

	// image drag over the text: the drop caret (inline track) starts
	el.ondragover(dragEvent());
	assert.strictEqual(ed.dd.IsTrackText(), true, name + ': dragover should start the inline drop target');

	// moving between the editor's own canvases must not stop it
	const child = {};
	el.children.add(child);
	if (el.ondragleave) el.ondragleave(dragEvent({ relatedTarget: child }));
	assert.strictEqual(ed.dd.IsTrackText(), true, name + ': a dragleave into a child of the editor must keep the drop target');

	// the drag leaves the view and is dropped in the other window: no drop here
	if (el.ondragleave) el.ondragleave(dragEvent({ relatedTarget: null }));
	const leftOn = ed.dd.IsTrackText();

	// the user comes back and clicks in the text
	ed.dd.mouseUp(ed.wordControl, { Page: 0, X: 10, Y: 10 });
	const split = ed.log.includes('OnEndTextDrag');
	results.push({ name, hasLeave: !!el.ondragleave, leftOn, split });
	console.log(`${name}: ondragleave=${!!el.ondragleave} drop target left on=${leftOn} click ended a text drag (split)=${split}`);
}

/* a real drop still ends the drop target by moving the cursor, not by a text drag */
{
	const { ed, el } = install(localInit, true);
	el.ondragover(dragEvent());
	el.ondrop(dragEvent({ dataTransfer: { types: ['Files'], getData: () => '' } }));
	assert.strictEqual(ed.dd.IsTrackText(), false, 'drop must end the drop target');
	assert.ok(!ed.log.includes('OnEndTextDrag'), 'drop must not run a text drag');
}

for (const r of results) {
	assert.ok(r.hasLeave, r.name + ': no ondragleave - the drop target is never stopped when the drag leaves');
	assert.strictEqual(r.leftOn, false, r.name + ': the inline drop target stayed on after the drag left');
	assert.strictEqual(r.split, false, r.name + ': the next click ran OnEndTextDrag (paragraph split at the click)');
}

console.log('PASS #2561: a drag that leaves without dropping no longer turns the next click into a text drop' + (BASELINE ? ' (BASELINE?!)' : ''));

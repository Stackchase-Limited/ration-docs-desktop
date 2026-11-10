/*
 * #2010 - "Add toc for the PDF export of DOCX": a docx with headings saved as
 * PDF had no bookmarks (outline) pane entries in the desktop app.
 *
 * In our 9.4 base the outline itself is already written: upstream bug 59297
 * (sdkjs 4c941077a5) made word asc_nativeGetPDF - what x2t/doctrenderer runs
 * for docx -> pdf and so for the desktop's Save as PDF - call
 * CDocumentRenderer.AddHeadings, which emits metafile command ctHeadings (169)
 * that core's CPdfWriter::SetHeadings turns into /Outlines. Our x2t gives a
 * correct nested outline for a whole-document export.
 *
 * Two defects remained in what AddHeadings wrote:
 *  - asc_nativeGetPDF draws only the pages of a range (print preview "Save as
 *    PDF" with a page range or the current page; onlyFirstPage), but each
 *    heading carried its DOCUMENT page index, which CPdfWriter resolves against
 *    the pages actually written. Saving page 2 of 2 gave bookmarks for page-1
 *    headings pointing at the one written page, and the page-2 headings with
 *    no destination at all (seen with x2t: pypdf page None).
 *  - CDocumentOutline.GetText ends with the paragraph mark, so every bookmark
 *    title was "Heading\r\n".
 *
 * This extracts by brace matching the REAL asc_nativeGetPDF (word/api.js),
 * getNativePrintRanges (common/editorscommon.js) and WriteHeadings, AddHeading,
 * GetHeadingsByHeadings, GetHeadingsByBookmarks and CDocumentRenderer.AddHeadings
 * (common/Drawings/Metafile.js), runs them against a stub document of 3 pages
 * with one heading per page, and decodes the ctHeadings record they write.
 *
 * Claimed: whole export keeps every heading with its page; a page range keeps
 * only the headings on the drawn pages, renumbered to their position in the
 * PDF; onlyFirstPage keeps page-1 headings only; titles have no trailing CR/LF.
 * NOT claimed: core's outline writer (checked with real x2t for the commit,
 * see #1855 for PageMode), the print-preview UI, or bookmark-based outlines.
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
const BASE_REF = process.env.BASE_REF || '29c78b83b5^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match a block starting at `from`, returning the source through its close. */
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
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at) + ';\n';
}

const api = src('word/api.js');
const common = src('common/editorscommon.js');
const metafile = src('common/Drawings/Metafile.js');

const code =
	extract(common, 'function getNativePrintRanges(') +
	'AscCommon.getNativePrintRanges = getNativePrintRanges;\n' +
	extract(metafile, 'function WriteHeadings(') +
	extract(metafile, 'function AddHeading(') +
	extract(metafile, 'function GetHeadingsByHeadings(') +
	extract(metafile, 'function GetHeadingsByBookmarks(') +
	extract(metafile, 'CDocumentRenderer.prototype.AddHeadings = function') +
	extract(api, 'window["asc_docs_api"].prototype["asc_nativeGetPDF"] = function');

/* --- stubs --- */
const PAGES = 3;
// one heading per page: level, page, title as CDocumentOutline.GetText returns it
const OUTLINE = [
	{ lvl: 0, page: 0, text: 'Chapter One\r\n' },
	{ lvl: 1, page: 1, text: 'Section 1.1\r\n' },
	{ lvl: 0, page: 2, text: 'Chapter Two\r\n' },
];

function exportPdf(options) {
	const window = {};
	const AscCommon = {};
	function asc_docs_api() {}
	window['asc_docs_api'] = asc_docs_api;
	window['native'] = { Save_End() {} };

	function Memory() { this.ops = []; this.pos = 0; this.data = this.ops; }
	Memory.prototype.WriteByte = function (v) { this.ops.push(['byte', v]); this.pos++; };
	Memory.prototype.WriteLong = function (v) { this.ops.push(['long', v]); this.pos++; };
	Memory.prototype.WriteDouble = function (v) { this.ops.push(['double', v]); this.pos++; };
	Memory.prototype.WriteString = function (v) { this.ops.push(['string', v]); this.pos++; };
	Memory.prototype.Skip = function () { this.pos++; };
	Memory.prototype.GetCurPosition = function () { return this.pos; };
	Memory.prototype.Seek = function (p) { this.pos = p; };
	Memory.prototype.ClearNoAttack = function () {};

	function CDocumentRenderer() { this.Memory = new Memory(); this.pagesDrawn = []; }
	CDocumentRenderer.prototype.InitPicker = function () {};
	CDocumentRenderer.prototype.DocInfo = function () {};
	AscCommon.CDocumentRenderer = CDocumentRenderer;
	AscCommon.CMemory = Memory;
	AscCommon.g_oTextMeasurer = { m_oManager: null };
	AscCommon.CWatermarkOnDraw = function () {};
	const CommandType = { ctHeadings: 169 };

	const docOutline = {
		IsUse: () => true,
		SetUse() {},
		GetElementsCount: () => OUTLINE.length,
		GetDestinationXY: i => ({ X: 20, Y: 30 + i, PageNum: OUTLINE[i].page }),
		GetLevel: i => OUTLINE[i].lvl,
		GetText: i => OUTLINE[i].text,
	};
	const logic = { GetDocumentOutline: () => docOutline };

	new Function('window', 'asc_docs_api', 'AscCommon', 'CommandType', 'CDocumentRenderer', code)(
		window, asc_docs_api, AscCommon, CommandType, CDocumentRenderer);

	const a = new asc_docs_api();
	let renderer = null;
	a.WordControl = { m_oLogicDocument: logic, m_oDrawingDocument: { m_lPagesCount: PAGES } };
	a.ShowParaMarks = false;
	a.asc_isFinalizedVersion = () => false;
	a.asc_getCoreProps = () => null;
	a['asc_nativePrintPagesCount'] = () => PAGES;
	a['asc_nativePrint'] = (r, i) => { renderer = r; r.pagesDrawn.push(i); };
	const ops = a['asc_nativeGetPDF'](options);

	// decode the ctHeadings record
	const at = ops.findIndex(op => op[0] === 'byte' && op[1] === 169);
	const headings = [];
	if (at !== -1) {
		const n = ops[at + 1][1];
		for (let k = 0; k < n; k++) {
			const b = at + 2 + k * 5;
			headings.push({ lvl: ops[b][1], page: ops[b + 1][1], title: ops[b + 4][1] });
		}
	}
	return { pages: renderer ? renderer.pagesDrawn : [], headings };
}

/* 1. whole document: every heading, on its own page */
let r = exportPdf(null);
assert.deepStrictEqual(r.pages, [0, 1, 2]);
assert.deepStrictEqual(r.headings.map(h => h.page), [0, 1, 2]);
assert.deepStrictEqual(r.headings.map(h => h.lvl), [0, 1, 0]);

/* 2. titles carry no paragraph mark */
assert.deepStrictEqual(r.headings.map(h => h.title), ['Chapter One', 'Section 1.1', 'Chapter Two'],
	'bookmark titles must not end with the paragraph mark');

/* 3. page range 2-3: the PDF has 2 pages; page-1 heading dropped, the others renumbered */
r = exportPdf({ nativeOptions: { pages: '2-3', currentPage: 1 } });
assert.deepStrictEqual(r.pages, [1, 2]);
assert.deepStrictEqual(r.headings.map(h => [h.title.trim(), h.page]), [['Section 1.1', 0], ['Chapter Two', 1]],
	'headings must point at their page within the exported range');

/* 4. current page (3): only its heading, on PDF page 0 */
r = exportPdf({ nativeOptions: { pages: 'current', currentPage: 3 } });
assert.deepStrictEqual(r.headings.map(h => [h.title.trim(), h.page]), [['Chapter Two', 0]]);

/* 5. onlyFirstPage: headings on later pages must not dangle */
r = exportPdf({ printOptions: { onlyFirstPage: true } });
assert.deepStrictEqual(r.headings.map(h => [h.title.trim(), h.page]), [['Chapter One', 0]]);

console.log('PASS #2010: PDF outline headings match the exported pages and have clean titles' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));

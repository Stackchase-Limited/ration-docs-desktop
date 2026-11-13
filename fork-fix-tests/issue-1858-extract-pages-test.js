/*
 * #1858 - extract pages to a new PDF.
 *
 * Before: the PDF editor could copy, cut, delete and rotate pages, but not save some of
 * them as a PDF of their own; Save Copy (#982) runs x2t over the whole document and
 * cannot carry a subset.
 *
 * Now: the thumbnails' page menu has "Save pages as new PDF..." (web-apps pdfeditor
 * DocumentHolderExt view/controller). It calls sdkjs api.asc_ExtractPages (pdf/api.js),
 * which takes the selected pages (only for a PDF file, as copying pages; valid,
 * de-duplicated indexes), gets their bytes from CPDFDoc.GetPagesBinary - the drawingfile
 * engine's SplitPages, already used to copy pages - and hands them to
 * AscCommon.DownloadFileFromBytes: a blob: URL made by the editor page and an
 * <a download> click. In the desktop app that download reaches desktop-sdk cefview.cpp
 * OnBeforeDownload, which sends CEF_SAVEFILEDIALOG: the native Save dialog on Windows/
 * Linux (onDownloadSaveDialog) and macOS (AppDelegate onCEFStartSave, NSSavePanel - it
 * exists; the earlier triage note saying macOS had none was wrong). Nothing new is
 * reachable through the AscDesktopEditor bridge. The file is named after the document
 * and the pages, e.g. "Report (2-4, 7).pdf".
 *
 * This test:
 * A. loads the REAL drawingfile.js + drawingfile.wasm in node, opens a 4-page PDF whose
 *    pages differ in height, and runs the REAL CPDFDoc.prototype.GetPagesBinary and the
 *    REAL PDFEditorApi asc_CanExtractPages / asc_ExtractPages (extracted by brace
 *    matching) against a stub viewer/document; the bytes handed to DownloadFileFromBytes
 *    are reopened with the engine and must hold exactly the chosen pages.
 * B. runs the REAL AscCommon DownloadFileFromBytes (common/editorscommon.js) in headless
 *    Chromium: the click must start a browser download (what CEF hands to
 *    OnBeforeDownload) with the given name and the identical bytes.
 * C. runs the REAL web-apps getExtractPagesFileName / onExtractPages against stubs and
 *    checks the menu item wiring and the en.json string.
 *
 * NOT claimed: the native Save dialog shown in the app (GUI check on each platform);
 * annotation/form edits carried into the new file (that is GetPagesBinary's SaveForSplit,
 * shared with copy pages; stubbed here with no edits).
 *
 * RD_REPO=<sdkjs> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default ../web-apps).
 * PLAYWRIGHT / RD_CHROME as in issue-1664-paste-webp-test.js.
 * BASELINE=1 reads sources at BASE_REF / WEBAPPS_BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps');
// Pinned to the parents of the commits that landed this feature, never HEAD.
const BASE_REF = process.env.BASE_REF || 'e48439ad4f^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '09b9b8911e^';
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
const UNDERSCORE = path.join(ROOT, 'web-apps', 'vendor', 'underscore', 'underscore-min.js');

function readFrom(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
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
function fnAfter(text, marker) {
	const at = text.indexOf(marker);
	return at === -1 ? null : matched(text, text.indexOf('function', at));
}

const CHECKS = [];
const check = (name, ok, got) => CHECKS.push([name, !!ok, got]);

// a PDF whose pages are told apart by their height (201, 202, ... points)
function makePdf(count) {
	const objs = ['<< /Type /Catalog /Pages 2 0 R >>',
		'<< /Type /Pages /Kids [' + Array.from({ length: count }, (x, i) => (3 + i) + ' 0 R').join(' ') + '] /Count ' + count + ' >>'];
	for (let i = 0; i < count; i++)
		objs.push('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 ' + (201 + i) + '] >>');
	let out = '%PDF-1.5\n';
	const off = [];
	objs.forEach((o, i) => { off.push(out.length); out += (i + 1) + ' 0 obj\n' + o + '\nendobj\n'; });
	const x = out.length;
	out += 'xref\n0 ' + (objs.length + 1) + '\n0000000000 65535 f \n' + off.map((o) => String(o).padStart(10, '0') + ' 00000 n \n').join('') +
		'trailer\n<< /Size ' + (objs.length + 1) + ' /Root 1 0 R >>\nstartxref\n' + x + '\n%%EOF\n';
	return new Uint8Array(Buffer.from(out));
}
function loadEngine() {
	// the engine is not changed by this feature: always the checked-out one
	const E = path.join(SDKJS, 'pdf/src/engine');
	const glue = fs.readFileSync(path.join(E, 'drawingfile.js'), 'utf8');
	const wasm = fs.readFileSync(path.join(E, 'drawingfile.wasm'));
	return new Promise((resolve, reject) => {
		const ctx = { console, WebAssembly, Promise, setTimeout, clearTimeout, TextDecoder, TextEncoder, performance,
			crypto: globalThis.crypto, navigator: { userAgent: 'node' } };
		ctx.window = ctx.self = ctx;
		ctx.fetch = () => Promise.resolve(new Response(wasm, { headers: { 'content-type': 'application/wasm' } }));
		ctx.AscViewer = { onLoadModule: () => resolve(ctx.AscViewer) };
		vm.createContext(ctx);
		vm.runInContext(glue, ctx, { filename: 'drawingfile.js' });
		setTimeout(() => reject(new Error('drawingfile module did not initialise')), 20000).unref();
	});
}

(async () => {
	// ------------------------------------------------------------ A: sdkjs api + real engine
	const apiSrc = readFrom(SDKJS, BASE_REF, 'pdf/api.js');
	const docSrc = readFrom(SDKJS, BASE_REF, 'pdf/src/document.js');
	const getPagesBinary = fnAfter(docSrc, 'CPDFDoc.prototype.GetPagesBinary = function');
	const canExtract = fnAfter(apiSrc, 'PDFEditorApi.prototype.asc_CanExtractPages = function');
	const extract = fnAfter(apiSrc, 'PDFEditorApi.prototype.asc_ExtractPages = function');
	check('sdkjs: pdf/api.js has asc_CanExtractPages and asc_ExtractPages', canExtract && extract, '');
	check('sdkjs: both are exported by name',
		/\['asc_CanExtractPages'\]\s*=\s*PDFEditorApi\.prototype\.asc_CanExtractPages/.test(apiSrc) &&
		/\['asc_ExtractPages'\]\s*=\s*PDFEditorApi\.prototype\.asc_ExtractPages/.test(apiSrc), '');

	const viewer = await loadEngine();
	if (getPagesBinary && canExtract && extract) {
		const downloads = [];
		const ctx = vm.createContext({ AscCommon: { Base64: { encode: () => 'b64' },
			DownloadFileFromBytes: (data, name, mime) => downloads.push({ data: new Uint8Array(data), name, mime }) }, Math, Array });
		const run = (src) => vm.runInContext('(' + src + ')', ctx);
		const makeApi = (type, selected) => {
			const file = new viewer.CDrawingFile();
			if (file.loadFromData(makePdf(4))) throw new Error('engine could not open the test PDF');
			const pages = file.getPages();
			const doc = {
				Viewer: { file: { type, nativeFile: file, pages, originalPagesCount: pages.length }, SaveForSplit: () => null },
				GetPagesCount: () => pages.length,
				IsMergeLock: () => false,
				GetPagesBinary: run(getPagesBinary),
			};
			doc.Viewer.file.pages.forEach((p, i) => { p.originIndex = i; });
			doc.Viewer.SaveForSplit = () => undefined;
			return { getPDFDoc: () => doc, getSelectedPages: () => selected.slice(), DocumentRenderer: doc.Viewer,
				asc_CanExtractPages: run(canExtract), asc_ExtractPages: run(extract) };
		};
		const heights = (bytes) => {
			const f = new viewer.CDrawingFile();
			if (f.loadFromData(bytes)) return 'unreadable';
			return f.getPages().map((p) => p.H).join(',');
		};

		let api = makeApi(0, [3, 1]);
		const ok = api.asc_ExtractPages('Report (2, 4).pdf');
		const d = downloads[0];
		check('sdkjs: the selected pages 2 and 4 are offered as one download',
			ok === true && downloads.length === 1 && d.name === 'Report (2, 4).pdf' && d.mime === 'application/pdf', JSON.stringify([ok, downloads.length, d && d.name]));
		check('sdkjs: the downloaded bytes are a PDF of exactly pages 2 and 4 (heights 202, 204)',
			d && Buffer.from(d.data.slice(0, 5)).toString() === '%PDF-' && heights(d.data) === '202,204', d && heights(d.data));

		downloads.length = 0;
		api = makeApi(0, [0]);
		api.asc_ExtractPages('x.pdf', [2, 2, 9, -1, 1.5, '0']);
		check('sdkjs: explicit pages are de-duplicated and pages the document does not have are dropped',
			downloads.length === 1 && heights(downloads[0].data) === '203', downloads.length && heights(downloads[0].data));

		downloads.length = 0;
		api = makeApi(0, [0]);
		const none = api.asc_ExtractPages('x.pdf', [7]);
		check('sdkjs: no valid page - nothing is downloaded', none === false && downloads.length === 0, none);

		downloads.length = 0;
		api = makeApi(1, [0]);
		check('sdkjs: not for XPS/DjVu files (as copying pages)',
			api.asc_CanExtractPages() === false && api.asc_ExtractPages('x.pdf') === false && downloads.length === 0, downloads.length);
	}

	// ------------------------------------------------------------ B: the download in a real browser
	const common = fs.readFileSync(path.join(SDKJS, 'common/editorscommon.js'), 'utf8');
	const dl = fnAfter(common, 'function DownloadFileFromBytes(');
	let browser;
	try {
		const { chromium } = require(PLAYWRIGHT);
		browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
		const page = await browser.newPage({ acceptDownloads: true });
		await page.setContent('<html><body></body></html>');
		const bytes = Array.from(makePdf(2));
		const [download] = await Promise.all([
			page.waitForEvent('download', { timeout: 10000 }),
			page.evaluate(([src, data]) => { (0, eval)('(' + src + ')')(new Uint8Array(data), 'Report (1-2).pdf', 'application/pdf'); }, [dl, bytes]),
		]);
		const saved = fs.readFileSync(await download.path());
		check('browser: DownloadFileFromBytes starts a real download with the name given',
			download.suggestedFilename() === 'Report (1-2).pdf' && /^blob:/.test(download.url()), download.suggestedFilename() + ' ' + download.url());
		check('browser: the downloaded file has the identical bytes', Buffer.compare(saved, Buffer.from(bytes)) === 0, saved.length + ' vs ' + bytes.length);
	} catch (e) {
		check('browser: download in headless Chromium', false, e.message);
	} finally {
		browser && await browser.close();
	}

	// ------------------------------------------------------------ C: web-apps
	const ctrl = readFrom(WEBAPPS, WEBAPPS_BASE_REF, 'apps/pdfeditor/main/app/controller/DocumentHolderExt.js');
	const view = readFrom(WEBAPPS, WEBAPPS_BASE_REF, 'apps/pdfeditor/main/app/view/DocumentHolderExt.js');
	const en = JSON.parse(readFrom(WEBAPPS, WEBAPPS_BASE_REF, 'apps/pdfeditor/main/locale/en.json'));
	const nameFn = fnAfter(ctrl, 'dh.getExtractPagesFileName = function');
	const onFn = fnAfter(ctrl, 'dh.onExtractPages = function');
	check('web-apps: the controller has onExtractPages and getExtractPagesFileName', nameFn && onFn, '');
	if (nameFn && onFn) {
		const calls = [];
		const ctx = vm.createContext({ _: require(UNDERSCORE), Common: { NotificationCenter: { trigger: (e) => calls.push(e) } } });
		const me = {
			getExtractPagesFileName: vm.runInContext('(' + nameFn + ')', ctx),
			onExtractPages: vm.runInContext('(' + onFn + ')', ctx),
			api: { getSelectedPages: () => [6, 1, 2, 3], asc_getDocumentName: () => 'Q3 report.final.pdf',
				asc_ExtractPages: (name, pages) => { calls.push([name, pages]); return true; } },
		};
		me.onExtractPages();
		check('web-apps: the menu command passes the selected pages and a name from the document and the pages',
			JSON.stringify(calls[0]) === JSON.stringify(['Q3 report.final (2-4, 7).pdf', [6, 1, 2, 3]]) && calls[1] === 'edit:complete', JSON.stringify(calls));
		check('web-apps: one page, and a document without a name',
			me.getExtractPagesFileName('a.pdf', [0]) === 'a (1).pdf' && me.getExtractPagesFileName('', [4, 4]) === 'Document (5).pdf',
			me.getExtractPagesFileName('a.pdf', [0]) + ' / ' + me.getExtractPagesFileName('', [4, 4]));
	}
	check('web-apps: the page menu has the item, shown for page selections when the api has it, and wired to onExtractPages',
		/me\.mnuExtractPages = new Common\.UI\.MenuItem/.test(view) && /mnuExtractPages\.setVisible\(value\.isPageSelect===true && !!me\.api && !!me\.api\.asc_ExtractPages\)/.test(view) &&
		/me\.mnuCopyPage,\s*me\.mnuExtractPages,/.test(view) && /view\.mnuExtractPages\.on\('click', _\.bind\(me\.onExtractPages, me\)\)/.test(ctrl), '');
	check('web-apps: en.json has the menu text', en['PDFE.Views.DocumentHolder.txtExtractPages'], '');

	let failed = 0;
	for (const [name, ok, got] of CHECKS) {
		if (!ok) failed++;
		console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ': got ' + String(got).slice(0, 400)}`);
	}
	console.log(failed ? `FAIL: ${failed} of ${CHECKS.length} checks` : `PASS: ${CHECKS.length} checks`);
	process.exit(failed ? 1 : 0);
})().catch((e) => { console.log('FAIL ' + (e && e.stack || e)); process.exit(1); });

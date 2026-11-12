// Real cell editor (headless Chromium, stubbed desktop host) for the "copy sheet to a new workbook" lead.
// node cell_rt.js source <sdkjs tree> <Editor.bin> <AllFonts.js> <outdir> <sheetIndexToCopy>
//   open, type into Sheet1!A1, insert a row on Sheet2 and type into its new A1 (recorded by an autosave,
//   as the editor does), write outdir/changes0.json exactly as the host does, then copyToNewWorkbook([idx]) and write what AscDesktopEditor.OpenWorkbook got as
//   outdir/EditorForAsLocal.bin.
// node cell_rt.js open <sdkjs tree> <Editor.bin> <AllFonts.js> <changes0.json or -> 
//   the new tab: the host's onlocaldocument_loadend - changes0.json (if any) passed to
//   DesktopOfflineAppDocumentApplyChanges + LocalFileSetOpenChangesCount, then EndLoad; prints the sheets.
const fs = require('fs');
const path = require('path');
const startServer = require('./server');
const PW = process.env.RD_PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const { chromium } = require(PW);

const initStub = () => {
	window.__changes = [];
	window.__openChanges = 0;
	const known = {
		CryptoMode: 0,
		LocalStartOpen() { window.__startOpen = true; },
		GetOpenedFile() { return window.__bin; },
		CheckUserId() { return 'uid1'; },
		LocalFileGetOpenChangesCount() { return window.__openChanges; },
		LocalFileSetOpenChangesCount(n) { window.__openChanges = n; },
		LocalFileGetSaved() { return true; },
		LocalFileGetSourcePath() { return '/tmp/x/book.xlsx'; },
		IsLocalFile() { return true; },
		LocalFileSaveChanges(str, deleteIndex, count) { window.__changes.push({ str, deleteIndex, count }); },
		LocalFileSave() {},
		OpenWorkbook(b64) { window.__workbook = b64; return true; },
		GetInstallPlugins() { return '[{"url":"","pluginsData":[]},{"url":"","pluginsData":[]}]'; },
		GetSupportedScaleValues() { return [1, 2]; },
		IsSupportMedia() { return false; },
		isBlockchainSupport() { return false; },
		GetImageBase64() { return ''; },
		GetEncryptedHeader() { return 'ENCRYPTED;'; },
		GetFontThumbnailHeight() { return 28; },
	};
	window.AscDesktopEditor = new Proxy(known, {
		get(t, k) {
			if (k in t) return t[k];
			if (typeof k !== 'string' || k === 'then' || k === 'toJSON') return undefined;
			return function () { return undefined; };
		},
	});
};

const dump = () => {
	const wb = Asc.editor.wbModel;
	const out = [];
	for (let i = 0; i < wb.getWorksheetCount(); i++) {
		const ws = wb.getWorksheet(i);
		const cells = {};
		for (let r = 0; r < 6; r++) for (let c = 0; c < 3; c++) {
			const v = ws.getCell3(r, c).getValueWithoutFormat();
			if (v !== '') cells[String.fromCharCode(65 + c) + (r + 1)] = v;
		}
		out.push({ name: ws.getName(), id: ws.getId(), cells });
	}
	return out;
};

(async () => {
	const [mode, sdkjsTree, bin, allFonts, arg5, arg6] = process.argv.slice(2);
	const srv = await startServer({ sdkjsRoots: [path.join(sdkjsTree, 'deploy', 'sdkjs'), sdkjsTree], page: path.join(__dirname, 'page.html'), allFonts, editorBin: bin });
	const chrome = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
	const browser = await chromium.launch(fs.existsSync(chrome) ? { executablePath: chrome } : {});
	const errors = [];
	try {
		const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
		page.on('pageerror', e => errors.push(String(e && e.stack || e))); page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errors.push('console: ' + m.text().slice(0, 300)); });
		await page.addInitScript(initStub);
		await page.goto(`http://127.0.0.1:${srv.address().port}/web-apps/apps/spreadsheeteditor/main/index.html`);
		await page.evaluate(async () => {
			const r = await fetch('/Editor.bin');
			window.__bin = await r.arrayBuffer();
			const api = new Asc.spreadsheet_api({ 'id-view': 'editor_sdk' });
			api.asc_registerCallback('asc_onDocumentContentReady', () => { window.__ready = true; });
			for (let i = 0; i < 300 && !api.isLoadFullApi; i++) await new Promise(r => setTimeout(r, 100));
			const docInfo = new Asc.asc_CDocInfo();
			docInfo.put_Id('test'); docInfo.put_Url('/tmp/x/book.xlsx'); docInfo.put_Title('book.xlsx'); docInfo.put_Format('xlsx');
			docInfo.put_Permissions({ edit: true }); docInfo.put_OfflineApp(true);
			const ui = new Asc.asc_CUserInfo(); ui.put_Id('uid1'); ui.put_FullName('T'); docInfo.put_UserInfo(ui);
			api.asc_registerCallback('asc_onGetEditorPermissions', () => { window.__perm = true; });
			api.asc_setDocInfo(docInfo);
			api.asc_getEditorPermissions();
			for (let i = 0; i < 100 && !window.__perm; i++) await new Promise(r => setTimeout(r, 50));
			api.asc_setViewMode(false);
			api.asc_LoadDocument();
		});
		await page.waitForFunction(() => window.__startOpen, null, { timeout: 60000 });
		let changesJs = null;
		if (mode === 'open' && arg5 && arg5 !== '-') {
			// what onlocaldocument_loadend builds: last ',' -> ']', count = quotes/2
			let s = fs.readFileSync(arg5, 'utf8');
			s = s.slice(0, -1) + ']';
			const n = (s.match(/"/g) || []).length >> 1;
			changesJs = { arr: JSON.parse('[' + s), n };
		}
		await page.evaluate((ch) => {
			AscFonts.CFontFileLoader.prototype.LoadFontAsync = function (basePath, callback) {
				this.callback = callback;
				if (-1 !== this.Status) return true;
				this.Status = 2;
				const ff = this;
				fetch('/font?p=' + encodeURIComponent(this.Id)).then(r => r.ok ? r.arrayBuffer() : null).then(buf => {
					if (!buf) { ff.Status = 1; return; }
					ff.Status = 0;
					const fontStreams = AscFonts.g_fonts_streams, idx = fontStreams.length, data = new Uint8Array(buf);
					fontStreams[idx] = new AscFonts.FontStream(data, data.length);
					ff.SetStreamIndex(idx);
					if (ff.callback) ff.callback();
					if (ff['externalCallback']) ff['externalCallback']();
				});
			};
			if (ch) {
				window.DesktopOfflineAppDocumentApplyChanges(ch.arr);
				window.AscDesktopEditor.LocalFileSetOpenChangesCount(ch.n);
			}
			window.DesktopOfflineAppDocumentEndLoad('/tmp/x/book.xlsx', 'binary_content://Editor.bin', 0);
		}, changesJs);
		await page.waitForFunction(() => window.__ready, null, { timeout: 60000 });
		await page.waitForTimeout(500);
		if (mode === 'open') {
			const r = await page.evaluate(dump);
			console.log(JSON.stringify({ sheets: r, errors: errors.filter(e => !/GL Driver/.test(e)).slice(0, 3) }));
			return;
		}
		const r = await page.evaluate(async ({ idx, dumpSrc }) => {
			const api = Asc.editor;
			const dump = eval('(' + dumpSrc + ')');
			const before = dump();
			const H = AscCommon.History;
			// Sheet1: type into A1 (replacing its text)
			H.Create_NewPoint();
			api.wbModel.getWorksheet(0).getRange2('A1').setValue('typed on Sheet1');
			// Sheet2: insert a row above row 1 (the UI command), then type into the new, empty A1
			api.asc_showWorksheet(1);
			api.wb.getWorksheet().setSelection(new Asc.Range(0, 0, 0, 0));
			api.asc_insertCells(Asc.c_oAscInsertOptions.InsertRows);
			H.Create_NewPoint();
			api.wbModel.getWorksheet(1).getRange2('A1').setValue('typed on Sheet2');
			api.asc_showWorksheet(0);
			api.asc_Save(true);
			for (let i = 0; i < 100 && !window.__changes.length; i++) await new Promise(r => setTimeout(r, 100));
			const edited = dump();
			const ok = api.copyToNewWorkbook([idx]);
			return { before, edited, ok, workbook: window.__workbook, changes: window.__changes };
		}, { idx: Number(arg6), dumpSrc: dump.toString() });
		let out = '';
		for (const c of r.changes) {
			const arr = Array.isArray(c.str) ? c.str.slice(0, c.count) : [c.str];
			for (const s of arr) out += '"' + s + '",';
		}
		fs.mkdirSync(arg5, { recursive: true });
		fs.writeFileSync(path.join(arg5, 'changes0.json'), out);
		fs.writeFileSync(path.join(arg5, 'EditorForAsLocal.bin'), Buffer.from(r.workbook || '', 'base64'));
		console.log(JSON.stringify({ before: r.before, edited: r.edited, openWorkbook: r.ok, changeBatches: r.changes.length, errors: errors.filter(e => !/GL Driver/.test(e)).slice(0, 3) }));
	} finally {
		await browser.close();
		srv.close();
	}
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });

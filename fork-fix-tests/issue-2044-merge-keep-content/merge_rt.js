// Real cell editor (headless Chromium, stubbed desktop host): select Src!B3:B6 and run the Merge menu's
// command (asc_mergeCellsDataLost, then asc_mergeCells(option)), then Undo. node merge_rt.js <sdkjs> <Editor.bin> <AllFonts.js> [option name]
const fs = require('fs');
const path = require('path');
const startServer = require('./server');
const PW = process.env.RD_PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const { chromium } = require(PW);

const initStub = () => {
	const known = {
		CryptoMode: 0,
		LocalStartOpen() { window.__startOpen = true; },
		GetOpenedFile() { return window.__bin; },
		CheckUserId() { return 'uid1'; },
		LocalFileGetOpenChangesCount() { return 0; },
		LocalFileSetOpenChangesCount() {},
		LocalFileGetSaved() { return true; },
		LocalFileGetSourcePath() { return '/tmp/x/book.xlsx'; },
		IsLocalFile() { return true; },
		LocalFileSaveChanges() {},
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

(async () => {
	const [sdkjsTree, bin, allFonts, mode] = process.argv.slice(2);
	const srv = await startServer({ sdkjsRoots: [path.join(sdkjsTree, 'deploy', 'sdkjs'), sdkjsTree], page: path.join(__dirname, 'page.html'), allFonts, editorBin: bin });
	const chrome = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
	const browser = await chromium.launch(fs.existsSync(chrome) ? { executablePath: chrome } : {});
	const errors = [];
	try {
		const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
		page.on('pageerror', e => errors.push(String(e && e.stack || e)));
		page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 300)); });
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
		await page.evaluate(() => {
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
			window.DesktopOfflineAppDocumentEndLoad('/tmp/x/book.xlsx', 'binary_content://Editor.bin', 0);
		});
		await page.waitForFunction(() => window.__ready, null, { timeout: 60000 });
		await page.waitForTimeout(300);
		const r = await page.evaluate(async ({ option }) => {
			const api = Asc.editor;
			const idle = async () => { for (let i = 0; i < 100 && api.isLongAction(); i++) await new Promise(r => setTimeout(r, 50)); await new Promise(r => setTimeout(r, 50)); };
			const ws = api.wbModel.getWorksheet(1);
			const dump = () => {
				const out = {};
				for (let r = 2; r < 6; r++) ws._getCell(r, 1, (c) => { out['B' + (r + 1)] = c.getValueWithoutFormat(); });
				const a = ws.getRange3(2, 1, 2, 1);
				out.wrap = !!(a.getAlign() && a.getAlign().getWrap());
				const m = ws.getMergedByCell(2, 1);
				out.merged = m ? [m.r1, m.c1, m.r2, m.c2].join(',') : null;
				return out;
			};
			api.asc_showWorksheet(1);
			api.wb.getWorksheet().setSelection(new Asc.Range(1, 2, 1, 5));   // Src!B3:B6
			const before = dump();
			const value = Asc.c_oAscMergeOptions[option];
			const dataLost = api.asc_mergeCellsDataLost(value);
			api.asc_mergeCells(value);
			await idle();
			const after = dump();
			api.asc_Undo();
			await idle();
			const undone = dump();
			return { option, value: value === undefined ? null : value, dataLost, before, after, undone };
		}, { option: mode || 'MergeKeepContent' });
		console.log(JSON.stringify(Object.assign(r, { errors: errors.filter(e => !/GL Driver/.test(e)).slice(0, 3) })));
	} finally {
		await browser.close();
		srv.close();
	}
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });

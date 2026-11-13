// Real cell editor (headless Chromium, stubbed desktop host): copy Src!B3:B6 with the real copy code,
// paste it on Dest!B3 and then apply Paste Special > Values (the paste button path), and report the
// destination cells' value, cell font and rich-text run fonts.
// node paste_rt.js <sdkjs tree> <Editor.bin> <AllFonts.js> [route: internal|html] [mode: special|normal|shortcut|shortcut-off]
// shortcut*: Ctrl+Shift+V (Cmd+Shift+V) through Api.onKeyDown with the option on/off, Undo/Redo, then a plain paste on D3.
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
		// the native Paste(): the host makes the renderer fire a real paste event with the system clipboard
		Paste() { window.__nativePaste = (window.__nativePaste || 0) + 1; setTimeout(() => window.__firePaste && window.__firePaste(), 0); },
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
	const [sdkjsTree, bin, allFonts, route, mode] = process.argv.slice(2);
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
		const r = await page.evaluate(async ({ route, mode }) => {
			const api = Asc.editor, F = AscCommon.c_oAscClipboardDataFormat, sp = AscCommon.g_specialPasteHelper;
			const idle = async () => { for (let i = 0; i < 200 && (sp.pasteStart || api.isLongAction()); i++) await new Promise(r => setTimeout(r, 50)); await new Promise(r => setTimeout(r, 100)); };
			const dump = () => {
				const ws = api.wbModel.getWorksheet(0), out = {};
				for (let r = 2; r < 6; r++) {
					ws._getCell(r, 1, (cell) => {
						const f = cell.getFont();
						out['B' + (r + 1)] = {
							text: cell.getValueWithoutFormat(), shown: cell.getValueWithFormat ? undefined : undefined,
							numFormat: cell.getNumFormatStr(),
							font: f.getName() + ' ' + f.getSize() + (f.getBold() ? ' b' : '') + (f.getItalic() ? ' i' : ''),
							runs: cell.multiText ? cell.multiText.map(x => (x.format ? (x.format.getName() + ' ' + x.format.getSize()) : '-') + ':' + JSON.stringify(x.text)) : null,
						};
					});
				}
				return out;
			};
			// copy Src!B3:B6 with the real copy code (the formats the desktop asks for)
			api.asc_showWorksheet(1);
			api.wb.getWorksheet().setSelection(new Asc.Range(1, 2, 1, 5));
			const clip = { d: {}, pushData(f, v) { this.d[f] = v; } };
			api.asc_CheckCopy(clip, F.Internal | F.Html | F.Text);
			api.asc_showWorksheet(0);
			api.wb.getWorksheet().setSelection(new Asc.Range(1, 2, 1, 2));
			const before = dump();
			const firePaste = () => {
				if (route === 'html') {
					AscCommon.g_clipboardBase.CommonIframe_PasteStart(clip.d[F.Html], clip.d[F.Text]);
				} else {
					api.asc_PasteData(F.Internal, clip.d[F.Internal], null, clip.d[F.Text]);
				}
			};
			window.__firePaste = firePaste;
			let keyResult = null;
			if (mode === 'shortcut' || mode === 'shortcut-off') {
				// Ctrl+Shift+V (Cmd+Shift+V on macOS) through the real key entry (Api.onKeyDown)
				api.asc_setPasteValuesShortcut && api.asc_setPasteValuesShortcut(mode === 'shortcut');
				const mac = AscCommon.AscBrowser.isMacOs;
				const ev = new KeyboardEvent('keydown', { keyCode: 86, which: 86, key: 'V', code: 'KeyV', ctrlKey: !mac, metaKey: mac, shiftKey: true, bubbles: true, cancelable: true });
				api.onKeyDown(ev);
				keyResult = ev.defaultPrevented ? 'prevented' : 'not prevented';
				// not prevented: the keys' own paste event reaches the editor, as a Ctrl+V does
				if (!ev.defaultPrevented) firePaste();
				await new Promise(r => setTimeout(r, 50));
				await idle();
				window.__afterKeys = dump();
				// one Undo takes the whole paste back
				api.asc_Undo();
				await idle();
				window.__afterUndo = dump();
				api.asc_Redo();
				await idle();
				// then a plain paste (Ctrl+V) of the same clipboard on column D: must be a normal paste
				api.wb.getWorksheet().setSelection(new Asc.Range(3, 2, 3, 2));
				firePaste();
				await idle();
				const ws = api.wbModel.getWorksheet(0);
				ws._getCell(2, 3, (cell) => { window.__plainAfter = cell.getFont().getName() + ' ' + cell.getFont().getSize() + ' runs=' + (cell.multiText ? cell.multiText.length : 0); });
			} else {
				firePaste();
				await idle();
				if (mode !== 'normal') {
					const props = new Asc.SpecialPasteProps();
					props.asc_setProps(Asc.c_oSpecialPasteProps.pasteOnlyValues);
					api.asc_SpecialPaste(props);
					await idle();
				}
			}
			return { before, after: dump(), native: window.__nativePaste || 0, keyResult, plainAfter: window.__plainAfter, afterKeys: window.__afterKeys, afterUndo: window.__afterUndo, formats: Object.keys(clip.d) };
		}, { route: route || 'internal', mode: mode || 'special' });
		console.log(JSON.stringify(Object.assign(r, { errors: errors.filter(e => !/GL Driver/.test(e)).slice(0, 3) })));
	} finally {
		await browser.close();
		srv.close();
	}
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });

// #2002 editor round trip in the REAL slide editor (headless Chromium, stubbed desktop host,
// adapted from the word harness used for earlier fixes):
// open Editor.bin -> report every video's UniMedia -> duplicate the slide (copies the video)
// -> move the original video -> save -> write the changes exactly as the desktop host does
// (changes/changes0.json: "chg","chg",...).
// usage: node editor_rt.js <built sdkjs tree> <Editor.bin> <AllFonts.js> <out changes0.json> [settings JSON]
// With a settings JSON (a list of asc_setMediaSettings arguments) it instead selects the slide's video,
// reports asc_getMediaSettings and every command sent to the desktop player
// (AscDesktopEditor.CallMediaPlayerCommand) before and after applying them in turn, and saves.
const fs = require('fs');
const path = require('path');
const startServer = require('./server');
const PW = process.env.RD_PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const { chromium } = require(PW);

const initStub = () => {
	window.__changes = [];
	window.__log = [];
	window.__player = [];
	const known = {
		CryptoMode: 0,
		LocalStartOpen() { window.__startOpen = true; },
		GetOpenedFile() { return window.__bin; },
		CheckUserId() { return 'uid1'; },
		LocalFileGetOpenChangesCount() { return 0; },
		LocalFileGetSaved() { return true; },
		LocalFileGetSourcePath() { return '/tmp/x/new.pptx'; },
		IsLocalFile() { return true; },
		LocalFileSaveChanges(str, deleteIndex, count) { window.__changes.push({ str, deleteIndex, count }); },
		LocalFileSave() { window.__saved = (window.__saved || 0) + 1; },
		CallMediaPlayerCommand(d) { window.__player.push(JSON.parse(JSON.stringify(d))); },
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
	const [sdkjsTree, bin, allFonts, outChanges, settingsJson] = process.argv.slice(2);
	const srv = await startServer({ sdkjsRoots: [path.join(sdkjsTree, 'deploy', 'sdkjs'), sdkjsTree], page: path.join(__dirname, 'page.html'), allFonts, editorBin: bin });
	const chrome = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
	const browser = await chromium.launch(fs.existsSync(chrome) ? { executablePath: chrome } : {});
	const errors = [];
	try {
		const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
		page.on('pageerror', e => errors.push(String(e && e.stack || e)));
		await page.addInitScript(initStub);
		await page.goto(`http://127.0.0.1:${srv.address().port}/web-apps/apps/presentationeditor/main/index.html`);
		await page.evaluate(async () => {
			const r = await fetch('/Editor.bin');
			window.__bin = await r.arrayBuffer();
			const api = new Asc.asc_docs_api({ 'id-view': 'editor_sdk' });
			window.editor = api;
			api.asc_registerCallback('asc_onDocumentContentReady', () => { window.__ready = true; });
			for (let i = 0; i < 300 && !api.isLoadFullApi; i++) await new Promise(r => setTimeout(r, 100));
			const docInfo = new Asc.asc_CDocInfo();
			docInfo.put_Id('test'); docInfo.put_Url('/tmp/x/new.pptx'); docInfo.put_Title('new.pptx'); docInfo.put_Format('pptx');
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
			window.DesktopOfflineAppDocumentEndLoad('/tmp/x/new.pptx', 'binary_content://Editor.bin', 0);
		});
		await page.waitForFunction(() => window.__ready, null, { timeout: 60000 });
		if (settingsJson) {
			const r = await page.evaluate(async (aSettings) => {
				const p = editor.WordControl.m_oLogicDocument;
				const slide = p.Slides[0];
				const pic = slide.cSld.spTree.find(d => d.getMediaFileName && d.getMediaFileName());
				slide.graphicObjects.resetSelection();
				slide.graphicObjects.selectObject(pic, 0);
				slide.graphicObjects.checkShowMediaControlOnSelect();
				const pick = a => a.map(d => ({ Cmd: d.Cmd, From: d.From === undefined ? null : d.From,
					StartTime: d.StartTime === undefined ? null : d.StartTime, EndTime: d.EndTime === undefined ? null : d.EndTime }));
				const steps = [{ settings: editor.asc_getMediaSettings(), player: pick(window.__player) }];
				for (const oSettings of aSettings) {
					window.__player = [];
					editor.asc_setMediaSettings(oSettings);
					steps.push({ settings: editor.asc_getMediaSettings(), player: pick(window.__player) });
				}
				editor.asc_Save();
				for (let i = 0; i < 100 && !window.__changes.length; i++) await new Promise(r => setTimeout(r, 100));
				return { steps, changes: window.__changes };
			}, JSON.parse(settingsJson));
			let out = '';
			for (const c of r.changes) {
				const arr = Array.isArray(c.str) ? c.str.slice(0, c.count) : [c.str];
				for (const s of arr) out += '"' + s + '",';
			}
			fs.writeFileSync(outChanges, out);
			console.log(JSON.stringify({ steps: r.steps, errors: errors.slice(0, 3) }));
			return;
		}
		const r = await page.evaluate(async () => {
			const p = editor.WordControl.m_oLogicDocument;
			const media = () => p.Slides.map(s => s.cSld.spTree.filter(d => d.getMediaFileName && d.getMediaFileName())
				.map(d => { const u = d.nvPicPr.nvPr.unimedia; return { trimSt: u.trimSt === undefined ? 'undefined' : u.trimSt, trimEnd: u.trimEnd === undefined ? 'undefined' : u.trimEnd }; }));
			const opened = media();
			editor.DublicateSlide();
			const pic = p.Slides[0].cSld.spTree.find(d => d.getMediaFileName && d.getMediaFileName());
			AscCommon.History.Create_NewPoint();
			pic.spPr.xfrm.setOffX(pic.spPr.xfrm.offX + 5);
			editor.asc_Save();
			for (let i = 0; i < 100 && !window.__changes.length; i++) await new Promise(r => setTimeout(r, 100));
			return { opened, edited: media(), changes: window.__changes };
		});
		let out = '';
		for (const c of r.changes) {
			const arr = Array.isArray(c.str) ? c.str.slice(0, c.count) : [c.str];
			for (const s of arr) out += '"' + s + '",';
		}
		fs.writeFileSync(outChanges, out);
		console.log(JSON.stringify({ opened: r.opened, edited: r.edited, changeBatches: r.changes.length, errors: errors.slice(0, 3) }));
	} finally {
		await browser.close();
		srv.close();
	}
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });

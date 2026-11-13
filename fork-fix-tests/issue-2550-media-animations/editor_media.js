// #2550 in the REAL slide editor (headless Chromium, stubbed desktop host; server + page of
// ../issue-2002-media-trim, the init/open code below is that harness's editor_rt.js).
// usage: node editor_media.js <built sdkjs tree> <Editor.bin> <AllFonts.js> <out changes0.json> <mode>
//   mode "add":  select a placeholder shape and try Media > Play on it, then select the slide's video and add
//                Media > Play, Pause, Stop (asc_AddAnimation, as the Animation tab does); report the effects
//                and the animation properties the tab gets; save (changes0.json as the desktop writes it)
//   mode "show": report the slide's effects, start the slide show and click through it; report every
//                command sent to the desktop player (AscDesktopEditor.CallMediaPlayerCommand) per click
const fs = require('fs');
const path = require('path');
const startServer = require('../issue-2002-media-trim/server');
const PW = process.env.RD_PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const { chromium } = require(PW);

const initStub = () => {
	window.__changes = [];
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
	const [sdkjsTree, bin, allFonts, outChanges, mode] = process.argv.slice(2);
	const srv = await startServer({ sdkjsRoots: [path.join(sdkjsTree, 'deploy', 'sdkjs'), sdkjsTree], page: path.join(__dirname, '..', 'issue-2002-media-trim', 'page.html'), allFonts, editorBin: bin });
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
		const r = await page.evaluate(async (mode) => {
			const p = editor.WordControl.m_oLogicDocument;
			const slide = p.Slides[0];
			const effects = () => (slide.timing ? slide.timing.getAllAnimEffects() : []).map(e => {
				let cmd = null;
				e.traverseTimeNodes(n => { if (n.cmd !== undefined && n.cmd !== null) { cmd = n.cmd; return true; } return false; });
				return { cls: e.cTn.presetClass, id: e.cTn.presetID, nodeType: e.cTn.nodeType, cmd, target: e.getObjectId() === (slide.cSld.spTree.find(d => d.getMediaFileName && d.getMediaFileName()) || {}).Id ? 'video' : 'other' };
			});
			const pick = a => a.map(d => ({ Cmd: d.Cmd, From: d.From === undefined ? null : d.From, IsSelected: !!d.IsSelected }));
			const pic = slide.cSld.spTree.find(d => d.getMediaFileName && d.getMediaFileName());
			if (mode === 'add') {
				const MEDIA = AscFormat.PRESET_CLASS_MEDIACALL;
				const other = slide.cSld.spTree.find(d => d !== pic);
				slide.graphicObjects.resetSelection();
				slide.graphicObjects.selectObject(other, 0);
				editor.asc_AddAnimation(MEDIA, AscFormat.MEDIACALL_PLAY, 0, null, false, false);
				const onShape = effects();
				slide.graphicObjects.resetSelection();
				slide.graphicObjects.selectObject(pic, 0);
				const ids = [AscFormat.MEDIACALL_PLAY, AscFormat.MEDIACALL_PAUSE, AscFormat.MEDIACALL_STOP];
				for (const id of ids) {
					// as a user picks the video again before each: only the video selected, no effect
					slide.timing.resetSelection();
					slide.graphicObjects.resetSelection();
					slide.graphicObjects.selectObject(pic, 0);
					editor.asc_AddAnimation(MEDIA, id, 0, null, false, false);
				}
				const added = effects();
				// what the Animation tab gets for each effect selected alone (as a click on it in the pane)
				const props = [];
				for (const e of slide.timing.getAllAnimEffects()) {
					slide.timing.resetSelection();
					e.select();
					p.Document_UpdateInterfaceState();
					const stack = editor.asc_getAnimatedObjectsStack ? editor.asc_getAnimatedObjectsStack() : [];
					const a = stack.find(o => o.get_ObjectType() === Asc.c_oAscTypeSelectElement.Animation);
					const v = a && a.get_ObjectValue();
					props.push(v ? { cls: v.asc_getClass(), type: v.asc_getType() } : null);
				}
				editor.asc_Save();
				for (let i = 0; i < 100 && !window.__changes.length; i++) await new Promise(r => setTimeout(r, 100));
				return { ids, onShape, added, props, changes: window.__changes };
			}
			// show
			const opened = effects();
			const div = document.createElement('div');
			div.id = 'demo';
			div.style.cssText = 'position:absolute;left:0;top:0;width:1000px;height:800px';
			document.body.appendChild(div);
			editor.StartDemonstration('demo', 0);
			for (let i = 0; i < 50 && !editor.isSlideShow(); i++) await new Promise(r => setTimeout(r, 100));
			await new Promise(r => setTimeout(r, 500));
			const inShow = editor.isSlideShow();
			const clicks = [{ player: pick(window.__player) }];
			for (let c = 0; c < 5; c++) {
				window.__player = [];
				editor.DemonstrationNextSlide();
				await new Promise(r => setTimeout(r, 700));
				clicks.push({ player: pick(window.__player) });
			}
			return { opened, inShow, clicks, changes: [] };
		}, mode);
		let out = '';
		for (const c of r.changes) {
			const arr = Array.isArray(c.str) ? c.str.slice(0, c.count) : [c.str];
			for (const s of arr) out += '"' + s + '",';
		}
		fs.writeFileSync(outChanges, out);
		delete r.changes;
		r.errors = errors.slice(0, 3);
		console.log(JSON.stringify(r));
	} finally {
		await browser.close();
		srv.close();
	}
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });

// #2484: opens an Editor.bin in the REAL slide editor (headless Chromium, stubbed desktop host; server, page and
// open code of ../issue-2002-media-trim) with the deck's media/ served, draws slide 1 with the editor's own canvas
// graphics as the thumbnails do (CGraphics + DrawPage) and prints the RGBA of the requested points (px of a
// 400 px wide rendering) as one JSON line.
// usage: node render.js <built sdkjs tree> <dir with Editor.bin + media/> <AllFonts.js> '<[[x,y],...]>'
const fs = require('fs');
const path = require('path');
const startServer = require('../issue-2002-media-trim/server');
const PW = process.env.RD_PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const { chromium } = require(PW);

const initStub = () => {
	const known = {
		CryptoMode: 0,
		LocalStartOpen() { window.__startOpen = true; },
		GetOpenedFile() { return window.__bin; },
		CheckUserId() { return 'uid1'; },
		LocalFileGetOpenChangesCount() { return 0; },
		LocalFileGetSaved() { return true; },
		LocalFileGetSourcePath() { return '/tmp/x/new.pptx'; },
		IsLocalFile() { return true; },
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
	const [sdkjsTree, binDir, allFonts, pointsJson] = process.argv.slice(2);
	const srv = await startServer({ sdkjsRoots: [path.join(sdkjsTree, 'deploy', 'sdkjs'), sdkjsTree], page: path.join(__dirname, '..', 'issue-2002-media-trim', 'page.html'), allFonts, editorBin: path.join(binDir, 'Editor.bin') });
	const chrome = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
	const browser = await chromium.launch(fs.existsSync(chrome) ? { executablePath: chrome } : {});
	const errors = [];
	try {
		const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
		page.on('pageerror', e => errors.push(String(e && e.stack || e)));
		// the document's pictures (media/<name>), wherever the editor asks for them
		await page.route(/\/media\/[^/?]+$/, route => {
			const f = path.join(binDir, 'media', path.basename(new URL(route.request().url()).pathname));
			if (fs.existsSync(f)) route.fulfill({ status: 200, contentType: 'image/png', body: fs.readFileSync(f) });
			else route.fulfill({ status: 404 });
		});
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
		const r = await page.evaluate(async (points) => {
			const p = editor.WordControl.m_oLogicDocument;
			const pic = p.Slides[0].cSld.spTree.find(d => d.blipFill);
			// the desktop opens a document from file:// (DesktopOfflineAppDocumentEndLoad), which a page served
			// over http cannot load: the pictures are taken from this server instead (/doc/media/<name>)
			AscCommon.g_oDocumentUrls.documentUrl = location.origin + '/doc';
			const url = AscCommon.getFullImageSrc2(pic.blipFill.RasterImageId);
			await new Promise(res => editor.ImageLoader.LoadImagesWithCallback([url], res, null));
			for (let i = 0; i < 100; i++) {
				const im = editor.ImageLoader.map_image_index[url];
				if (im && im.Image && im.Status === AscFonts.ImageLoadStatus.Complete) break;
				await new Promise(r => setTimeout(r, 100));
			}
			const im = editor.ImageLoader.map_image_index[url];
			const wMM = p.GetWidthMM(), hMM = p.GetHeightMM();
			const w = 400, h = Math.round(400 * hMM / wMM);
			const c = document.createElement('canvas');
			c.width = w; c.height = h;
			const g = new AscCommon.CGraphics();
			g.IsNoDrawingEmptyPlaceholder = true;
			g.IsThumbnail = true;
			g.init(c.getContext('2d'), w, h, wMM, hMM);
			g.m_oFontManager = AscCommon.g_fontManager;
			g.transform(1, 0, 0, 1, 0, 0);
			p.DrawPage(0, g);
			const ctx = c.getContext('2d');
			const effects = pic.blipFill.Effects.map(e => e.constructor && e.Type);
			const pics = p.Slides[0].cSld.spTree.map(d => ({ type: d.getObjectType(), x: d.x, y: d.y, w: d.extX, h: d.extY,
				brush: !!(d.brush && d.brush.fill), url: d.blipFill && d.blipFill.RasterImageId }));
			const dump = c.toDataURL('image/png');
			return { dump, pics, url, imageLoaded: !!(im && im.Status === AscFonts.ImageLoadStatus.Complete && im.Image && im.Image.width > 0), effects,
				px: points.map(([x, y]) => Array.from(ctx.getImageData(x, y, 1, 1).data)) };
		}, JSON.parse(pointsJson));
		if (process.env.RENDER_DUMP)
			fs.writeFileSync(process.env.RENDER_DUMP, Buffer.from(r.dump.split(',')[1], 'base64'));
		delete r.dump;
		r.errors = errors.slice(0, 3);
		console.log(JSON.stringify(r));
	} finally {
		await browser.close();
		srv.close();
	}
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1); });

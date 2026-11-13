// Opens the REAL editor (web-apps source in dev mode + built sdkjs) in headless Chromium with a stubbed
// desktop host, the way the desktop app does: api/documents/index.html (index.html.desktop) -> DocsAPI
// iframe -> apps/<editor>/main/index.html; the sdk asks the host to open, the host answers with
// DesktopOfflineAppDocumentEndLoad(Editor.bin).
// (#733 copy of issue-1801-command-search/open.js; adds the host calls mail merge uses - the native file
// dialog, convertFile (the real x2t, run by the test through opts.host.convert), loadLocalFile and
// OpenBinaryAsNewFile - with their in-app shapes from desktop-sdk client_renderer_wrapper.cpp.)
const fs = require('fs');
const path = require('path');
const startServer = require('./server');
const PW = process.env.RD_PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const { chromium } = require(PW);

const initStub = (storage) => {
	try { for (const k in storage) localStorage.setItem(k, storage[k]); } catch (e) {}
	// The app loads the editors from file://, so sdkjs asc_isOffline() is true there (apiBase.js checks the
	// protocol); this harness serves them over http. Pin asc_isOffline to true on the api as soon as it exists -
	// before the editor asks for it (Main.js onEditorPermissions) and over word/Local/api.js's own override.
	let ascObj;
	Object.defineProperty(window, 'Asc', { configurable: true, get() { return ascObj; }, set(v) {
		if (v === ascObj) return;
		ascObj = v;
		let api;
		v && Object.defineProperty(v, 'asc_docs_api', { configurable: true, enumerable: true, get() { return api; }, set(a) {
			api = a;
			a && a.prototype && Object.defineProperty(a.prototype, 'asc_isOffline', { configurable: true, get() { return () => true; }, set() {} });
		} });
	} });
	const known = {
		CryptoMode: 0,
		LocalStartOpen() { window.__startOpen = true; },
		GetOpenedFile() { return window.__bin; },
		CheckUserId() { return 'uid1'; },
		LocalFileGetOpenChangesCount() { return 0; },
		LocalFileSetOpenChangesCount() {},
		LocalFileGetSaved() { return true; },
		LocalFileGetSourcePath() { return '/tmp/x/doc'; },
		IsLocalFile() { return true; },
		LocalFileSaveChanges() {},
		GetInstallPlugins() { return '[{"url":"","pluginsData":[]},{"url":"","pluginsData":[]}]'; },
		GetSupportedScaleValues() { return [1, 2]; },
		IsSupportMedia() { return false; },
		isBlockchainSupport() { return false; },
		GetImageBase64() { return ''; },
		GetEncryptedHeader() { return 'ENCRYPTED;'; },
		GetFontThumbnailHeight() { return 28; },
		getViewportSettings() { return { widgetType: 'tab' }; },
		// the in-app OpenFilenameDialog calls back with a path (an array when ismulti)
		OpenFilenameDialog(filter, ismulti, callback) {
			(window.__dialogs = window.__dialogs || []).push(filter);
			window.rdHostPick(filter).then(p => callback(ismulti ? [p] : p));
		},
		// convertFile(path, format, callback(file, error)): file is { get() -> ArrayBuffer of the output, close() }
		convertFile(p, format, callback) {
			(window.__converts = window.__converts || []).push({ path: p, format });
			window.rdHostConvert(p, format).then(r => {
				const buf = r.b64 ? Uint8Array.from(atob(r.b64), c => c.charCodeAt(0)).buffer : null;
				callback(buf ? { get() { return buf; }, close() {} } : undefined, r.code);
			});
		},
		loadLocalFile(p, callback) {
			(window.__reads = window.__reads || []).push(p);
			window.rdHostRead(p).then(b64 => callback(b64 ? Uint8Array.from(atob(b64), c => c.charCodeAt(0)) : null));
		},
		OpenBinaryAsNewFile(b64) { (window.__newFiles = window.__newFiles || []).push(b64); return true; },
	};
	window.RendererProcessVariable = { theme: { id: 'theme-light', type: 'light', system: 'light' }, localthemes: {} };
	window.AscDesktopEditor = new Proxy(known, {
		get(t, k) {
			if (k in t) return t[k];
			if (typeof k !== 'string' || k === 'then' || k === 'toJSON') return undefined;
			return function () { return undefined; };
		},
	});
};

// The editor frame is returned once the document is being opened; the caller waits for the app to be ready.
// returns { browser, page, frame, srv, errors }
async function openEditor({ webapps, webappsDeploy, sdkjs, allFonts, editorBin, doctype, filetype, storage, viewport, host }) {
	const srv = await startServer({ webapps, webappsDeploy, sdkjs, allFonts, editorBin });
	const chrome = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
	const browser = await chromium.launch(fs.existsSync(chrome) ? { executablePath: chrome } : {});
	const errors = [];
	const page = await browser.newPage({ viewport: viewport || { width: 1600, height: 1000 } });
	page.on('pageerror', e => errors.push(String(e && e.stack || e)));
	if (process.env.RD_DEBUG) page.on('console', m => /error/i.test(m.type() + m.text()) && console.log('console:', m.type(), m.text().slice(0, 600)));
	await page.exposeFunction('rdHostPick', (filter) => host && host.pick ? host.pick(filter) : '');
	await page.exposeFunction('rdHostConvert', (p, format) => host && host.convert ? host.convert(p, format) : { code: 89 });
	await page.exposeFunction('rdHostRead', (p) => host && host.read ? host.read(p) : null);
	await page.addInitScript(initStub, storage || {});
	const port = srv.address().port;
	await page.goto(`http://127.0.0.1:${port}/web-apps/apps/api/documents/index.html?doctype=${doctype}&filetype=${filetype}&title=t.${filetype}&mode=edit&lang=en`);
	let frame = null;
	for (let i = 0; i < 1200 && !frame; i++) {
		frame = page.frames().find(f => /main\/index\.html/.test(f.url()));
		if (!frame) await new Promise(r => setTimeout(r, 100));
	}
	if (!frame) { const urls = page.frames().map(f => f.url()).join(' '); await browser.close(); srv.close(); throw new Error('editor frame did not appear: ' + urls + ' ' + errors.join(' ')); }
	await frame.waitForFunction(() => window.__startOpen, null, { timeout: 120000 });
	await frame.evaluate(async () => {
		const r = await fetch('/Editor.bin');
		window.__bin = await r.arrayBuffer();
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
		window.DesktopOfflineAppDocumentEndLoad('/tmp/x/doc', 'binary_content://Editor.bin', 0);
	});
	return { browser, page, frame, srv, errors };
}

module.exports = { openEditor };

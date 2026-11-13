// Opens the REAL editor (web-apps source in dev mode + built sdkjs) in headless Chromium with a stubbed
// desktop host, the way the desktop app does: api/documents/index.html (index.html.desktop) -> DocsAPI
// iframe -> apps/<editor>/main/index.html; the sdk asks the host to open, the host answers with
// DesktopOfflineAppDocumentEndLoad(Editor.bin). (From issue-1801-command-search/open.js; this copy
// can reload the page on the same server, so the editor's localStorage survives the reload.)
const fs = require('fs');
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

async function loadDocument(page) {
	let frame = null;
	for (let i = 0; i < 1200 && !frame; i++) {
		frame = page.frames().find(f => /main\/index\.html/.test(f.url()));
		if (!frame) await new Promise(r => setTimeout(r, 100));
	}
	if (!frame) throw new Error('editor frame did not appear: ' + page.frames().map(f => f.url()).join(' '));
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
	return frame;
}

// returns { browser, page, frame, srv, errors, reload() -> frame }
async function openEditor({ webapps, webappsDeploy, sdkjs, allFonts, editorBin, doctype, filetype, viewport }) {
	const srv = await startServer({ webapps, webappsDeploy, sdkjs, allFonts, editorBin });
	const chrome = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
	const browser = await chromium.launch(fs.existsSync(chrome) ? { executablePath: chrome } : {});
	const errors = [];
	try {
		const page = await browser.newPage({ viewport: viewport || { width: 1600, height: 1000 } });
		page.on('pageerror', e => errors.push(String(e && e.stack || e)));
		if (process.env.RD_DEBUG) page.on('console', m => /error/i.test(m.type() + m.text()) && console.log('console:', m.type(), m.text().slice(0, 600)));
		await page.addInitScript(initStub);
		const port = srv.address().port;
		await page.goto(`http://127.0.0.1:${port}/web-apps/apps/api/documents/index.html?doctype=${doctype}&filetype=${filetype}&title=t.${filetype}&mode=edit&lang=en`);
		const o = { browser, page, srv, errors, frame: await loadDocument(page) };
		o.reload = async () => { await page.reload(); o.frame = await loadDocument(page); return o.frame; };
		return o;
	} catch (e) {
		await browser.close();
		srv.close();
		throw e;
	}
}

module.exports = { openEditor };

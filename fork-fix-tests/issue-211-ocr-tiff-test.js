/*
 * #211 - "OCR for more than png and jpg files".
 *
 * 9.4's bundled OCR plugin (onlyoffice.github.io sdkjs-plugins/content/ocr) already
 * reads bmp, jpg, png, gif (and, outside the desktop app, webp) - the original ask.
 * What was still wrong on the desktop: the plugin picks files with the app's own
 * image dialog (AscDesktopEditor.OpenFilenameDialog("images")), which offers TIFF,
 * and GetImageBase64 hands a TIFF back as data:image/tiff. Chromium cannot draw
 * TIFF, so the preview <img> has naturalWidth 0, and the Recognize handler dropped
 * every such picture and returned without a word - a TIFF scan gave nothing and no
 * message (the report's "no error message is shown"). A file the app could not
 * read at all (GetImageBase64 returns "") was dropped the same silent way. Yet
 * tesseract decodes the bytes itself (leptonica in WebAssembly reads TIFF), so
 * nothing stops the TIFF from being recognized.
 * Fix (scripts/ocr.js): data:image/tiff pictures are kept for tesseract (preview
 * shows the file name), a file the app could not read gets the plugin's existing
 * "OCR plugin cannot read this file." alert, and Recognize with nothing readable
 * says so in the status line.
 *
 * This test serves the REAL plugin (index.html markup, scripts/ocr.js, the bundled
 * tesseract.js worker/core, jQuery, select2) to headless Chromium, stubs only the
 * host (window.Asc.plugin; AscDesktopEditor.OpenFilenameDialog/GetImageBase64 answer
 * as the native code does: data:image/<sniffed type>;base64 or ""), clicks Load File
 * and Recognize, and checks the recognized text and the messages:
 *   - a TIFF is recognized (BASELINE: nothing, no message);
 *   - PNG + an unreadable file: the PNG is recognized and the unreadable file is
 *     named in an alert (BASELINE: silently dropped);
 *   - a PNG alone is recognized both before and after (no regression).
 * The English language data comes from the CDN the plugin uses (cached under
 * $TMPDIR/rd-ocr-langdata after the first run), so the first run needs the network.
 *
 * NOT claimed: no multi-page TIFF (tesseract reads the first page), no PDF OCR (the
 * report's main ask - a PDF has to be rendered to pictures first; not done here);
 * the plugin was not run inside the app (needs a GUI check: Plugins > OCR > Load
 * File > a .tif > Recognize).
 *
 *   node issue-211-ocr-tiff-test.js             -> passes
 *   BASELINE=1 node issue-211-ocr-tiff-test.js  -> fails
 * RD_REPO=<onlyoffice.github.io checkout> (default ../onlyoffice.github.io),
 * BASE_REF (default: the fix commit's parent), PLAYWRIGHT / RD_CHROME as in
 * issue-1664-store-html-test.js.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const zlib = require('zlib');

const REPO = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'onlyoffice.github.io'));
const BASE_REF = process.env.BASE_REF || '94a3e9c5^';
const BASELINE = !!process.env.BASELINE;
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';
const PLUGIN = 'sdkjs-plugins/content/ocr';
const CACHE = path.join(os.tmpdir(), 'rd-ocr-langdata');

function read(rel) {
	if (BASELINE)
		return execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${PLUGIN}/${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 });
	return fs.readFileSync(path.join(REPO, PLUGIN, rel), 'utf8');
}

// host stubs: what plugins.js and the desktop bridge provide, nothing of the plugin itself
const STUBS = `<script>
window.__alerts = []; window.alert = function (s) { window.__alerts.push(String(s)); };
window.PerfectScrollbar = function () { this.update = function () {}; };
window.Asc = { plugin: { resizeWindow: function () {}, executeMethod: function () {}, tr: function (s) { return s; },
	onThemeChangedBase: function () {} } };
window.__files = []; window.__images = {};
window.AscDesktopEditor = {
	OpenFilenameDialog: function (filter, multi, cb) { window.__filter = filter; cb(window.__files.slice()); },
	GetImageBase64: function (file, noHeader) { return window.__images[file] || ''; }
};
</script>`;

function indexHtml() {
	let html = read('index.html');
	// remote plugin API scripts/styles are the host's; the IE switch is replaced by the scripts it writes
	html = html.replace(/<script[^>]*src="https:[^"]*"[^>]*><\/script>/g, '').replace(/<link[^>]*href="https:[^"]*"[^>]*>/g, '');
	html = html.replace(/<script type="text\/javascript">[\s\S]*?document\.write[\s\S]*?<\/script>/,
		'<script src="vendor/tesseract/tesseract.min.js"></script><script src="scripts/ocr.js"></script>');
	return html.replace('<head>', '<head>' + STUBS);
}

// sample pictures drawn by Chromium; TIFF written here (uncompressed RGBA strips)
function tiffFromRgba(w, h, rgba) {
	const entries = [[256, 3, 1, w], [257, 3, 1, h], [258, 3, 4, 0], [259, 3, 1, 1], [262, 3, 1, 2],
		[273, 4, 1, 0], [277, 3, 1, 4], [278, 3, 1, h], [279, 4, 1, rgba.length], [284, 3, 1, 1], [338, 3, 1, 2]];
	const ifdOff = 8, ifdLen = 2 + entries.length * 12 + 4, bpsOff = ifdOff + ifdLen, dataOff = bpsOff + 8;
	const b = Buffer.alloc(dataOff + rgba.length);
	b.write('II', 0); b.writeUInt16LE(42, 2); b.writeUInt32LE(ifdOff, 4); b.writeUInt16LE(entries.length, ifdOff);
	entries.forEach(([tag, type, count, val], i) => {
		const o = ifdOff + 2 + i * 12;
		if (tag === 258) val = bpsOff;
		if (tag === 273) val = dataOff;
		b.writeUInt16LE(tag, o); b.writeUInt16LE(type, o + 2); b.writeUInt32LE(count, o + 4);
		if (type === 3 && count === 1) b.writeUInt16LE(val, o + 8); else b.writeUInt32LE(val, o + 8);
	});
	for (let i = 0; i < 4; ++i) b.writeUInt16LE(8, bpsOff + i * 2);
	Buffer.from(rgba).copy(b, dataOff);
	return b;
}

async function main() {
	const { chromium } = require(PLAYWRIGHT);
	const root = path.join(REPO, PLUGIN);
	const server = http.createServer((req, res) => {
		const u = decodeURIComponent(req.url.split('?')[0]);
		let body;
		try {
			if (u === '/' || u === '/index.html') body = indexHtml();
			else if (u === '/scripts/ocr.js') body = read('scripts/ocr.js');
			else body = fs.readFileSync(path.join(root, path.normalize(u).replace(/^([/\\])+/, '')));
		} catch (e) { res.writeHead(404); return res.end(); }
		const type = /\.html?$|^\/$/.test(u) ? 'text/html' : /\.js$/.test(u) ? 'application/javascript' : /\.css$/.test(u) ? 'text/css' : 'application/octet-stream';
		res.writeHead(200, { 'Content-Type': type }); res.end(body);
	});
	await new Promise((r) => server.listen(0, '127.0.0.1', r));
	const base = 'http://127.0.0.1:' + server.address().port + '/';
	const browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
	let failed = 0;
	const check = (ok, what) => { console.log((ok ? 'ok   ' : 'FAIL ') + what); if (!ok) ++failed; };
	try {
		const ctx = await browser.newContext();
		// language data: the plugin's own CDN URL, kept in a local cache
		fs.mkdirSync(CACHE, { recursive: true });
		await ctx.route(/cdn\.jsdelivr\.net\/npm\/@tesseract\.js-data\//, async (route) => {
			const f = path.join(CACHE, route.request().url().replace(/[^A-Za-z0-9._-]/g, '_'));
			if (!fs.existsSync(f)) {
				const r = await route.fetch();
				fs.writeFileSync(f, await r.body());
			}
			await route.fulfill({ status: 200, contentType: 'application/gzip', body: fs.readFileSync(f) });
		});

		// sample text pictures
		const page0 = await ctx.newPage();
		await page0.goto(base + 'index.html');
		const pic = await page0.evaluate(() => {
			const c = document.createElement('canvas'); c.width = 600; c.height = 120;
			const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, 600, 120);
			x.fillStyle = '#000'; x.font = '48px Arial'; x.fillText('Hello Ration OCR', 20, 75);
			return { png: c.toDataURL('image/png'), rgba: Array.from(x.getImageData(0, 0, 600, 120).data) };
		});
		await page0.close();
		const tiff = 'data:image/tiff;base64,' + tiffFromRgba(600, 120, pic.rgba).toString('base64');

		async function run(files, images) {
			const page = await ctx.newPage();
			page.on('pageerror', (e) => console.log('  page error: ' + e.message));
			await page.goto(base + 'index.html');
			await page.evaluate(([f, im]) => { window.__files = f; window.__images = im; window.Asc.plugin.init(); }, [files, images]);
			await page.click('#load-file-button-id');
			await page.waitForTimeout(500);
			await page.evaluate(() => document.getElementById('recognize-button').click());
			// done when the Recognize button is enabled again with text, or nothing started
			await page.waitForFunction(() => !document.getElementById('recognize-button').hasAttribute('disabled') &&
				!/Recognizing/.test(document.getElementById('status-label').textContent), null, { timeout: 120000 }).catch(() => {});
			const r = await page.evaluate(() => ({
				filter: window.__filter,
				text: document.getElementById('text-container-div').textContent.replace(/\s+/g, ' ').trim(),
				status: document.getElementById('status-label').textContent,
				alerts: window.__alerts
			}));
			await page.close();
			return r;
		}

		let r = await run(['/scans/page.tif'], { '/scans/page.tif': tiff });
		console.log('  TIFF: text="' + r.text + '" status="' + r.status + '"');
		check(r.filter === 'images', 'the plugin uses the app image dialog');
		check(/Hello Ration OCR/.test(r.text), 'a TIFF from the image dialog is recognized');

		r = await run(['/a/t.png', '/a/broken.heic'], { '/a/t.png': pic.png });
		console.log('  PNG+unreadable: text="' + r.text + '" alerts=' + JSON.stringify(r.alerts));
		check(/Hello Ration OCR/.test(r.text), 'the PNG next to an unreadable file is recognized');
		check(r.alerts.length === 1 && /broken\.heic/.test(r.alerts[0]), 'the unreadable file is named in a message');

		r = await run(['/b/broken.heic'], {});
		console.log('  unreadable only: status="' + r.status + '" alerts=' + r.alerts.length);
		check(r.alerts.length + (r.status ? 1 : 0) > 0, 'a file that cannot be read gives a message, not silence');

		r = await run(['/a/t.png'], { '/a/t.png': pic.png });
		check(/Hello Ration OCR/.test(r.text), 'a PNG alone is recognized (unchanged)');
	} finally {
		await browser.close();
		server.close();
	}
	console.log(failed ? failed + ' check(s) FAILED' : 'PASS: TIFF pictures are recognized and unreadable files are reported');
	process.exit(failed ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });

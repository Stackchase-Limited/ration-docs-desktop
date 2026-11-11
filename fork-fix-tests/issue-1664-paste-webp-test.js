/*
 * #1664 (security follow-up) - pasted WebP/AVIF pictures were decoded by Chromium 109.
 *
 * Our CEF 109 has the libwebp heap overflow exploited in the wild (CVE-2023-4863)
 * and an AVIF decoder with later memory bugs. desktop-sdk now fails every WebP/AVIF
 * response in the browser process (image_guard.h, tested by issue-1664-webp-guard/),
 * but data: URLs never leave the renderer. sdkjs common/clipboard_base.js
 * CommonIframe_PasteStart writes pasted HTML - and clipboard image files, which
 * _private_onpaste reads as data: URLs - into the paste iframe with
 * document.write, and Blink loads and draws its pictures there. In the test app
 * (before the fix) a WebP and an AVIF pasted as data: URLs, also one declared
 * image/png and one written with an HTML entity (&#100;ata:), all loaded with
 * naturalWidth 64.
 *
 * Now, in the desktop editor (window.AscDesktopEditor), CommonIframe_PasteStart
 * first runs removeUnsafePastedImages: an inert DOMParser parse, every attribute
 * (style CSS-unescaped, srcdoc recursively) and <style> text searched for data:
 * URLs, decoded (percent, base64) and sniffed by their bytes; a WebP or AVIF one
 * is emptied and the document serialized. With none, the ORIGINAL string is
 * written unchanged.
 *
 * This extracts by brace matching the REAL helpers (isUnsafeImageHead,
 * getDataUrlHead, hasUnsafeDataImage, decodeCssEscapes, removeUnsafePastedImages)
 * and the REAL CommonIframe_PasteStart, and runs them in headless Chromium
 * (Playwright; it decodes WebP and AVIF, so a picture that is not removed shows a
 * naturalWidth) against a stub clipboard object whose Api.asc_PasteData records
 * what the editor would have pasted.
 *
 * Claimed: after CommonIframe_PasteStart, no WebP/AVIF picture in the paste iframe
 * is decoded (img src, declared-as-png, entity-written, srcset, SVG <image href>,
 * CSS background in a style attribute and in <style>, CSS-escaped, percent-encoded,
 * whitespace-broken base64, srcdoc iframe); PNG, JPEG, GIF, BMP data: pictures and
 * file:/http: URLs are kept; HTML without a WebP/AVIF data: URL is written as the
 * identical string; outside the desktop (no AscDesktopEditor) nothing changes.
 * NOT claimed: the insertion of a pasted picture into the document (that is the
 * native LocalFileGetImageUrl, which keeps only PNG/JPEG/GIF/SVG - checked in the
 * test app, see the report) or the GUI clipboard; data: URLs created by plugins.
 *
 * RD_REPO=<sdkjs> (default ../sdkjs next to fork-fix-tests). PLAYWRIGHT=<path of
 * the playwright package> (default /Users/osindero/dev/active/node_modules/playwright),
 * RD_CHROME=<headless Chromium> (default the installed chromium_headless_shell-1179).
 * BASELINE=1 reads the source with git show at BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'b0a9cfb763^';
const PLAYWRIGHT = process.env.PLAYWRIGHT || '/Users/osindero/dev/active/node_modules/playwright';
const RD_CHROME = process.env.RD_CHROME || '/Users/osindero/Library/Caches/ms-playwright/chromium_headless_shell-1179/chrome-mac/headless_shell';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
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
	if (at === -1) return null;
	return matched(text, text.indexOf('function', at));
}

const src = read('common/clipboard_base.js');
const helpers = ['function isUnsafeImageHead(', 'function getDataUrlHead(', 'function hasUnsafeDataImage(',
	'function decodeCssEscapes(', 'function removeUnsafePastedImages(']
	.map((m) => fnAfter(src, m)).filter(Boolean);
const constLine = (src.match(/var c_nUnsafeImageSniffBytes = \d+;/) || [''])[0];
const pasteStart = fnAfter(src, 'CommonIframe_PasteStart : function');
assert.ok(pasteStart, 'CommonIframe_PasteStart not found');

// 64x64 pictures; the WebP is lossless (VP8L, the CVE-2023-4863 code path)
const IMG = {
	webp: 'UklGRiIAAABXRUJQVlA4TBYAAAAvP8APAAfQ//5H/wNAQvj/Xovof+oH',
	avif: 'AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUEAAADrbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAAAAAAAOcGl0bQAAAAAAAQAAAB5pbG9jAAAAAEQAAAEAAQAAAAEAAAETAAAAIgAAAChpaW5mAAAAAAABAAAAGmluZmUCAAAAAAEAAGF2MDFDb2xvcgAAAABqaXBycAAAAEtpcGNvAAAAFGlzcGUAAAAAAAAAQAAAAEAAAAAQcGl4aQAAAAADCAgIAAAADGF2MUOBIAAAAAAAE2NvbHJuY2x4AAEAAgAGgAAAABdpcG1hAAAAAAAAAAEAAQQBAoMEAAAAKm1kYXQSAAoGOBV//YJAMhYWQAYYYYQAtIPtMjTyOUJqGBn2I9mA',
	png: 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABAAQMAAACQp+OdAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAAAGUExURf8AAP///0EdNBEAAAABYktHRAH/Ai3eAAAAB3RJTUUH6gsLAgslcK79tgAAAA9JREFUKM9jYBgFo4B8AAACQAABjMWrdwAAACV0RVh0ZGF0ZTpjcmVhdGUAMjAyNi0xMS0xMVQwMjoxMTozNyswMDowMOAe5WYAAAAldEVYdGRhdGU6bW9kaWZ5ADIwMjYtMTEtMTFUMDI6MTE6MzcrMDA6MDCRQ13aAAAAKHRFWHRkYXRlOnRpbWVzdGFtcAAyMDI2LTExLTExVDAyOjExOjM3KzAwOjAwxlZ8BQAAAABJRU5ErkJggg==',
	jpg: '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCABAAEADAREAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFgEBAQEAAAAAAAAAAAAAAAAAAAcI/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AnJD2bwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH//Z',
	gif: 'R0lGODlhQABAAPAAAAAA/wAAACH5BAAAAAAALAAAAABAAEAAAAJFhI+py+0Po5y02ouz3rz7D4biSJbmiabqyrbuC8fyTNf2jef6zvf+DwwKh8Si8YhMKpfMpvMJjUqn1Kr1is1qt9yuF1AAADs=',
	bmp: 'Qk1mAAAAAAAAADYAAAAoAAAABAAAAAQAAAABABgAAAAAADAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/',
};
const d = (mime, b64) => `data:${mime};base64,${b64}`;
const pct = (b64) => 'data:image/png,' + Array.from(Buffer.from(b64, 'base64')).map((c) => '%' + c.toString(16).padStart(2, '0')).join('');
const cssEsc = (s) => s.replace('data', '\\64 ata');
const broken = (b64) => b64.replace(/(.{8})/g, '$1\n ');

// [id, html of one element, must the picture stay decodable?]
const CASES = [
	['webp', `<img id="webp" src="${d('image/webp', IMG.webp)}">`, false],
	['webp-as-png', `<img id="webp-as-png" src="${d('image/png', IMG.webp)}">`, false],
	['avif-as-png', `<img id="avif-as-png" src="${d('image/png', IMG.avif)}">`, false],
	['entity', `<img id="entity" src="&#100;ata:image/png;base64,${IMG.webp}">`, false],
	['percent', `<img id="percent" src="${pct(IMG.webp)}">`, false],
	['broken-b64', `<img id="broken-b64" src="${d('image/png', broken(IMG.webp))}">`, false],
	['upper', `<img id="upper" src="DATA:IMAGE/PNG;BASE64,${IMG.webp}">`, false],
	['srcset', `<img id="srcset" srcset="${d('image/png', IMG.webp)} 1x">`, false],
	['png', `<img id="png" src="${d('image/png', IMG.png)}">`, true],
	['jpg', `<img id="jpg" src="${d('image/jpeg', IMG.jpg)}">`, true],
	['gif', `<img id="gif" src="${d('image/gif', IMG.gif)}">`, true],
	['bmp', `<img id="bmp" src="${d('image/bmp', IMG.bmp)}">`, true],
];
const BG = [
	['style-attr', `<div id="style-attr" style="width:64px;height:64px;background-image:url('${d('image/png', IMG.webp)}')">x</div>`, false],
	['style-escaped', `<div id="style-escaped" style="width:64px;height:64px;background-image:url('${cssEsc(d('image/png', IMG.webp))}')">x</div>`, false],
	['style-png', `<div id="style-png" style="width:64px;height:64px;background-image:url('${d('image/png', IMG.png)}')">x</div>`, true],
];
const STYLE_BLOCK = `<style>#style-block{width:64px;height:64px;background:url("${d('image/png', IMG.avif)}")}</style><div id="style-block">x</div>`;
const SVG = `<svg width="64" height="64"><image id="svgimg" href="${d('image/png', IMG.webp)}" width="64" height="64"/></svg>`;
const SRCDOC = `<iframe id="srcdoc" srcdoc="<img id=inner src='${d('image/png', IMG.webp)}'>"></iframe>`;

let failures = 0;
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures++; console.log('FAIL ' + name + ': ' + e.message); }
}

(async () => {
	const { chromium } = require(PLAYWRIGHT);
	const browser = await chromium.launch(fs.existsSync(RD_CHROME) ? { executablePath: RD_CHROME } : {});
	const page = await browser.newPage();
	await page.setContent('<html><body></body></html>');
	const run = (html, desktop) => page.evaluate(async ({ html, desktop, code, pasteStart }) => {
		// stubs for what CommonIframe_PasteStart touches; the code under test is the real one
		const pasted = [];
		window.AscCommon = { c_oAscClipboardDataFormat: { HtmlElement: 8 } };
		if (desktop) window.AscDesktopEditor = {}; else delete window.AscDesktopEditor;
		const g_clipboardBase = { Paste_End() {} };
		const definePastedFrom = () => null;
		const old = document.getElementById('paste-frame');
		if (old) old.remove();
		const clip = { CommonIframeId: 'paste-frame', CommonIframe: null,
			Api: { asc_PasteData: (f, body) => pasted.push(body.ownerDocument.documentElement.outerHTML.length) } };
		const make = new Function('g_clipboardBase', 'definePastedFrom', '"use strict";' + code + '\nreturn ' + pasteStart + ';');
		const written = [];
		const fn = make(g_clipboardBase, definePastedFrom);
		const frameDoc = () => window.frames['paste-frame'] && window.frames['paste-frame'].document;
		// the paste iframe exists already (as after the first paste), so the exact string
		// handed to its document.write can be recorded
		const ifr = document.createElement('iframe');
		ifr.id = ifr.name = 'paste-frame';
		document.body.appendChild(ifr);
		const proto = ifr.contentWindow.Document.prototype;
		const origWrite = proto.write;
		proto.write = function (s) { written.push(s); return origWrite.call(this, s); };
		try { fn.call(clip, html); } finally { proto.write = origWrite; }
		const fd = frameDoc();
		const wait = (img) => (img.complete ? Promise.resolve() : new Promise((r) => { img.onload = img.onerror = r; setTimeout(r, 2000); }));
		await Promise.all(Array.from(fd.images).map(wait));
		const inner = fd.getElementById('srcdoc');
		if (inner) await new Promise((r) => { if (inner.contentDocument && inner.contentDocument.readyState === 'complete') r(); else { inner.onload = r; setTimeout(r, 2000); } });
		await new Promise((r) => setTimeout(r, 300));
		const res = { written: written[0], pasted: pasted.length, imgs: {}, bg: {} };
		for (const img of fd.images) res.imgs[img.id] = img.naturalWidth;
		// a CSS background is decoded if an <img> with the same URL decodes; use the computed URL
		for (const el of fd.querySelectorAll('div[id]')) {
			const m = /url\("?(.*?)"?\)$/.exec(getComputedStyle(el).backgroundImage);
			if (!m) { res.bg[el.id] = 0; continue; }
			const probe = new Image(); probe.src = m[1];
			await new Promise((r) => { probe.onload = probe.onerror = r; setTimeout(r, 2000); });
			res.bg[el.id] = probe.naturalWidth;
		}
		const svg = fd.getElementById('svgimg');
		if (svg) {
			const href = svg.getAttribute('href') || '';
			const probe = new Image(); probe.src = href;
			await new Promise((r) => { if (!href) r(); probe.onload = probe.onerror = r; setTimeout(r, 2000); });
			res.svg = href ? probe.naturalWidth : 0;
		}
		if (inner) {
			const ii = inner.contentDocument && inner.contentDocument.getElementById('inner');
			res.srcdoc = ii ? ii.naturalWidth : 0;
		}
		return res;
	}, { html, desktop, code: [constLine].concat(helpers).join('\n'), pasteStart });

	const body = CASES.map((c) => c[1]).join('') + BG.map((c) => c[1]).join('') + STYLE_BLOCK + SVG + SRCDOC;
	const html = `<html><head><meta name="ProgId" content="Word.Document"></head><body><p>text</p>${body}</body></html>`;
	const r = await run(html, true);
	check('the paste still reaches Api.asc_PasteData', () => assert.strictEqual(r.pasted, 1));
	for (const [id, , keep] of CASES) {
		check(`${keep ? 'kept' : 'not decoded'}: <img> ${id}`, () => (keep
			? assert.strictEqual(r.imgs[id], id === 'bmp' ? 4 : 64)
			: assert.strictEqual(r.imgs[id], 0, `decoded, naturalWidth ${r.imgs[id]}`)));
	}
	for (const [id, , keep] of BG) {
		check(`${keep ? 'kept' : 'not decoded'}: CSS background ${id}`, () => (keep
			? assert.strictEqual(r.bg[id], 64)
			: assert.strictEqual(r.bg[id], 0, `decoded, naturalWidth ${r.bg[id]}`)));
	}
	check('not decoded: AVIF background in a <style> block', () => assert.strictEqual(r.bg['style-block'], 0, `decoded, naturalWidth ${r.bg['style-block']}`));
	check('not decoded: SVG <image href> WebP', () => assert.strictEqual(r.svg, 0, `decoded, naturalWidth ${r.svg}`));
	check('not decoded: WebP inside an iframe srcdoc', () => assert.strictEqual(r.srcdoc, 0, `decoded, naturalWidth ${r.srcdoc}`));
	check('the ProgId meta (pastedFrom detection) survives the rewrite', () => assert.ok(/ProgId/.test(r.written)));

	const clean = `<html><body><!--StartFragment--><p style="color:red">a&amp;b</p><img src="${d('image/png', IMG.png)}"><img src="file:///tmp/x.png"><img src="https://example.invalid/a.webp"><!--EndFragment--></body></html>`;
	const r2 = await run(clean, true);
	check('HTML without a WebP/AVIF data: URL is written as the identical string', () => assert.strictEqual(r2.written, clean));

	const r3 = await run(`<html><body>${CASES[0][1]}</body></html>`, false);
	check('outside the desktop editor (no AscDesktopEditor) the HTML is not touched', () => assert.ok(r3.written.includes(IMG.webp)));

	await browser.close();
	console.log(failures ? `${failures} check(s) FAILED` : 'all checks passed');
	process.exit(failures ? 1 : 0);
})().catch((e) => { console.log('FAIL ' + e.stack); process.exit(1); });

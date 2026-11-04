/*
 * #2506 - a grayscale JPEG 2000 image without /ColorSpace still rendered black
 * in the PDF viewer after the core fix.
 *
 * Core a1e8e1c060 fixed JPXStream2::getImageParams (PdfFile/SrcReader/
 * JPXStream2.cpp), which answered DeviceRGB for every JPX image, so a 1-byte-
 * per-pixel grayscale JPX was read 3 bytes per pixel: coloured stripes in the
 * top third, the rest never filled - black under an /SMask. That fixed x2t, but
 * the editor's PDF viewer does not use x2t: sdkjs/pdf/src/viewer.js loads
 * sdkjs/pdf/src/engine/drawingfile.js + drawingfile.wasm, an emscripten build
 * of the same PdfFile sources that was last rebuilt upstream on 2026-04-28 and
 * therefore still carried the bug.
 *
 * This loads the REAL checked-in drawingfile.js glue and drawingfile.wasm in
 * Node (a vm context standing in for the browser window; fetch() hands the
 * glue the .wasm bytes), and separately the asm.js fallback drawingfile_ie.js
 * (the same build pass, used where WebAssembly is unavailable), opens a PDF built here around a 200x200 grayscale JP2
 * (opj_compress output, light checkerboard: grey 140 / white 255, embedded
 * below) with an opaque /SMask and NO /ColorSpace, renders the page with
 * CDrawingFile.getPagePixmap and checks:
 *   - control: the same image WITH /ColorSpace /DeviceGray renders the
 *     checkerboard (no black, no colour) - this path was never broken, so it
 *     proves the harness renders correctly with either artefact;
 *   - the image without /ColorSpace renders pixel-for-pixel like the control
 *     (no black pixels, no coloured pixels).
 *
 *   RD_REPO=<sdkjs checkout>  default ../../sdkjs relative to this file
 *   BASELINE=1                read both artefacts via `git show $BASE_REF:<path>`;
 *                             must FAIL there (the 2026-04-28 binary)
 *
 * NOT claimed: the desktop app's own loader (desktop_fetch over ascdesktop://)
 * is not exercised - that was checked by hand in the test app. It
 * cannot tell whether the wasm is older than OTHER core changes - only that
 * this one is in it. Needs Node >= 18 (global Response, WebAssembly
 * streaming) and crypto.getRandomValues (glue imports getentropy).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const zlib = require('zlib');
const { execFileSync } = require('child_process');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', '..', 'sdkjs');
const BASE_REF = process.env.BASE_REF || '7f89b00088^';
const BASELINE = !!process.env.BASELINE;
const ENGINES = ['pdf/src/engine/drawingfile.js', 'pdf/src/engine/drawingfile_ie.js'];
const WASM = 'pdf/src/engine/drawingfile.wasm';

function read(rel) {
	if (BASELINE)
		return execFileSync('git', ['-C', SDKJS, 'show', BASE_REF + ':' + rel], { maxBuffer: 1 << 26 });
	return fs.readFileSync(path.join(SDKJS, rel));
}

// 200x200 8-bit grayscale JP2 (colr box: greyscale), made by opj_compress 2.5.4
const JP2 = Buffer.from(
	'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' +
	'qi//2Q==' , 'base64');
const W = 200, H = 200;

function makePdf(colorSpace) {
	const mask = zlib.deflateSync(Buffer.alloc(W * H, 255)); // opaque soft mask
	const content = 'q ' + W + ' 0 0 ' + H + ' 0 0 cm /Im1 Do Q';
	const objs = [
		'<< /Type /Catalog /Pages 2 0 R >>',
		'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
		'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ' + W + ' ' + H + '] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>',
		['<< /Type /XObject /Subtype /Image /Width ' + W + ' /Height ' + H + (colorSpace ? ' /ColorSpace ' + colorSpace : '') +
			' /Filter /JPXDecode /SMask 6 0 R /Length ' + JP2.length + ' >>', JP2],
		['<< /Length ' + content.length + ' >>', Buffer.from(content)],
		['<< /Type /XObject /Subtype /Image /Width ' + W + ' /Height ' + H +
			' /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode /Length ' + mask.length + ' >>', mask],
	];
	const parts = [Buffer.from('%PDF-1.5\n')];
	const offsets = [];
	let pos = parts[0].length;
	objs.forEach((o, i) => {
		const b = Array.isArray(o)
			? Buffer.concat([Buffer.from((i + 1) + ' 0 obj\n' + o[0] + '\nstream\n'), o[1], Buffer.from('\nendstream\nendobj\n')])
			: Buffer.from((i + 1) + ' 0 obj\n' + o + '\nendobj\n');
		offsets.push(pos);
		parts.push(b);
		pos += b.length;
	});
	parts.push(Buffer.from('xref\n0 ' + (objs.length + 1) + '\n0000000000 65535 f \n' +
		offsets.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('') +
		'trailer\n<< /Size ' + (objs.length + 1) + ' /Root 1 0 R >>\nstartxref\n' + pos + '\n%%EOF\n'));
	return Buffer.concat(parts);
}

function loadEngine(JS) {
	const glue = read(JS).toString('utf8');
	const wasm = read(WASM);
	return new Promise((resolve, reject) => {
		const ctx = { console, WebAssembly, Promise, setTimeout, clearTimeout, TextDecoder, TextEncoder, performance,
			crypto: globalThis.crypto, navigator: { userAgent: 'node' } };
		ctx.window = ctx.self = ctx;
		ctx.fetch = () => Promise.resolve(new Response(wasm, { headers: { 'content-type': 'application/wasm' } }));
		ctx.AscViewer = { onLoadModule: () => resolve(ctx.AscViewer) };
		vm.createContext(ctx);
		vm.runInContext(glue, ctx, { filename: JS });
		setTimeout(() => reject(new Error('drawingfile module did not initialise')), 20000).unref();
	});
}

function render(viewer, colorSpace) {
	const file = new viewer.CDrawingFile();
	const err = file.loadFromData(new Uint8Array(makePdf(colorSpace)));
	if (err)
		throw new Error('open failed, error ' + err);
	const ptr = file.getPagePixmap(0, W, H, 0xFFFFFF);
	if (!ptr)
		throw new Error('getPagePixmap returned nothing');
	const px = Buffer.from(file.getUint8Array(ptr, W * H * 4));
	file.free(ptr);
	file.close();
	let black = 0, coloured = 0;
	for (let i = 0; i < W * H; i++) {
		const r = px[4 * i], g = px[4 * i + 1], b = px[4 * i + 2];
		if (r < 32 && g < 32 && b < 32) black++;
		if (Math.max(r, g, b) - Math.min(r, g, b) > 24) coloured++;
	}
	return { px, black, coloured };
}

let failed = 0;
const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); failed += !ok; };

(async () => {
	console.log(BASELINE ? 'BASELINE ' + BASE_REF : 'repo ' + SDKJS);
	for (const JS of ENGINES) {
		console.log('-- ' + JS + (JS.endsWith('_ie.js') ? ' (asm.js)' : ' + drawingfile.wasm'));
		const viewer = await loadEngine(JS);

		const ref = render(viewer, '/DeviceGray');
		let grey = 0, white = 0;
		for (let i = 0; i < W * H; i++) { const v = ref.px[4 * i + 1]; if (Math.abs(v - 140) < 8) grey++; else if (v > 247) white++; }
		check(ref.black === 0 && ref.coloured === 0 && grey > 15000 && white > 15000,
			'control, /ColorSpace /DeviceGray: ' + grey + ' grey + ' + white + ' white px, ' + ref.black + ' black, ' + ref.coloured + ' coloured');

		const got = render(viewer, null);
		let differ = 0;
		for (let i = 0; i < W * H * 4; i++) if (Math.abs(got.px[i] - ref.px[i]) > 8) differ++;
		check(got.black === 0, 'no /ColorSpace: ' + got.black + ' black px (of ' + W * H + ')');
		check(got.coloured === 0, 'no /ColorSpace: ' + got.coloured + ' coloured px');
		check(differ === 0, 'no /ColorSpace: ' + differ + ' channel values differ from the control');
	}

	console.log(failed ? 'FAILED (' + failed + ')' : 'PASSED');
	process.exit(failed ? 1 : 0);
})().catch(e => { console.log('FAIL ' + e.message); process.exit(1); });

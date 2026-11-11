/*
 * ONLYOFFICE 10.0 security backports, viewer/editor half: the core fixes in
 * c5d814c502..fc6cea8985 reach the editors only through the WASM builds of
 * core that sdkjs carries, so those were rebuilt. This checks the rebuilt
 * artefacts on the two kinds of input those fixes are about.
 *
 *   sdkjs/pdf/src/engine/drawingfile.js + .wasm, drawingfile_ie.js (asm.js)
 *     the PDF viewer (PdfFile, XpsFile, DjVu). Core b6897a441e (bug 81929,
 *     "heap buffer overflow when rendering image masks in PDF"):
 *     RendererOutputDev::drawImageMask read each mask row through
 *     ImageStream::getLine() and never checked it for NULL, which is what a
 *     mask stream shorter than Width x Height returns. Native x2t crashes on
 *     the NULL read; in WASM address 0 is ordinary memory, so the viewer
 *     painted every missing row from whatever lies at the bottom of linear
 *     memory (zeros there, i.e. "paint", so a truncated mask turned into a
 *     solid block of the fill colour). Fixed: missing rows are transparent.
 *
 *   sdkjs/common/libfont/engine/fonts.js + .wasm, fonts_ie.js (asm.js)
 *     the font engine, which also carries core's WMF/EMF -> SVG converter
 *     (CZLibEngineJS.getImageBuffer -> Raster_Encode(..., SVG), what
 *     AscCommon.g_oDocumentBlobUrls uses for metafile pictures in OOXML read
 *     in the browser, vendor/easysax.js).
 *     - a15cb4d641 (bug 84010, WMF out-of-bounds read): CWmfParserBase::
 *       ClipBuffer clamped the SIZE of a StretchDIB source rectangle to the
 *       bitmap but not its ORIGIN, so a 2x2 DIB with XSrc=10 copied heap
 *       memory beyond the bitmap into the picture. Here that memory still
 *       holds the SVG text of the previous conversion: the old engine puts
 *       the bytes "<s x" ... into the PNG it embeds. Fixed: the rectangle is
 *       clamped to the bitmap, nothing outside it is read.
 *     - 732d9bae15 (bug 82607, EMF PolyBezier): CEmfParser::
 *       Read_EMR_POLYBEZIER_BASE read cptl points in steps of 3 into a vector
 *       of cptl entries without checking that 3 more fit; cptl=3 writes 12
 *       bytes of file-controlled data past the vector, over the allocator's
 *       next chunk header. The old engine traps with "memory access out of
 *       bounds" after a few conversions of such a file (deterministic for a
 *       given binary). Fixed: the loop stops at the last full triple.
 *
 * Every engine is the REAL checked-in glue + binary, run in a vm context
 * standing in for the browser window (fetch() hands the glue the .wasm), and
 * driven through the same JS API the editor calls (CDrawingFile.loadFromData
 * / getPagePixmap; CZLibEngineJS.open / getImageBuffer on a zip). The inputs
 * are built here.
 *
 * Controls (must pass on old and new artefacts alike, so a broken harness
 * cannot pass for a fix): a complete image mask renders as painted /
 * transparent where its bits say; a complete WMF StretchDIB renders its DIB
 * colour; a well-formed 4-point PolyBezier comes out as an SVG cubic.
 *
 *   RD_REPO=<sdkjs checkout>  default ../../sdkjs relative to this file
 *   BASELINE=1                read the artefacts via `git show $BASE_REF:<path>`;
 *                             must FAIL there: BASE_REF 4789c97347^ (the
 *                             2026-11-04 builds) fails every .wasm check,
 *                             4789c97347 (the default) only the huge mask
 *
 * Added with the rebuild from core c9d4bbe6c4 ("v10-sec: PDF image buffer
 * sizes still wrapped in the wasm32 viewer"): b6897a441e sized the mask buffer
 * as 4 * (size_t)w * (size_t)h, but size_t is 32 bits in wasm32, so a
 * 32768 x 32769 /ImageMask asked for 4 GB + 128 KB, got 128 KB, and
 * drawImageMask wrote all its rows into it: the module died with "memory
 * access out of bounds" and every later call into it failed. Fixed: an image
 * whose buffer does not fit size_t is not drawn; the page renders, and the
 * module still renders the control mask afterwards.
 *
 * NOT claimed: the other fixes compiled in (PdfAnnot/PdfReader/
 * tilingPatternFill sizes, XPS font key, libxml2 valid.c, RedactOutputDev,
 * the DCT soft-mask size check of c9d4bbe6c4) are not exercised here - the XPS
 * key and libxml2 ones are covered at source level by v10-sec-core-converter,
 * the DCT one was shown under ASan with a native build. The asm.js variants
 * get the same checks, but only the .wasm variants are required to fail on
 * BASELINE (heap layouts differ; asm.js has no 4 GB trap to hit).
 * The desktop app's own loaders (ascdesktop:// fetch) are not exercised.
 * Needs Node >= 18 (Response, crypto.getRandomValues).
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const zlib = require('zlib');
const { execFileSync } = require('child_process');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', '..', 'sdkjs');
// Pinned to the parent of the commit that rebuilt the artefacts, never HEAD.
// The integrator re-pins it to the parent of the image-size rebuild.
const BASE_REF = process.env.BASE_REF || '3c0c7a391c^';
const BASELINE = !!process.env.BASELINE;

function read(rel) {
	if (BASELINE)
		return execFileSync('git', ['-C', SDKJS, 'show', BASE_REF + ':' + rel], { maxBuffer: 1 << 26 });
	return fs.readFileSync(path.join(SDKJS, rel));
}

let failed = 0;
const check = (ok, msg) => { console.log((ok ? 'ok   ' : 'FAIL ') + msg); failed += !ok; return ok; };

// ---------------------------------------------------------------- engines

function newContext(wasm) {
	const ctx = { console, WebAssembly, Promise, setTimeout, clearTimeout, TextDecoder, TextEncoder, performance,
		crypto: globalThis.crypto, navigator: { userAgent: 'node' } };
	ctx.window = ctx.self = ctx;
	ctx.fetch = () => Promise.resolve(new Response(wasm, { headers: { 'content-type': 'application/wasm' } }));
	return ctx;
}

function loadDrawingFile(js) {
	const glue = read(js).toString('utf8');
	const ctx = newContext(read('pdf/src/engine/drawingfile.wasm'));
	return new Promise((resolve, reject) => {
		ctx.AscViewer = { onLoadModule: () => resolve(ctx.AscViewer) };
		vm.createContext(ctx);
		vm.runInContext(glue, ctx, { filename: js });
		setTimeout(() => reject(new Error(js + ' did not initialise')), 20000).unref();
	});
}

function loadFonts(js) {
	const glue = read(js).toString('utf8');
	const ctx = newContext(read('common/libfont/engine/fonts.wasm'));
	return new Promise((resolve, reject) => {
		// the glue calls onLoadModule once when it is evaluated and again when
		// the runtime is up; the editor's loader waits for both
		let calls = 0;
		ctx.AscFonts = { onLoadModule: () => { if (++calls === 2) resolve(ctx); } };
		vm.createContext(ctx);
		vm.runInContext(glue, ctx, { filename: js });
		setTimeout(() => reject(new Error(js + ' did not initialise')), 20000).unref();
	});
}

// ---------------------------------------------------------------- PDF

function makePdf(objs) {
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

// a 100x100 page filled by one red-painted /ImageMask of 100x100 (13 bytes a
// row, 1300 in all); `mask` is the stream as stored, possibly short
const N = 100;
function maskPdf(mask, w, h) {
	const content = '1 0 0 rg q ' + N + ' 0 0 ' + N + ' 0 0 cm /Im1 Do Q';
	return makePdf([
		'<< /Type /Catalog /Pages 2 0 R >>',
		'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
		'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ' + N + ' ' + N + '] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>',
		['<< /Type /XObject /Subtype /Image /Width ' + (w || N) + ' /Height ' + (h || N) + ' /ImageMask true /Length ' + mask.length + ' >>', mask],
		['<< /Length ' + content.length + ' >>', Buffer.from(content)],
	]);
}

function renderMask(viewer, mask, w, h) {
	const file = new viewer.CDrawingFile();
	const err = file.loadFromData(new Uint8Array(maskPdf(mask, w, h)));
	if (err)
		throw new Error('open failed, error ' + err);
	const ptr = file.getPagePixmap(0, N, N, 0xFFFFFF);
	if (!ptr)
		throw new Error('getPagePixmap returned nothing');
	const px = Buffer.from(file.getUint8Array(ptr, N * N * 4));
	file.free(ptr);
	file.close();
	let red = 0, white = 0;
	for (let i = 0; i < N * N; i++) {
		const r = px[4 * i], g = px[4 * i + 1], b = px[4 * i + 2];
		if (r > 200 && g < 60 && b < 60) red++;
		else if (r > 240 && g > 240 && b > 240) white++;
	}
	return { red, white };
}

const ROW = (N + 7) >> 3;

async function pdfChecks(js) {
	console.log('-- ' + js + (js.endsWith('_ie.js') ? ' (asm.js)' : ' + drawingfile.wasm'));
	const viewer = await loadDrawingFile(js);
	let r = renderMask(viewer, Buffer.alloc(ROW * N, 0x00));
	check(r.red === N * N, 'control, complete mask of 0 bits: ' + r.red + ' of ' + N * N + ' px painted');
	r = renderMask(viewer, Buffer.alloc(ROW * N, 0xFF));
	check(r.red === 0 && r.white === N * N, 'control, complete mask of 1 bits: ' + r.white + ' px left white, ' + r.red + ' painted');
	// 4 rows short: the rows with no data must not be painted
	r = renderMask(viewer, Buffer.alloc(ROW * (N - 4), 0xFF));
	check(r.red === 0, 'mask 4 rows short of its /Height: ' + r.red + ' px painted from memory (want 0)');
	r = renderMask(viewer, Buffer.alloc(0));
	check(r.red === 0, 'empty mask stream: ' + r.red + ' px painted from memory (want 0)');
	// 4 * 32768 * 32769 wraps a 32-bit size_t to 128 KB; the stream is empty, so
	// every row is filled as "missing" - 4 GB of writes into that buffer
	let error = null;
	try { r = renderMask(viewer, Buffer.alloc(0), 32768, 32769); }
	catch (e) { error = (e && e.message) || String(e); }
	check(error === null && r.red === 0, '32768x32769 /ImageMask: ' + (error ? 'died: ' + error : r.red + ' px painted'));
	if (!error) {
		r = renderMask(viewer, Buffer.alloc(ROW * N, 0x00));
		check(r.red === N * N, 'module still renders the control mask afterwards: ' + r.red + ' px painted');
	}
}

// ---------------------------------------------------------------- WMF / EMF

function wmfRecord(fn, params) { // size in 16-bit words
	const b = Buffer.alloc(6 + params.length);
	b.writeUInt32LE((6 + params.length) / 2, 0);
	b.writeUInt16LE(fn, 4);
	params.copy(b, 6);
	return b;
}
function s16(...v) { const b = Buffer.alloc(2 * v.length); v.forEach((x, i) => b.writeInt16LE(x, 2 * i)); return b; }
function i32(...v) { const b = Buffer.alloc(4 * v.length); v.forEach((x, i) => b.writeInt32LE(x, 4 * i)); return b; }

// window 100x100, one META_STRETCHDIB of a dibW x dibH 32-bit DIB of `argb`
// from source origin (xSrc, 0), size dibW x dibH, onto (0,0,100,100)
function wmfStretchDib(xSrc, dibW, dibH, argb) {
	const dib = Buffer.alloc(40 + 4 * dibW * dibH);
	dib.writeUInt32LE(40, 0); dib.writeInt32LE(dibW, 4); dib.writeInt32LE(dibH, 8);
	dib.writeUInt16LE(1, 12); dib.writeUInt16LE(32, 14); dib.writeUInt32LE(4 * dibW * dibH, 20);
	for (let i = 0; i < dibW * dibH; i++) dib.writeUInt32LE(argb, 40 + 4 * i);
	const rop = Buffer.alloc(4); rop.writeUInt32LE(0x00CC0020, 0); // SRCCOPY
	// RasterOperation, ColorUsage, SrcHeight, SrcWidth, YSrc, XSrc, DestHeight, DestWidth, YDest, XDest
	const params = Buffer.concat([rop, s16(0, dibH, dibW, 0, xSrc, 100, 100, 0, 0), dib]);
	const recs = [wmfRecord(0x020B, s16(0, 0)), wmfRecord(0x020C, s16(100, 100)), wmfRecord(0x0F43, params), wmfRecord(0x0000, Buffer.alloc(0))];
	const body = Buffer.concat(recs);
	const h = Buffer.alloc(18);
	h.writeUInt16LE(1, 0); h.writeUInt16LE(9, 2); h.writeUInt16LE(0x0300, 4);
	h.writeUInt32LE((18 + body.length) / 2, 6);
	h.writeUInt32LE(Math.max(...recs.map(r => r.length / 2)), 12);
	return Buffer.concat([h, body]);
}

function emfRecord(type, data) {
	const b = Buffer.alloc(8 + data.length);
	b.writeUInt32LE(type, 0); b.writeUInt32LE(8 + data.length, 4); data.copy(b, 8);
	return b;
}
// EMR_POLYBEZIER (32-bit points) declaring `cptl` points, followed by `pts`
function emfPolyBezier(cptl, pts) {
	const p = Buffer.alloc(8 * pts.length);
	pts.forEach(([x, y], i) => { p.writeInt32LE(x, 8 * i); p.writeInt32LE(y, 8 * i + 4); });
	const recs = [emfRecord(2, Buffer.concat([i32(0, 0, 100, 100, cptl), p])), emfRecord(14, i32(0, 0, 20))];
	const body = Buffer.concat(recs);
	const hd = Buffer.alloc(80);
	i32(0, 0, 100, 100).copy(hd, 0);        // rclBounds
	i32(0, 0, 2646, 2646).copy(hd, 16);     // rclFrame, .01 mm
	hd.writeUInt32LE(0x464D4520, 32);       // " EMF"
	hd.writeUInt32LE(0x00010000, 36);
	hd.writeUInt32LE(88 + body.length, 40); // nBytes
	hd.writeUInt32LE(1 + recs.length, 44);  // nRecords
	hd.writeUInt16LE(1, 48);
	i32(1024, 768, 270, 203).copy(hd, 64);  // szlDevice, szlMillimeters
	return Buffer.concat([emfRecord(1, hd), body]);
}

// minimal PNG reader for what CBgraFrame writes (8-bit RGB/RGBA, no interlace)
function readPng(buf) {
	let pos = 8, w = 0, h = 0, ct = 0;
	const idat = [];
	while (pos < buf.length) {
		const len = buf.readUInt32BE(pos), type = buf.toString('latin1', pos + 4, pos + 8), d = buf.subarray(pos + 8, pos + 8 + len);
		if (type === 'IHDR') { w = d.readUInt32BE(0); h = d.readUInt32BE(4); ct = d[9]; }
		else if (type === 'IDAT') idat.push(d);
		pos += 12 + len;
	}
	const bpp = ct === 6 ? 4 : 3, stride = w * bpp, out = Buffer.alloc(w * h * 4, 255);
	const raw = w && h ? zlib.inflateSync(Buffer.concat(idat)) : Buffer.alloc(0);
	let prev = Buffer.alloc(stride);
	for (let y = 0; y < h; y++) {
		const f = raw[y * (stride + 1)], line = Buffer.from(raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)));
		for (let i = 0; i < stride; i++) {
			const a = i >= bpp ? line[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
			const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
			line[i] = (line[i] + [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][f]) & 255;
		}
		for (let x = 0; x < w; x++) for (let k = 0; k < bpp; k++) out[4 * (y * w + x) + k] = line[x * bpp + k];
		prev = line;
	}
	return { w, h, px: out };
}

// every PNG embedded in the SVG, as {w, h, px (RGBA)}
function svgImages(svg) {
	return [...svg.matchAll(/base64,([A-Za-z0-9+/=\s]+)"/g)].map(m => readPng(Buffer.from(m[1].replace(/\s/g, ''), 'base64')));
}

async function metafileChecks(js) {
	console.log('-- ' + js + (js.endsWith('_ie.js') ? ' (asm.js)' : ' + fonts.wasm'));
	const ctx = await loadFonts(js);
	// the editor's path: a zip read with CZLibEngineJS, then getImageBuffer(),
	// which turns a WMF/EMF into SVG (type 24) with Raster_Encode
	const convert = vm.runInContext(`(function (name, bytes) {
		AscCommon.CZLibEngineJS.prototype.isModuleInit = true; // as common/libfont/engine.js does on load
		var w = new AscCommon.CZLibEngineJS();
		w.create();
		w.addFile(name, new Uint8Array(bytes));
		var zip = new Uint8Array(w.save());
		w.close();
		var z = new AscCommon.CZLibEngineJS();
		if (!z.open(zip))
			throw new Error("zip open failed");
		var r = z.getImageBuffer(name);
		z.close();
		return r;
	})`, ctx);
	const toSvg = (name, buf) => {
		const r = convert('word/media/' + name, Array.from(buf));
		if (!r || r.type !== 24 || !r.dataBlob)
			throw new Error(name + ': no SVG (type ' + (r && r.type) + ')');
		return Buffer.from(r.dataBlob).toString('utf8');
	};

	const GREEN = 0xFF00FF00; // ARGB in the DIB, RGBA 00 ff 00 ff in the PNG
	const isGreen = (px, i) => px[4 * i] === 0 && px[4 * i + 1] === 255 && px[4 * i + 2] === 0;

	// control: the whole 2x2 DIB
	let imgs = svgImages(toSvg('ctrl.wmf', wmfStretchDib(0, 2, 2, GREEN)));
	check(imgs.length === 1 && imgs[0].w === 2 && imgs[0].h === 2 && [0, 1, 2, 3].every(i => isGreen(imgs[0].px, i)),
		'control, WMF StretchDIB of a green 2x2 DIB: ' + imgs.map(m => m.w + 'x' + m.h).join(',') + ' image, green');

	// source origin outside the DIB; convert a large picture first so the heap
	// past the 16-byte bitmap holds stale data, as it does in a real session
	toSvg('big.wmf', wmfStretchDib(0, 64, 64, 0xFF3366CC));
	imgs = svgImages(toSvg('oob.wmf', wmfStretchDib(10, 2, 2, GREEN)));
	const foreign = [];
	for (const m of imgs)
		for (let i = 0; i < m.w * m.h; i++)
			if (!isGreen(m.px, i))
				foreign.push(m.px.subarray(4 * i, 4 * i + 4));
	const shown = Buffer.concat(foreign).toString('latin1').replace(/[^\x20-\x7e]/g, '.');
	check(foreign.length === 0, 'WMF StretchDIB, XSrc 10 on a 2x2 DIB: ' + foreign.length +
		' px not from the DIB' + (foreign.length ? ' (bytes "' + shown.slice(0, 24) + '")' : '') + ' in ' + imgs.length + ' image(s)');

	// control: a well-formed curve
	const curve = toSvg('ok.emf', emfPolyBezier(4, [[10, 10], [90, 90], [10, 90], [90, 10]]));
	check(/<path d="M 10 10 C 90 90 10 90 90 10 "/.test(curve), 'control, EMF PolyBezier of 4 points -> SVG cubic');

	// cptl 3: one start point and an incomplete triple
	const bad = emfPolyBezier(3, [[10, 10], [0x7fffffff, 0x7fffffff], [0x7fffffff, 0x7fffffff], [0x7fffffff, 0x7fffffff]]);
	let error = null, done = 0;
	for (; done < 20; done++) {
		try { toSvg('pb.emf', bad); }
		catch (e) { error = (e && e.message) || String(e); break; }
	}
	check(error === null, 'EMF PolyBezier with cptl 3, converted 20 times: ' + (error ? 'died on run ' + (done + 1) + ': ' + error : 'no error'));
	if (!error) {
		const after = toSvg('ok2.emf', emfPolyBezier(4, [[10, 10], [90, 90], [10, 90], [90, 10]]));
		check(/C 90 90 10 90 90 10/.test(after), 'engine still converts a good EMF afterwards');
	}
}

(async () => {
	console.log(BASELINE ? 'BASELINE ' + BASE_REF : 'repo ' + SDKJS);
	for (const js of ['pdf/src/engine/drawingfile.js', 'pdf/src/engine/drawingfile_ie.js']) {
		try { await pdfChecks(js); } catch (e) { check(false, js + ': ' + e.message); }
	}
	for (const js of ['common/libfont/engine/fonts.js', 'common/libfont/engine/fonts_ie.js']) {
		try { await metafileChecks(js); } catch (e) { check(false, js + ': ' + e.message); }
	}
	console.log(failed ? 'FAILED (' + failed + ')' : 'PASSED');
	process.exit(failed ? 1 : 0);
})();

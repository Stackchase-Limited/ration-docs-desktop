/*
 * #676 - "Copy paste image from GNOME nautilus is broken".
 *
 * Copying an image FILE in a Linux file manager puts no bitmap data on the
 * clipboard - it puts URIs naming the file on disk. Nautilus <= 40 also leaked
 * its marker into text/plain, so the reporter saw this pasted as literal text:
 *
 *     x-special/nautilus-clipboard
 *     copy
 *     file:///home/X/Pictures/X.png
 *
 * In sdkjs/common/clipboard_base.js the paste path narrows the incoming items
 * to `kind === 'file' && type.indexOf('image/') !== -1` (checkImages). A URI
 * list matches nothing, so the text/plain branch pastes the marker verbatim.
 *
 * This drives the REAL _private_onpaste, extracted out of the real source file
 * by brace matching, against a synthetic DataTransfer carrying exactly the
 * flavours a file manager emits. Nothing is retyped: every function under test
 * is sliced out of clipboard_base.js at run time.
 *
 * This machine is macOS, so the GNOME end-to-end leg is NOT covered here; what
 * is covered is the clipboard payload shape and the decision the editor makes
 * about it.
 *
 *   node fork-fix-tests/issue-676-nautilus-image-paste-test.js
 *
 * BASELINE=1 runs the same assertions against HEAD, where they must fail. The
 * default run does that for you and fails if the baseline unexpectedly passes.
 */
'use strict';
const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'common/clipboard_base.js';
// Pinned to the commit this fix landed on top of. It must NOT default to HEAD:
// once the fix is committed, HEAD carries it, the baseline stops differing and
// the test quietly becomes toothless while still reporting success.
const BASE_REF = process.env.BASE_REF || 'b98bcb7c0106504261863c483e7f1fd8172af82b';
const BASELINE = !!process.env.BASELINE;

const source = BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

/* ------------------------------------------------------------------ extract */

/* Slice `name : function(...) { ... }` out of the prototype object literal by
 * brace matching. Returns null when the method does not exist (HEAD). */
function extractMethod(src, name) {
	const at = src.indexOf('\n\t\t' + name + ' : function');
	if (at === -1) return null;
	const fnAt = src.indexOf('function', at);
	const open = src.indexOf('{', fnAt);
	let depth = 0;
	for (let i = open; i < src.length; i++) {
		if (src[i] === '{') depth++;
		else if (src[i] === '}' && --depth === 0) return src.slice(fnAt, i + 1);
	}
	throw new Error('unbalanced braces in ' + name);
}

const onpasteSrc = extractMethod(source, '_private_onpaste');
assert.ok(onpasteSrc, '_private_onpaste not found in ' + REL);
/* prove we sliced the right thing and the whole thing */
assert.ok(onpasteSrc.includes('let checkImages = function'), 'extracted the wrong block');
assert.ok(onpasteSrc.includes('reader.readAsDataURL(blob)'), 'extraction truncated');

const pathsSrc = extractMethod(source, 'getFileManagerImagePaths');
const checkSrc = extractMethod(source, 'checkFileManagerImagePaste');
if (!BASELINE) {
	assert.ok(pathsSrc, 'getFileManagerImagePaths missing - is the fix applied?');
	assert.ok(checkSrc, 'checkFileManagerImagePaste missing - is the fix applied?');
	assert.ok(pathsSrc.includes('text/uri-list'), 'extracted the wrong parser');
}

/* ------------------------------------------------------------------- scenarios */

const IMAGE_ON_DISK = '/home/X/Pictures/X.png';
const SPACED_IMAGE = '/home/X/Pictures/My Photo.png';

/* Files that really exist on disk AND really are images, as the native
 * CImageFileFormatChecker::isImageFile() magic-byte sniff would report. */
const REAL_IMAGES = new Set([IMAGE_ON_DISK, SPACED_IMAGE, '/home/X/a.png', '/home/X/b.png']);

const NAUTILUS_40_TEXT = 'x-special/nautilus-clipboard\ncopy\nfile://' + IMAGE_ON_DISK + '\n';

const scenarios = [
	{
		name: 'A. Nautilus<=40 marker in text/plain (the #676 payload)',
		flavours: { 'text/plain': NAUTILUS_40_TEXT },
		expect: { images: ['docurl/media/image1.png'], text: null },
		regression: false,
	},
	{
		name: 'B. modern XDG text/uri-list, percent-encoded path',
		flavours: {
			'text/uri-list': 'file:///home/X/Pictures/My%20Photo.png\r\n',
			'text/plain': SPACED_IMAGE,
		},
		expect: { images: ['docurl/media/image1.png'], text: null },
		regression: false,
	},
	{
		name: 'C. GNOME x-special/gnome-copied-files ("copy\\n<uri>")',
		flavours: { 'x-special/gnome-copied-files': 'copy\nfile:///home/X/a.png' },
		expect: { images: ['docurl/media/image1.png'], text: null },
		regression: false,
	},
	{
		name: 'D. two images selected in the file manager',
		flavours: { 'text/uri-list': 'file:///home/X/a.png\r\nfile:///home/X/b.png\r\n' },
		expect: { images: ['docurl/media/image1.png', 'docurl/media/image2.png'], text: null },
		regression: false,
	},

	{
		/* GetLocalImageUrl() strips this form explicitly - see its comment
		 * "MS Word copy image with url file://localhost/... on mac". */
		name: 'M. file://localhost/ is local and is accepted',
		flavours: { 'text/uri-list': 'file://localhost/home/X/a.png\r\n' },
		expect: { images: ['docurl/media/image1.png'], text: null },
		regression: false,
	},

	/* --- security: these must never reach the native layer --- */
	{
		name: 'E. SECURITY http:// URI on the clipboard is refused',
		flavours: { 'text/uri-list': 'http://evil.example/track.png\r\n', 'text/plain': 'http://evil.example/track.png' },
		expect: { images: null, text: 'http://evil.example/track.png' },
		noNativeCalls: true,
		regression: true,
	},
	{
		name: 'F. SECURITY https:// smuggled behind the nautilus marker is refused',
		flavours: { 'text/plain': 'x-special/nautilus-clipboard\ncopy\nhttps://evil.example/x.png\n' },
		expect: { images: null, text: 'x-special/nautilus-clipboard\ncopy\nhttps://evil.example/x.png\n' },
		noNativeCalls: true,
		regression: true,
	},
	{
		name: 'G. SECURITY remote host in a file:// URI is refused',
		flavours: { 'text/uri-list': 'file://evil.example/share/x.png', 'text/plain': 'x' },
		expect: { images: null, text: 'x' },
		noNativeCalls: true,
		regression: true,
	},
	{
		name: 'H. SECURITY a mixed image+remote payload is refused whole',
		flavours: { 'text/uri-list': 'file:///home/X/a.png\r\nhttp://evil.example/x\r\n', 'text/plain': 'x' },
		expect: { images: null, text: 'x' },
		noNativeCalls: true,
		regression: true,
	},
	{
		name: 'I. SECURITY a local file that is not an image is refused',
		flavours: { 'text/uri-list': 'file:///etc/passwd\r\n', 'text/plain': '/etc/passwd' },
		expect: { images: null, text: '/etc/passwd' },
		noImageUrlCalls: true,
		regression: true,
	},

	/* --- no-regression: existing paste behaviour must be untouched --- */
	{
		name: 'J. plain text paste is unchanged',
		flavours: { 'text/plain': 'hello world' },
		expect: { images: null, text: 'hello world' },
		noNativeCalls: true,
		regression: true,
	},
	{
		name: 'K. a bare file:// URI typed as text stays text',
		flavours: { 'text/plain': 'file://' + IMAGE_ON_DISK },
		expect: { images: null, text: 'file://' + IMAGE_ON_DISK },
		noNativeCalls: true,
		regression: true,
	},
	{
		name: 'L. real HTML still wins over a uri-list',
		flavours: {
			'text/html': '<html><body><b>rich</b></body></html>',
			'text/uri-list': 'file:///home/X/a.png\r\n',
			'text/plain': 'rich',
		},
		expect: { images: null, text: null, html: '<html><body><b>rich</b></body></html>' },
		regression: true,
	},
];

/* ------------------------------------------------------------------- harness */

function run(scenario) {
	const log = {
		pasteData: [],        // [format, data]
		addImageUrl: [],      // [urls]
		iframeHtml: [],
		isImageFile: [],      // paths handed to the native magic-byte sniff
		localFileGetImageUrl: [], // paths/URLs handed to the native resolver+downloader
		pasteEnd: 0,
	};

	let imageCounter = 0;

	/* Chromium's DataTransfer returns "" for a flavour that is not present and
	 * never throws; mirror that exactly. */
	const clipboardData = {
		items: [],
		files: [],
		getData(type) {
			return Object.prototype.hasOwnProperty.call(scenario.flavours, type)
				? scenario.flavours[type]
				: '';
		},
	};

	const AscCommon = {
		c_oAscClipboardDataFormat: { Text: 1, Html: 2, Internal: 4, HtmlElement: 8, Rtf: 16, Image: 32 },
		g_specialPasteHelper: { specialPasteData: {} },
		g_oDocumentUrls: {
			getImageUrl(url) { return 'docurl/' + url; },
		},
	};

	const AscDesktopEditor = {
		/* native CImageFileFormatChecker::isImageFile - sniffs magic bytes,
		 * returns false for anything that is not a decodable image. */
		IsImageFile(p) {
			log.isImageFile.push(p);
			return REAL_IMAGES.has(p);
		},
		/* native CCefView::GetLocalImageUrl. For a path that is not an existing
		 * local file this really does fall through to NSFileDownloader and
		 * DownloadSync(), so every call here is a potential network fetch. */
		LocalFileGetImageUrl(p) {
			log.localFileGetImageUrl.push(p);
			if (!REAL_IMAGES.has(p)) return 'error';
			return 'media/image' + (++imageCounter) + '.png';
		},
	};

	const windowStub = { AscDesktopEditor: AscDesktopEditor, clipboardData: undefined };

	const cb = {};
	const make = (src) => new Function(
		'g_clipboardBase', 'AscCommon', 'window',
		'"use strict"; return (' + src + ');'
	)(cb, AscCommon, windowStub);

	cb.Api = {
		asc_IsFocus: () => true,
		isLongAction: () => false,
		incrementCounterLongAction() {},
		decrementCounterLongAction() {},
		asc_PasteData(format, data) { log.pasteData.push([format, data]); },
		_addImageUrl(urls) { log.addImageUrl.push(urls); },
	};
	cb.IsNeedDivOnPaste = false;
	cb.PasteFlag = false;
	cb.pastedFrom = null;
	cb.ClosureParams = {
		_e: null,
		getData(type) {
			const c = (this._e && this._e.clipboardData) ? this._e.clipboardData : windowStub.clipboardData;
			if (!c || !c.getData) return null;
			try { return c.getData(type); } catch (e) { return null; }
		},
	};
	cb._console_log = function () {};
	cb.CommonIframe_PasteStart = function (html) { log.iframeHtml.push(html); };
	cb.Paste_End = function () { log.pasteEnd++; };

	if (pathsSrc) cb.getFileManagerImagePaths = make(pathsSrc);
	if (checkSrc) cb.checkFileManagerImagePaste = make(checkSrc);
	cb._private_onpaste = make(onpasteSrc);

	cb._private_onpaste({ clipboardData, preventDefault() {} });
	return log;
}

/* ---------------------------------------------------------------- assertions */

const failures = [];

for (const s of scenarios) {
	try {
		const log = run(s);
		if (process.env.DUMP) console.log('  --- ' + s.name + '\n      ' + JSON.stringify(log));

		if (s.expect.images) {
			assert.deepStrictEqual(log.addImageUrl, [s.expect.images],
				'expected the image to be inserted');
			assert.deepStrictEqual(log.pasteData, [],
				'the raw clipboard payload must not also be pasted as text');
		} else {
			assert.deepStrictEqual(log.addImageUrl, [], 'no image may be inserted');
		}

		if (s.expect.text !== null && s.expect.text !== undefined) {
			assert.deepStrictEqual(log.pasteData, [[1 /* Text */, s.expect.text]],
				'existing text paste behaviour changed');
		}

		if (s.expect.html) {
			assert.deepStrictEqual(log.iframeHtml, [s.expect.html],
				'HTML paste must still win');
		}

		if (s.noNativeCalls) {
			assert.deepStrictEqual(log.isImageFile, [],
				'nothing should have been handed to the native image sniff');
			assert.deepStrictEqual(log.localFileGetImageUrl, [],
				'a URL reached GetLocalImageUrl, which can DownloadSync() it');
		}
		if (s.noImageUrlCalls) {
			assert.deepStrictEqual(log.localFileGetImageUrl, [],
				'a rejected path still reached GetLocalImageUrl');
		}

		console.log('  ok   ' + s.name);
	} catch (err) {
		failures.push(s.name + '\n         ' + err.message.split('\n').join('\n         '));
		console.log('  FAIL ' + s.name);
	}
}

const fixCases = scenarios.filter(s => !s.regression).map(s => s.name);
const brokenFixCases = failures.filter(f => fixCases.some(n => f.startsWith(n)));

console.log('');
if (failures.length) {
	console.log(failures.length + ' of ' + scenarios.length + ' failed:\n');
	for (const f of failures) console.log('  - ' + f + '\n');
}

if (BASELINE) {
	/* At HEAD the fix cases MUST fail, otherwise this test proves nothing. */
	if (brokenFixCases.length === 0) {
		console.error('BASELINE: the fix cases passed against ' + BASE_REF + ' - the test is toothless.');
		process.exit(1);
	}
	console.log('BASELINE: ' + brokenFixCases.length + ' fix case(s) fail against ' + BASE_REF + ', as required.');
	/* Regressions cases are expected to pass at HEAD too. */
	if (failures.length !== brokenFixCases.length) {
		console.error('BASELINE: a no-regression case failed at ' + BASE_REF + ' - the stubs are wrong.');
		process.exit(1);
	}
	process.exit(0);
}

if (failures.length) process.exit(1);

/* Default run: prove the test has teeth by re-running it against HEAD. */
console.log('all ' + scenarios.length + ' cases pass; checking the test fails against ' + BASE_REF + ' ...');
const baseline = spawnSync(process.execPath, [__filename], {
	env: Object.assign({}, process.env, { BASELINE: '1' }),
	encoding: 'utf8',
});
process.stdout.write(baseline.stdout.split('\n').map(l => l ? '  | ' + l : l).join('\n'));
if (baseline.status !== 0) {
	process.stderr.write(baseline.stderr);
	console.error('the baseline self-check did not behave as expected');
	process.exit(1);
}
console.log('OK - fix verified, and the test fails without it.');

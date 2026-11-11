/*
 * #1233 - pasting web content with images froze the desktop editor until every
 * image had downloaded (22.7 s for three images served with a 3 s delay).
 *
 * The desktop AscCommon.sendImgUrls (sdkjs common/Local/common.js) called
 * AscDesktopEditor.LocalFileGetImageUrl per image; for an http(s) url that call
 * downloads synchronously in the renderer (DownloadSync sleep-polls on the
 * editor's main thread). The fix sends http(s) images through the asynchronous
 * AscDesktopEditor.DownloadFiles in one batch, with a timeout, and keeps local
 * files and data: urls on the direct (fast) path.
 *
 * This extracts the REAL AscCommon.sendImgUrls by brace matching and runs it with
 * a stub AscDesktopEditor whose LocalFileGetImageUrl records being handed a
 * remote url (that call is the freeze) and whose DownloadFiles answers later.
 *
 * Claimed: no http(s) url reaches LocalFileGetImageUrl; sendImgUrls returns
 * before the downloads answer and the callback then gets the downloaded files
 * imported, in the original order, beside the local/data images; the LoadImage
 * action brackets the wait; downloaded temp files are removed; with no answer
 * the callback comes once, after the timeout, with "error" for the remote
 * images, and files arriving later are removed; a batch without remote images
 * still answers synchronously.
 * NOT claimed: the native download itself. Measured in an APFS clone of the
 * test app (word, 3 images from a server delaying 3 s): baseline paste call
 * blocked 22.7 s, main-thread gap 22.9 s; fixed: call 4 ms, images in 3.6 s,
 * largest main-thread gap 379 ms.
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the source at
 * BASE_REF with git show, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '3b3a0125ea^';
const REL = 'common/Local/common.js';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
const marker = 'AscCommon.sendImgUrls = function(api, images, callback)';
const at = source.indexOf(marker);
assert.notStrictEqual(at, -1, marker + ' not found');
const code = block(source, at) + ';';

/* --- stubs --- */
function makeEnv(opts) {
	const log = { remoteSync: [], removed: [], actions: [], downloads: [] };
	let nextMedia = 1;
	const desktop = {
		LocalFileGetImageUrl(u) {
			if (/^(https?|ftp):\/\//i.test(u) || /^www\./i.test(u)) log.remoteSync.push(u);
			return 'image' + (nextMedia++) + '.png';
		},
		RemoveFile(f) { log.removed.push(f); },
	};
	if (!opts.noDownloadFiles) {
		desktop.DownloadFiles = function (src, dst, cb) {
			log.downloads.push({ src: src.slice(), cb });
		};
	}
	const window = { AscDesktopEditor: desktop };
	const AscCommon = {
		g_oDocumentUrls: { getUrl: (p) => 'file:///doc/media/' + p },
	};
	const Asc = { c_oAscAsyncActionType: { BlockInteraction: 1 }, c_oAscAsyncAction: { LoadImage: 5 } };
	const api = {
		isOpenedFrameEditor: false,
		sync_StartAction: (t, a) => log.actions.push(['start', t, a]),
		sync_EndAction: (t, a) => log.actions.push(['end', t, a]),
	};
	new Function('window', 'AscCommon', 'Asc', code)(new Proxy(window, {
		get: (o, k) => (k in o ? o[k] : undefined),
	}), AscCommon, Asc);
	if (AscCommon.sendImgUrlsDownloadTimeout !== undefined) AscCommon.sendImgUrlsDownloadTimeout = opts.timeout || 50;
	return { log, AscCommon, api };
}

let failed = 0;
async function check(name, fn) {
	try { await fn(); console.log('ok   ' + name); } catch (e) { failed++; console.log('FAIL ' + name + ': ' + e.message); }
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const IMAGES = ['file:///Users/me/pic.png', 'http://example.com/a.png', 'data:image/png;base64,AAAA', 'https://example.com/b.jpg'];

(async () => {
	await check('remote images download asynchronously, nothing remote reaches LocalFileGetImageUrl', async () => {
		const env = makeEnv({});
		let result = null, calls = 0;
		env.AscCommon.sendImgUrls(env.api, IMAGES.slice(), (d) => { calls++; result = d; });
		assert.deepStrictEqual(env.log.remoteSync, [], 'synchronous download of ' + env.log.remoteSync.join(', '));
		assert.strictEqual(calls, 0, 'callback ran before the downloads answered');
		assert.strictEqual(env.log.downloads.length, 1, 'one DownloadFiles batch');
		assert.deepStrictEqual(env.log.downloads[0].src, ['http://example.com/a.png', 'https://example.com/b.jpg']);
		env.log.downloads[0].cb({ 'http://example.com/a.png': '/tmp/doc/IMG1', 'https://example.com/b.jpg': '/tmp/doc/IMG2' });
		assert.strictEqual(calls, 1);
		assert.strictEqual(result.length, 4);
		assert.deepStrictEqual(result.map((r) => r.path), ['image1.png', 'image3.png', 'image2.png', 'image4.png']);
		assert.strictEqual(result[1].url, 'file:///doc/media/image3.png');
		assert.deepStrictEqual(env.log.removed.sort(), ['/tmp/doc/IMG1', '/tmp/doc/IMG2']);
		assert.deepStrictEqual(env.log.actions, [['start', 1, 5], ['end', 1, 5]]);
	});

	await check('no answer: one callback after the timeout with "error", late files removed', async () => {
		const env = makeEnv({ timeout: 30 });
		let result = null, calls = 0;
		env.AscCommon.sendImgUrls(env.api, ['http://slow.example/a.png'], (d) => { calls++; result = d; });
		assert.deepStrictEqual(env.log.remoteSync, [], 'synchronous download');
		await wait(80);
		assert.strictEqual(calls, 1, 'callback after timeout');
		assert.strictEqual(result[0].path, 'error');
		assert.deepStrictEqual(env.log.actions, [['start', 1, 5], ['end', 1, 5]]);
		env.log.downloads[0].cb({ 'http://slow.example/a.png': '/tmp/doc/IMG9' });
		assert.strictEqual(calls, 1, 'callback ran twice');
		assert.deepStrictEqual(env.log.removed, ['/tmp/doc/IMG9']);
	});

	await check('a failed download ("" path) gives "error" for that image only', async () => {
		const env = makeEnv({});
		let result = null;
		env.AscCommon.sendImgUrls(env.api, ['http://x/a.png', 'http://x/b.png'], (d) => { result = d; });
		env.log.downloads[0].cb({ 'http://x/a.png': '/tmp/doc/IMG1' });
		assert.deepStrictEqual(result.map((r) => r.path), ['image1.png', 'error']);
	});

	await check('control: local and data: images still answer synchronously', async () => {
		const env = makeEnv({});
		let result = null;
		env.AscCommon.sendImgUrls(env.api, ['file:///a.png', 'data:image/png;base64,AA'], (d) => { result = d; });
		assert.ok(result, 'callback not synchronous');
		assert.deepStrictEqual(result.map((r) => r.path), ['image1.png', 'image2.png']);
		assert.strictEqual(env.log.downloads.length, 0);
		assert.deepStrictEqual(env.log.actions, []);
	});

	console.log(failed ? `FAIL: ${failed} check(s)` : 'PASS: desktop paste downloads images without blocking the editor');
	process.exit(failed ? 1 : 0);
})();

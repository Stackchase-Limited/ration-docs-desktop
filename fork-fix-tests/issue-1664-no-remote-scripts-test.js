/*
 * #1664 (security follow-up) - local pages with the desktop bridge must not run
 * code from the network.
 *
 * Bug: the bundled plugins and the plugin store are file:// pages under the
 * app; they get window.AscDesktopEditor (read/write/convert local files, start
 * processes) and, through --allow-file-access-from-files, can read any local
 * file. Several of them loaded scripts and stylesheets from other hosts, so
 * whoever controlled (or could tamper with) those hosts ran code with all of
 * that. Measured in the macOS test app with CDP (Debugger.scriptParsed and
 * Network.requestWillBeSent on every target; the executing frame's window had
 * typeof AscDesktopEditor == "object"):
 *   store/index.html, store/plugin-card.html  onlyoffice.github.io/sdkjs-plugins/v1/
 *                                             plugins.js, plugins-ui.js, plugins.css
 *   youtube/index.html                        www.youtube.com/iframe_api (+ www-widgetapi.js)
 *   ocr/index.html                            cdn.jsdelivr.net tesseract.js 6.0.1, and its
 *                                             worker and engine (tesseract.js-core) by default
 *   translator/index_widget.html              code.jquery.com jquery-3.7.1.min.js,
 *                                             translate.google.com element.js (+ Google's)
 *   thesaurus, highlightcode index.html       fonts.googleapis.com Material Icons (unused)
 *
 * Fix (onlyoffice.github.io): the store uses the plugin SDK the editors ship
 * (editors/sdkjs-plugins/v1, i.e. ../../v1 from {AA2EA9B6-...}/store/); the
 * YouTube page loads the player API only when served over http(s) - in the
 * desktop app the player already runs in a remote, bridge-less, process-
 * isolated frame (desktop-player.html on onlyoffice.github.io); tesseract.js
 * and its worker/LSTM cores are vendored (byte-identical to npm/CDN, sha256 in
 * ocr/3rd-Party.txt) and passed to createWorker; jQuery is vendored; the unused
 * Material Icons links are gone.
 *
 * This test takes every HTML page the desktop build ships from this repo
 * (build_tools/defaults sdkjs-plugin list + the store, with build_tools'
 * desktop rewrite of https://onlyoffice.github.io/sdkjs-plugins/ -> ../ in a
 * plugin's top-level pages), drops comments, and collects
 *   - <script src>, <link rel=stylesheet|preload|modulepreload|import href>,
 *     @import / url() in <style>, with a remote (http, https, //) URL;
 *   - the same in whatever the page's own inline scripts document.write(),
 *     found by RUNNING those inline scripts (vm) as a file:// desktop page
 *     (location.protocol "file:", AscDesktopEditor user agent);
 * and fails on any of them. It also evaluates the real workerOptions literal
 * of ocr/scripts/ocr.js for a file:// page and checks that the worker and both
 * LSTM cores tesseract.js would load are local files that exist, and that the
 * vendored files match the sha256 recorded in ocr/3rd-Party.txt.
 *
 * KNOWN, NOT fixed (reported, listed in KNOWN below): the Translator widget
 * (translator/index_widget.html) is Google's website-translator element; it has
 * to run Google's scripts inside the very document it translates, and the
 * plugin reads the result through contentDocument. Moving it out of file://
 * needs an https origin we control (or a native scheme) - a product decision.
 *
 * NOT claimed: remote iframes are allowed on purpose (the bridge is gated by
 * origin in desktop-sdk bridge_access.h; YouTube is isolated by
 * --isolate-origins); scripts loaded by local JS files at run time are only
 * covered for tesseract.js (the live CDP run found no others); remote images
 * (help pages) are not scripts; plugins installed from the store are code the
 * user chose to install; build_tools still downloads v1/plugins*.js at BUILD
 * time (deploy_desktop.py). The store renders remote config/CHANGELOG text as
 * HTML (separate issue).
 *
 * Env: RD_REPO   onlyoffice.github.io checkout (default ../onlyoffice.github.io)
 *      BASELINE=1 reads the tree at BASE_REF via git; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const REPO = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'onlyoffice.github.io'));
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || 'cdfcd7a^';
const BASELINE = !!process.env.BASELINE;

function git(args, opts) {
	return execFileSync('git', ['-C', REPO].concat(args), Object.assign({ encoding: 'utf8', maxBuffer: 1 << 28 }, opts || {}));
}
function read(rel, binary) {
	if (BASELINE)
		return git(['show', `${BASE_REF}:${rel}`], binary ? { encoding: 'buffer' } : {});
	return fs.readFileSync(path.join(REPO, rel), binary ? null : 'utf8');
}
function exists(rel) {
	if (BASELINE) {
		try { git(['cat-file', '-e', `${BASE_REF}:${rel}`], { stdio: 'ignore' }); return true; } catch (e) { return false; }
	}
	return fs.existsSync(path.join(REPO, rel));
}
function files(dir) {
	if (BASELINE)
		return git(['ls-tree', '-r', '--name-only', BASE_REF, '--', dir]).split('\n').filter(Boolean);
	const out = [];
	(function walk(rel) {
		for (const e of fs.readdirSync(path.join(REPO, rel), { withFileTypes: true })) {
			const r = rel + '/' + e.name;
			if (e.isDirectory()) walk(r); else out.push(r);
		}
	})(dir);
	return out;
}

// the plugins the desktop build bundles (build_tools/defaults, sdkjs-plugin=)
function bundledPlugins() {
	const def = path.join(__dirname, '..', 'build_tools', 'defaults');
	if (fs.existsSync(def)) {
		const m = /^sdkjs-plugin\s*=\s*["']?([^"'\n]*)/m.exec(fs.readFileSync(def, 'utf8'));
		if (m) return m[1].split(',').map((s) => s.trim()).filter(Boolean);
	}
	return ['ai', 'photoeditor', 'ocr', 'translator', 'thesaurus', 'youtube', 'highlightcode'];
}

// [page path in the repo, page path as shipped, is a plugin top-level page (rewritten)]
function shippedPages() {
	const pages = [];
	for (const p of bundledPlugins()) {
		const base = 'sdkjs-plugins/content/' + p;
		for (const f of files(base)) {
			// build_tools copies the plugin folder's entries by glob('*'): no top-level dot folders
			// (.dev), and drops deploy/
			const top = f.slice(base.length + 1).split('/')[0];
			if (!/\.html?$/i.test(f) || top === 'deploy' || top[0] === '.') continue;
			pages.push([f, f, f.lastIndexOf('/') === base.length]);
		}
	}
	for (const f of files('store')) {
		if (!/\.html?$/i.test(f) || f.startsWith('store/plugin-dev/')) continue;
		if (f.startsWith('store/plugin/'))   // the Plugin Manager itself: {AA2EA9B6-...}/
			pages.push([f, f, f.lastIndexOf('/') === 'store/plugin'.length]);
		else                                 // copied to {AA2EA9B6-...}/store/
			pages.push([f, f, false]);
	}
	return pages;
}

const REMOTE = /^\s*(https?:)?\/\//i;

// remote script / style loads written statically in an HTML fragment
function staticLoads(html) {
	const out = [];
	// comments, and the text of inline scripts (what those write is checked by running them)
	html = html.replace(/<!--[\s\S]*?-->/g, '').replace(/(<script\b[^>]*>)[\s\S]*?<\/script>/gi, '$1</script>');
	let m;
	const reScript = /<script\b([^>]*)>/gi;
	while ((m = reScript.exec(html))) {
		const a = /\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(m[1]);
		if (a) { const u = a[1] || a[2] || a[3]; if (REMOTE.test(u)) out.push(['script', u]); }
	}
	const reLink = /<link\b([^>]*)>/gi;
	while ((m = reLink.exec(html))) {
		const rel = /\brel\s*=\s*["']?([^"'>]*)/i.exec(m[1]);
		const href = /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(m[1]);
		if (!rel || !href || !/stylesheet|preload|modulepreload|import/i.test(rel[1])) continue;
		const u = href[1] || href[2] || href[3];
		if (REMOTE.test(u)) out.push(['link ' + rel[1].trim(), u]);
	}
	const reStyle = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
	while ((m = reStyle.exec(html))) {
		const reUrl = /(?:@import\s+(?:url\()?|url\()\s*["']?([^"')\s;]+)/gi;
		let u;
		while ((u = reUrl.exec(m[1]))) if (REMOTE.test(u[1])) out.push(['css', u[1]]);
	}
	return out;
}

// run the page's inline scripts as a local desktop page; collect what they document.write()
function inlineWrites(html, shippedPath) {
	html = html.replace(/<!--[\s\S]*?-->/g, '');
	const written = [];
	const problems = [];
	const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
	let m;
	while ((m = re.exec(html))) {
		if (/\bsrc\s*=/i.test(m[1]) || !m[2].trim()) continue;
		if (/type\s*=\s*["']?(?!text\/javascript|application\/javascript|module)[^"'\s>]+/i.test(m[1])) continue;
		const doc = {
			write: (s) => written.push(String(s)), writeln: (s) => written.push(String(s)),
			currentScript: null, readyState: 'loading',
			getElementById: () => null, getElementsByTagName: () => [], querySelector: () => null,
			addEventListener: () => {}, createElement: () => ({ setAttribute() {}, style: {}, appendChild() {} }),
			head: { appendChild() {} }, body: null,
		};
		const win = {
			document: doc,
			navigator: { userAgent: 'Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/109.0.0.0 AscDesktopEditor/9.4.0', appName: 'Netscape' },
			location: { protocol: 'file:', href: 'file:///Applications/Ration%20Docs.app/Contents/Resources/editors/' + shippedPath, search: '' },
			addEventListener: () => {}, setTimeout: () => 0, console: { log() {}, warn() {}, error() {} },
		};
		win.window = win; win.self = win; win.top = win; win.parent = win;
		try {
			vm.runInNewContext(m[2], win, { timeout: 1000 });
		} catch (e) {
			// could not run it here: then it must not even mention a remote script
			if (/(https?:)?\\?\/\\?\/[^'"\s]+\.js\b|<script[^>]+src=[^>]*https?:/i.test(m[2]))
				problems.push(['inline script (not runnable here: ' + e.message.split('\n')[0] + ')', m[2].trim().slice(0, 120)]);
		}
	}
	return { written: written.join('\n'), problems: problems };
}

// remote loads that are known and NOT fixed (see header); matched on page + URL prefix
const KNOWN = [
	['sdkjs-plugins/content/translator/index_widget.html', 'https://translate.google.com/translate_a/element.js'],
];

const found = [];
const known = [];
for (const [rel, shipped, topLevel] of shippedPages()) {
	let html = read(rel);
	if (topLevel) html = html.split('https://onlyoffice.github.io/sdkjs-plugins/').join('../');
	const loads = staticLoads(html);
	const inl = inlineWrites(html, shipped);
	for (const l of staticLoads(inl.written)) loads.push(['document.write ' + l[0], l[1]]);
	for (const l of inl.problems) loads.push(l);
	for (const [kind, url] of loads) {
		const k = KNOWN.some(([p, u]) => p === rel && url.indexOf(u) === 0);
		(k ? known : found).push(`${rel}: ${kind} ${url}`);
	}
}

const failures = [];
if (found.length)
	failures.push('remote scripts/styles in shipped local pages:\n    ' + found.join('\n    '));

// tesseract.js: the worker and the engine it loads at run time must be the vendored ones
{
	const ocr = read('sdkjs-plugins/content/ocr/scripts/ocr.js');
	const at = ocr.indexOf('const workerOptions = {');
	if (at < 0) {
		failures.push('ocr.js passes no workerPath/corePath to Tesseract.createWorker: tesseract.js loads its worker and engine from cdn.jsdelivr.net');
	} else {
		const lit = ocr.slice(ocr.indexOf('{', at), (function () {
			let d = 0;
			for (let i = ocr.indexOf('{', at); i < ocr.length; i++) {
				if (ocr[i] === '{') d++;
				else if (ocr[i] === '}' && --d === 0) return i + 1;
			}
			throw new Error('unbalanced braces in workerOptions');
		})());
		const base = 'file:///Applications/Ration%20Docs.app/Contents/Resources/editors/sdkjs-plugins/%7B440EBF13-9B19-4BD8-8621-05200E58140B%7D/index.html?lang=en-EN';
		const opts = vm.runInNewContext('(' + lit + ')', { window: { location: { href: base } }, URL: URL, showProgress: function () {} });
		const dir = base.replace(/[^/]*$/, '');
		const local = (u, what) => {
			if (typeof u !== 'string' || u.indexOf(dir) !== 0) { failures.push(`tesseract ${what} is not a local file next to the plugin: ${u}`); return null; }
			return 'sdkjs-plugins/content/ocr/' + decodeURIComponent(u.slice(dir.length));
		};
		const w = local(opts.workerPath, 'workerPath');
		if (w && !exists(w)) failures.push('tesseract worker missing: ' + w);
		const c = local(opts.corePath, 'corePath');
		// OEM.DEFAULT -> tesseract.js loads the LSTM-only core: SIMD build, or the plain one
		if (c) for (const f of ['tesseract-core-simd-lstm.wasm.js', 'tesseract-core-lstm.wasm.js'])
			if (!exists(c + '/' + f)) failures.push('tesseract core missing: ' + c + '/' + f);
	}
	// the vendored files are the ones recorded (sha256 in 3rd-Party.txt)
	const notes = read('sdkjs-plugins/content/ocr/3rd-Party.txt');
	const re = /sha256 ([0-9a-f]{64})\s+(\S+)/g;
	let m, n = 0;
	while ((m = re.exec(notes))) {
		n++;
		const rel = 'sdkjs-plugins/content/ocr/vendor/tesseract/' + m[2];
		if (!exists(rel)) { failures.push('recorded but not vendored: ' + rel); continue; }
		const h = crypto.createHash('sha256').update(read(rel, true)).digest('hex');
		if (h !== m[1]) failures.push(`sha256 mismatch ${rel}: ${h} != recorded ${m[1]}`);
	}
	if (!n) failures.push('ocr/3rd-Party.txt records no sha256 for vendored tesseract.js');
}

for (const k of known) console.log('KNOWN, not fixed: ' + k);
if (failures.length) {
	console.log('FAIL (' + (BASELINE ? 'baseline ' + BASE_REF : REPO) + ')');
	for (const f of failures) console.log('  - ' + f);
	process.exit(1);
}
console.log(`PASS: ${shippedPages().length} shipped pages of ${REPO}${BASELINE ? ' @' + BASE_REF : ''} load no script or stylesheet from the network (except the ${known.length} known above); tesseract worker/cores local and match their sha256`);

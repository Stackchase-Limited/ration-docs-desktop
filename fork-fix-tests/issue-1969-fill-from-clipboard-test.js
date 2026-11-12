/*
 * #1969 - "Presentation: Allow 'from clipboard' on background image selection":
 * the slide background / shape "Picture or texture" fill only offered From file,
 * From URL and From storage; a copied picture had to be saved to a file first.
 *
 * Fix (web-apps): the "Select picture" menu of PE SlideSettings and ShapeSettings
 * has "From clipboard" (value 3, shown where navigator.clipboard.read exists).
 * Common.Utils.readClipboardImage reads the clipboard, takes the first image/*
 * item and passes it as a data: url to the view's existing setImageUrl - the
 * "From URL" path (SetSlideProps / ShapeApply). No picture -> a warning, no change.
 *
 * This test
 *  1. brace-extracts the real Common.Utils.canReadClipboardImage /
 *     readClipboardImage from utils.js and runs them in jsdom (real Blob and
 *     FileReader) against a stub navigator.clipboard: a PNG item -> its data:
 *     url; text only -> null; read() refused -> null; no clipboard API -> null
 *     and canReadClipboardImage() false;
 *  2. brace-extracts the real onImageSelect of both views and calls it with
 *     the menu item value 3 on a stub view: with a PNG on the clipboard
 *     setImageUrl gets its data: url; with none, Common.UI.warning is shown and
 *     setImageUrl is not called; both fire 'editcomplete';
 *  3. checks both menus list {value: 3} with the textFromClipboard caption, and
 *     en.json has the strings.
 *  Baseline: no readClipboardImage / no value 3 branch -> FAILS.
 *
 * NOT claimed: the menu in the running editor and the picture reaching the
 * document's media (SetSlideProps -> LocalFileGetImageUrl with a data: url,
 * the "From URL" path) - needs a GUI check in the desktop app (copy a picture,
 * slide background > Picture or texture > Select picture > From clipboard).
 *
 * Env: RD_REPO  web-apps checkout (default ../web-apps)
 *      RD_NODE_MODULES  where jsdom lives (default /Users/osindero/dev/active/node_modules)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '72a998da54^';
const NODE_MODULES = process.env.RD_NODE_MODULES || '/Users/osindero/dev/active/node_modules';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(REPO, rel), 'utf8');
}
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function extract(text, marker, what) {
	const at = text.indexOf(marker);
	assert.ok(at !== -1, `${what}: not found - no "From clipboard"`);
	return block(text, at);
}

(async () => {
	const { JSDOM } = require(path.join(NODE_MODULES, 'jsdom'));
	const w = new JSDOM('<!doctype html><body></body>', { runScripts: 'outside-only' }).window;

	const utils = src('apps/common/main/lib/util/utils.js');
	const can = extract(utils, 'Common.Utils.canReadClipboardImage = function', 'Common.Utils.canReadClipboardImage');
	const read = extract(utils, 'Common.Utils.readClipboardImage = function', 'Common.Utils.readClipboardImage');
	w.eval(`var Common = {Utils: {}, UI: {}}; ${can}; ${read};`);

	// a tiny real PNG (1x1)
	const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==';
	const pngItem = () => ({ types: ['text/html', 'image/png'], getType: (t) => Promise.resolve(new w.Blob([Buffer.from(PNG, 'base64')], { type: t })) });
	const textItem = () => ({ types: ['text/plain'], getType: (t) => Promise.resolve(new w.Blob(['hello'], { type: t })) });
	const setClipboard = (read) => {
		Object.defineProperty(w.navigator, 'clipboard', { value: read ? { read } : undefined, configurable: true });
	};
	const readImage = () => new Promise(resolve => w.Common.Utils.readClipboardImage(resolve));

	setClipboard(() => Promise.resolve([textItem(), pngItem()]));
	const got = await readImage();
	console.log(`clipboard [text, png] -> ${got && got.slice(0, 40)}...`);
	assert.strictEqual(got, 'data:image/png;base64,' + PNG, 'the clipboard picture is not handed on as its data: url');

	setClipboard(() => Promise.resolve([textItem()]));
	assert.strictEqual(await readImage(), null, 'text-only clipboard must give null');
	setClipboard(() => Promise.reject(new Error('NotAllowedError')));
	assert.strictEqual(await readImage(), null, 'a refused clipboard read must give null');
	setClipboard(null);
	assert.strictEqual(w.Common.Utils.canReadClipboardImage(), false, 'without the clipboard API the item must be hidden');
	assert.strictEqual(await readImage(), null, 'without the clipboard API must give null');
	console.log('text only, refused read, no clipboard API -> null; item hidden without the API');

	// the two views
	const en = JSON.parse(src('apps/presentationeditor/main/locale/en.json'));
	for (const view of ['SlideSettings', 'ShapeSettings']) {
		const file = `apps/presentationeditor/main/app/view/${view}.js`;
		const text = src(file);
		assert.ok(/\{caption: this\.textFromClipboard, value: 3\b/.test(text), `${view}: the Select picture menu has no From clipboard item`);
		assert.ok(en[`PE.Views.${view}.textFromClipboard`] && en[`PE.Views.${view}.textNoClipboardImage`], `${view}: strings missing from en.json`);
		const fn = extract(text, 'onImageSelect: function', `${view}.onImageSelect`).replace(/^onImageSelect: /, '');
		w.eval(`var __onImageSelect = ${fn};`);
		for (const withPicture of [true, false]) {
			setClipboard(() => Promise.resolve(withPicture ? [pngItem()] : [textItem()]));
			const calls = [];
			let done;
			const finished = new Promise(r => { done = r; });
			const stub = {
				api: {}, textNoClipboardImage: 'none',
				setImageUrl: (url) => calls.push(['setImageUrl', url]),
				fireEvent: (ev) => { calls.push([ev]); done(); },
			};
			w.Common.UI.warning = (o) => calls.push(['warning', o.msg]);
			w.__onImageSelect.call(stub, null, { value: 3 });
			await Promise.race([finished, new Promise(r => setTimeout(r, 2000))]);
			const names = calls.map(c => c[0]).join(',');
			console.log(`${view} From clipboard (${withPicture ? 'picture' : 'no picture'}): ${names}`);
			if (withPicture) {
				assert.deepStrictEqual(calls[0], ['setImageUrl', 'data:image/png;base64,' + PNG], `${view}: the picture is not applied`);
				assert.strictEqual(names, 'setImageUrl,editcomplete');
			} else {
				assert.strictEqual(names, 'warning,editcomplete', `${view}: no picture must warn and change nothing`);
			}
		}
	}
	console.log('PASS #1969: "From clipboard" fills a slide background / shape with the picture on the clipboard');
})().catch(e => { console.error(e && e.message || e); process.exit(1); });

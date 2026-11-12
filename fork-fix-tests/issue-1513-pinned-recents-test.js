/*
 * #1513 - "Pin some of the recent files for easy access": pinning exists
 * (pin button / context menu, sdk 'recent:pinned', desktop-sdk Recents_Pin,
 * pin="1" in recents.xml), but in our start page pinned entries did not stay
 * at the top of Recent: with two files pinned at start the second one was
 * missing from the list, and pinning a row showed it twice.
 *
 * Cause: desktop-apps common/loginpage/src/panelrecent.js _init_collections
 * built the Recent collection with list: _cl_rcbox.find('.file-list-body'),
 * which since the fork's search history (2fa3fc844) matches two elements:
 * the list's body and the hidden #idx-history-body. jQuery inserts into every
 * target (clones for all but the last), so rows went into both, and a pinned
 * row placed with insertAfter($pinned.last()) / prependTo(list) ended up only
 * in the hidden body, or twice in the visible one.
 * Fix: list: _cl_rcbox.children('.file-list-body').
 *
 * This test builds the real Recent panel markup (the tplPage template
 * literal, evaluated), loads the real jQuery and model.js (Collection,
 * FileModel) into jsdom, extracts the real _init_collections, handlePin,
 * addContextMenuEventListener and listitemtemplate, and then
 *  1. adds alpha, beta (pinned), gamma (pinned) as the core sends them: the
 *     visible list must be beta*, gamma*, alpha - each once (baseline: gamma
 *     missing -> FAILS);
 *  2. pins alpha and unpins beta with the row's pin button: the list must be
 *     beta*, gamma*, alpha* then gamma*, alpha*, beta - each once, and the
 *     app must be told (sdk.setRecentFilePinned) each time.
 *
 * NOT claimed: the look of a pinned row (no persistent pin marker in the
 * reskinned list); the native side (unchanged, checked live in a copy of
 * the macOS test app, see the commit).
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      RD_NODE_MODULES  where jsdom lives (default /Users/osindero/dev/active/node_modules)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || 'fc625f1ea2^';
const NODE_MODULES = process.env.RD_NODE_MODULES || '/Users/osindero/dev/active/node_modules';
const { JSDOM } = require(path.join(NODE_MODULES, 'jsdom'));

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', APPS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(APPS, rel), 'utf8');
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
function extract(text, marker) {
	const at = text.indexOf(marker);
	assert.ok(at !== -1, marker + ' not found - test is stale');
	return block(text, at);
}

const recent = src('common/loginpage/src/panelrecent.js');

// the real panel markup
const tplAt = recent.indexOf('args.tplPage = `');
const tplSrc = recent.slice(tplAt + 'args.tplPage = '.length, recent.indexOf('`;', tplAt + 16) + 1);
const lang = new Proxy({}, { get: (t, k) => typeof k === 'string' ? k : undefined });
const panelHtml = new Function('args', '_lang', 'welcomeBannerTemplate', 'return ' + tplSrc + ';')({ action: 'recents' }, lang, '');

const dom = new JSDOM(`<!doctype html><body><div id="panel">${panelHtml}</div></body>`, { runScripts: 'outside-only' });
const w = dom.window;
w.eval(fs.readFileSync(path.join(APPS, 'common/loginpage/vendor/jquery/jquery.js'), 'utf8'));
w.eval('var utils = {Lang:{}}; var Menu = {closeAll(){}, opened:false};');
// model.js is 'use strict', so its declarations stay inside the eval unless exported
w.eval(src('common/loginpage/src/model.js') + '\n;window.Collection = Collection; window.FileModel = FileModel;');
w.eval(extract(src('common/loginpage/src/htmlutils.js'), 'function escapeHtml(value)'));

const calls = [];
w.__pinned = (id, v) => calls.push([id, v]);
const code = `
	var sdk = { setRecentFilePinned: function(id, v) { window.__pinned(id, v); } };
	var isSvgIcons = true;
	var collectionRecents, collectionRecovers, ppmenu = {};
	var view = { $panel: $('#panel'), $boxRecent: $('#box-recent'), $boxRecovery: $('#box-recovery') };
	view.listitemtemplate = function ${extract(recent, 'listitemtemplate: function (info)').replace(/^listitemtemplate: function /, '')};
	${extract(recent, 'function addContextMenuEventListener(')}
	${extract(recent, 'function handlePin(collection, model)')}
	${extract(recent, 'function _init_collections()')}
	_init_collections.call({ view: view });
	window.__add = function (name, id, pinned) {
		var m = new FileModel({ name: name + '.docx', path: '/f/' + name + '.docx', fileid: id, pinned: pinned,
			pinid: pinned ? -id : id, type: 65, format: 'docx', date: '' });
		collectionRecents.add(m);
	};
	window.__rows = function () {
		return $('#box-recent > .file-list-body > .row').map(function () {
			return $(this).find('.name').text().replace(/\\s+/g, '') + ($(this).hasClass('pinned') ? '*' : '');
		}).get().join(', ');
	};
	window.__click = function (name) {
		$('#box-recent > .file-list-body > .row').filter(function () { return $(this).text().indexOf(name) !== -1; })
			.first().find('.col-pin button').trigger('click');
	};`;
w.eval(code);

// ids as the core numbers them: most recent first
w.__add('alpha', 0, false);
w.__add('beta', 1, true);
w.__add('gamma', 2, true);
const atStart = w.__rows();
console.log('Recent at start (alpha, beta*, gamma* in recents.xml):', atStart);
assert.strictEqual(atStart, 'beta.docx*, gamma.docx*, alpha.docx', 'pinned files are not listed once each at the top of Recent');

w.__click('alpha');
const afterPin = w.__rows();
console.log('after pinning alpha:', afterPin);
assert.strictEqual(afterPin, 'beta.docx*, gamma.docx*, alpha.docx*', 'pinning a file does not keep it once at the top');

w.__click('beta');
const afterUnpin = w.__rows();
console.log('after unpinning beta:', afterUnpin);
assert.strictEqual(afterUnpin, 'gamma.docx*, alpha.docx*, beta.docx', 'unpinning a file does not return it below the pinned ones');
console.log('app told:', JSON.stringify(calls));
assert.deepStrictEqual(calls, [[0, true], [1, false]], 'the app is not told about the pin change');

console.log('PASS #1513: pinned recent files stay once at the top of Recent');

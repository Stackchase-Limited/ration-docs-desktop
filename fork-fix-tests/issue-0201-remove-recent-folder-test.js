/*
 * #201 - "delete folder from newest folder": the start page's "Recent folders"
 * list (Open local file) had no way to take an entry off it. Right-clicking a
 * folder did nothing; only the pin button reacted.
 *
 * Cause: desktop-apps common/loginpage/src/panelfolders.js built the rows with
 * no context menu, and the list itself is not stored anywhere: utils.js
 * utils.fn.parseRecent(arr, 'folders') derives it from the folders of the
 * recent files (plus pinned folders), so there was nothing to remove from.
 * Fix: right-click on a folder row opens a menu (Open / Pin or Unpin /
 * Remove from list). "Remove from list" unpins the folder and hides it
 * (utils.fn.hiddenFolders, localStorage 'hiddenFolders'); the recent FILES in
 * it stay in Recent. The folder comes back when a file from it is opened
 * again (its newest file moves up in the recent list).
 *
 * This test loads the real jQuery, events.js, model.js, menu.js, base.js,
 * utils.js, htmlutils.js escapeHtml, panelrecent.js listitemtemplate and
 * String.prototype.hashCode, and the
 * whole of panelfolders.js into jsdom (bootstrap's dropdown stubbed), feeds it
 * recents as the core sends them (onupdaterecents, newest first), then:
 *  1. right-clicks the "beta" folder row and clicks "Remove from list": the
 *     list must lose beta and keep the others (baseline: no menu -> FAILS);
 *  2. sends an update where another file was opened (everything moves down):
 *     beta must stay hidden;
 *  3. sends an update where a file in beta was opened again: beta is back;
 *  4. a pinned folder removed with the menu is unpinned and gone.
 *
 * NOT claimed: the look of the menu or rows (needs a GUI check of the start
 * page); a folder whose newest file was already the most recent file of all is
 * not brought back by reopening that same file (it cannot move up).
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
const BASE_REF = process.env.BASE_REF || 'cfbce8138^';
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

const L = 'common/loginpage/';
const recent = src(L + 'src/panelrecent.js');

const dom = new JSDOM(`<!doctype html><body>
	<div class="main-column tool-menu"></div><div class="main-column col-center"></div><div id="placeholder"></div>
	</body>`, { runScripts: 'dangerously', url: 'http://localhost/loginpage/index.html' });
const w = dom.window;
function run(code) {
	const s = w.document.createElement('script');
	s.textContent = code;
	w.document.body.appendChild(s);
	if (w.__err) throw w.__err;
}
w.addEventListener('error', e => { w.__err = e.error; });

run(fs.readFileSync(path.join(APPS, L + 'vendor/jquery/jquery.js'), 'utf8'));
run('jQuery.fn.dropdown = function () { return this; };');
run(src(L + 'src/events.js'));
run(src(L + 'src/model.js'));
run(src(L + 'src/menu.js'));
run(src(L + 'src/base.js'));
run(src(L + 'src/utils.js'));
run(extract(src(L + 'src/htmlutils.js'), 'function escapeHtml(value)'));
run(extract(recent, 'String.prototype.hashCode = function ()') + ';');
run(`
	utils.Lang = new Proxy({}, { get: function (t, k) { return typeof k === 'string' ? k : undefined; } });
	var isSvgIcons = true, OPEN_FILE_FOLDER = 3, opened = [];
	function openFile(how, p) { opened.push(p); }
	var _sdk = {};
	window.sdk = { on: function (ev, fn) { _sdk[ev] = fn; } };
	function DnDFileZone() {} DnDFileZone.prototype = { render: function () {}, hide: function () {}, show: function () {} };
	var _rv = { listitemtemplate: function ${extract(recent, 'listitemtemplate: function (info)').replace(/^listitemtemplate: function /, '')} };
	window.app = { controller: { recent: { view: _rv } } };
`);
run(src(L + 'src/panelfolders.js'));
run('window.app.controller.folders = (new ControllerFolders).init();');

// recents as the core sends them: newest first
function rec(paths) {
	return paths.map((p, i) => ({ id: i, type: 65, path: p, modifyed: '', cloud: '', pin: false }));
}
function update(paths) { w.eval('_sdk.onupdaterecents')(rec(paths)); }
function rows() {
	return w.$('.action-panel.open .file-list-body > .row').map(function () {
		return w.$(this).find('.name').text().trim() + (w.$(this).hasClass('pinned') ? '*' : '');
	}).get().join(', ');
}
function rowOf(name) {
	return w.$('.action-panel.open .file-list-body > .row').filter(function () {
		return w.$(this).find('.name').text().trim() === name;
	}).first();
}
function menuClick(name, caption) {
	const $row = rowOf(name);
	assert.ok($row.length, name + ' is not listed');
	const ev = new w.MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 10 });
	$row.get(0).dispatchEvent(ev);
	const $item = w.$('.menu-container .dd-item').filter(function () {
		return w.$(this).text().trim() === caption && w.$(this).parent().css('display') !== 'none';
	});
	assert.ok($item.length, `right-clicking the "${name}" folder gives no "${caption}" item: there is no way to remove it from Recent folders`);
	$item.first().trigger('click');
}

update(['/u/alpha/a1.docx', '/u/beta/b1.xlsx', '/u/gamma/g1.pptx', '/u/beta/b2.docx']);
const atStart = rows();
console.log('Recent folders at start:', atStart);
assert.strictEqual(atStart, 'alpha, beta, gamma');

menuClick('beta', 'menuRemoveModel');
const afterRemove = rows();
console.log('after "Remove from list" on beta:', afterRemove);
assert.strictEqual(afterRemove, 'alpha, gamma', 'beta is still listed after "Remove from list"');

update(['/u/delta/d1.docx', '/u/alpha/a1.docx', '/u/beta/b1.xlsx', '/u/gamma/g1.pptx', '/u/beta/b2.docx']);
const afterOther = rows();
console.log('after opening a file elsewhere:', afterOther);
assert.strictEqual(afterOther, 'delta, alpha, gamma', 'a removed folder came back without a file from it being opened');

update(['/u/beta/b2.docx', '/u/delta/d1.docx', '/u/alpha/a1.docx', '/u/beta/b1.xlsx', '/u/gamma/g1.pptx']);
const afterReopen = rows();
console.log('after opening a file in beta again:', afterReopen);
assert.strictEqual(afterReopen, 'beta, delta, alpha, gamma', 'a removed folder did not come back when a file from it was opened');

menuClick('gamma', 'menuFilePin');
console.log('after pinning gamma:', rows());
assert.strictEqual(rows(), 'gamma*, beta, delta, alpha');
menuClick('gamma', 'menuRemoveModel');
console.log('after "Remove from list" on pinned gamma:', rows());
assert.strictEqual(rows(), 'beta, delta, alpha', 'a pinned folder stays after "Remove from list"');
assert.ok(!JSON.parse(w.localStorage.getItem('pinnedFolders') || '[]').includes('/u/gamma'), 'gamma is still pinned');

menuClick('alpha', 'menuFileOpen');
assert.strictEqual(JSON.stringify(w.eval('opened')), '["/u/alpha"]', '"Open" does not open the folder');

console.log('PASS #201: a folder can be removed from Recent folders and comes back when a file in it is opened');

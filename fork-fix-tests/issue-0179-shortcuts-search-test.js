/*
 * #179 - keyboard shortcuts could not be searched by the feature's name.
 *
 * 9.x has a Keyboard Shortcuts dialog with a search box (web-apps
 * common/main/lib/view/ShortcutsDialog.js, File > Advanced settings >
 * Keyboard Shortcuts), so the request is mostly met. But its filter only
 * looked for the typed text inside the action name, and the names come from
 * the locale files written as one word ("InsertPageBreak", "ApplyHeading1",
 * "MoveToNextPage" - in en.json and the other locales alike). Typing the
 * feature's words, "page break" or "next page", found nothing, and the
 * description ("Insert a page break at the current cursor position.") was
 * not searched at all.
 *
 * Fix: _filterActionsList ignores spaces when it matches the name and also
 * matches the description.
 *
 * This extracts the REAL _filterActionsList and onInputSearch and runs them
 * on the REAL document editor action names and descriptions from
 * apps/documenteditor/main/locale/en.json (the c_oAscDocumentShortcutType names
 * the controller builds them from are taken from the en.json keys).
 *
 * NOT claimed: the dialog as drawn.
 *
 * RD_REPO overrides the web-apps checkout (default ../web-apps). BASELINE=1
 * reads the parent of the fix commit (BASE_REF), where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '459948889e^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
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
function method(source, name) {
	const m = new RegExp('\\n\\s*' + name + '\\s*:\\s*function\\b').exec(source);
	assert.ok(m, name + ' not found');
	const src = block(source, m.index);
	return src.slice(src.indexOf('function'));
}

const dialog = read('apps/common/main/lib/view/ShortcutsDialog.js');
const locale = JSON.parse(fs.readFileSync(path.join(REPO, 'apps/documenteditor/main/locale/en.json'), 'utf8'));
const prefix = 'Common.Controllers.Shortcuts.txtLabel';
const actions = {};
let type = 0;
for (const key of Object.keys(locale)) {
	if (!key.startsWith(prefix)) continue;
	const name = key.slice(prefix.length);
	actions[++type] = {
		action: { name: locale[key], description: locale['Common.Controllers.Shortcuts.txtDescription' + name] || '', type },
		shortcuts: [],
	};
}
assert.ok(Object.keys(actions).length > 100, 'expected the document editor actions');

const _ = { values: o => Object.values(o) };
const $ = el => ({ val: () => el.value });
const filter = new Function('_', '$', 'return (' + method(dialog, '_filterActionsList') + ');')(_, $);
const onInput = new Function('_', '$', 'return (' + method(dialog, 'onInputSearch') + ');')(_, $);

function search(text) {
	let shown = null;
	const dlg = {
		_state: { searchValue: '' },
		_getActionsMap: () => actions,
		actionsList: { store: { reset: data => { shown = data.map(d => d.action.name); } } },
		onSelectActionItem() {},
	};
	dlg._filterActionsList = filter;
	onInput.call(dlg, { target: { value: text } });
	return shown;
}

let failed = 0;
function check(what, fn) {
	try { fn(); console.log('ok   ' + what); }
	catch (e) { failed++; console.log('FAIL ' + what + ': ' + e.message); }
}

/* unchanged on both trees */
check('a word from the name still finds it ("bold")', () => assert.ok(search('bold').includes('Bold')));
check('an empty search shows every action', () => assert.strictEqual(search('').length, Object.keys(actions).length));

/* the fix */
check('"page break" finds InsertPageBreak', () => assert.ok(search('page break').includes('InsertPageBreak'), search('page break').join(',')));
check('"Next Page" finds MoveToNextPage', () => assert.ok(search('Next Page').includes('MoveToNextPage')));
check('"nonprinting" (only in the description) finds ShowAll', () => assert.ok(search('nonprinting').includes('ShowAll')));
check('several words of the description ("cursor position")', () =>
	assert.ok(search('cursor position').includes('InsertPageBreak')));
check('nonsense finds nothing', () => assert.strictEqual(search('zzqqxx').length, 0));

if (failed) {
	console.log(`${failed} check(s) FAILED`);
	process.exit(1);
}
console.log('PASS #179 shortcuts search');

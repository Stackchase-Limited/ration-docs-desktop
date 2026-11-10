/*
 * #1655 - Pivot table "Grouping" dialog: on macOS the "By" list (Seconds ...
 * Years) cannot select non-adjacent units, e.g. Years + Months without
 * Quarters. Shift+click selects a range; nothing adds a single item.
 *
 * Cause: Common.UI.DataView (web-apps apps/common/main/lib/component/DataView.js)
 * only treats ctrlKey on a click as "add/remove this item". On macOS ctrl+click
 * is a right click (Chromium fires contextmenu, no click), and Cmd+click
 * (metaKey) was handled as a plain click that replaces the selection.
 * Fix: on macOS a Cmd+click toggles the item like ctrl+click does elsewhere, and
 * releasing Cmd ends the toggle mode, as releasing Ctrl does.
 *
 * The grouping itself was never wrong: run in docbuilder, Years+Months,
 * Quarters+Months and Months+Days give Excel's nesting and sums, and the xlsx
 * round trip writes/reads Excel's fieldGroup par/base layout. Only the selection
 * of the units in the dialog was missing.
 *
 * This extracts the real DataView onClickItem, selectRecord and onKeyUp
 * (the PivotGroupDialog list is a ListView with multiSelect: true, which uses
 * them unchanged) and runs them against a stub store of the dialog's 7 units.
 * Checks:
 *   1. macOS: click Years, Cmd+click Months -> Years + Months selected   <- FAILS on baseline
 *   2. macOS: release Cmd, plain click -> only that item (guard against a
 *      sticky toggle mode)                                               <- FAILS on baseline
 *   3. Windows/Linux: ctrl+click still toggles, metaKey is not ctrl (guard)
 *   4. Shift+click still selects a range (guard)
 *
 * Env: RD_REPO = web-apps checkout (default ../web-apps),
 *      BASELINE=1 reads DataView.js from BASE_REF via git show; must FAIL.
 * NOT claimed: the real mouse event in the Mac app (Cmd+click reaching the
 * list as a click with metaKey) - needs a GUI check.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'd420245695^';
const REL = 'apps/common/main/lib/component/DataView.js';

const text = process.env.BASELINE
	? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
	: fs.readFileSync(path.join(REPO, REL), 'utf8');

/* only Common.UI.DataView, not DataViewSimple further down */
const dvStart = text.indexOf('Common.UI.DataView = Common.UI.BaseView.extend(');
const dvEnd = text.indexOf('Common.UI.DataViewSimple = ');
assert.ok(dvStart > 0 && dvEnd > dvStart, 'Common.UI.DataView not found');
const dv = text.slice(dvStart, dvEnd);

function block(src, from) {
	const open = src.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < src.length; i++) {
		if (src[i] === '{') depth++;
		else if (src[i] === '}' && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}
function method(name) {
	const at = dv.indexOf(name + ': function');
	assert.notStrictEqual(at, -1, name + ' not found');
	return block(dv, at).replace(new RegExp('^' + name + ':\\s*'), '');
}

const Common = { UI: { Keys: { SHIFT: 16, CTRL: 17, META: 91 } }, Utils: { isMac: true } };
const _ = { each: (a, f) => a.forEach(f), bind: (f, t) => f.bind(t) };
const window = {};
const proto = new Function('Common', '_', 'window', 'setTimeout',
	'return {onClickItem: ' + method('onClickItem') + ',\nselectRecord: ' + method('selectRecord') +
	',\nonKeyUp: ' + method('onKeyUp') + '};')(Common, _, window, setTimeout);

function makeList() {
	const units = ['Seconds', 'Minutes', 'Hours', 'Days', 'Months', 'Quarters', 'Years'];
	const models = units.map((value) => {
		const attrs = { value, selected: false };
		return { get: (k) => attrs[k], set: (o) => Object.assign(attrs, o) };
	});
	const list = Object.assign(Object.create(proto), {
		multiSelect: true, showLast: true, handleSelect: true, enableKeyEvents: true,
		store: { models, where: (q) => models.filter((m) => m.get('selected') === q.selected) },
		suspendEvents() {}, resumeEvents() {}, trigger() {},
	});
	const rec = (v) => models[units.indexOf(v)];
	const click = (v, mods) => list.onClickItem({ $el: { data: () => null } }, rec(v), Object.assign({ ctrlKey: false, metaKey: false, shiftKey: false }, mods));
	const selected = () => models.filter((m) => m.get('selected')).map((m) => m.get('value'));
	return { list, click, selected };
}

const failures = [];
function check(name, f) {
	try { f(); console.log('ok   ' + name); }
	catch (e) { failures.push(name); console.log('FAIL ' + name + ': ' + e.message); }
}

check('1. macOS: Years, then Cmd+click Months -> Years + Months', () => {
	Common.Utils.isMac = true;
	const t = makeList();
	t.click('Years');
	t.click('Months', { metaKey: true });
	assert.deepStrictEqual(t.selected(), ['Months', 'Years']);
	t.click('Years', { metaKey: true });      // Cmd+click again removes it
	assert.deepStrictEqual(t.selected(), ['Months']);
});

check('2. macOS: after releasing Cmd a plain click selects only that item', () => {
	Common.Utils.isMac = true;
	const t = makeList();
	t.click('Years');
	t.click('Months', { metaKey: true });
	assert.deepStrictEqual(t.selected(), ['Months', 'Years'], 'Cmd+click must add Months');
	t.list.onKeyUp({ keyCode: 91 });          // Cmd released
	t.click('Days');
	assert.deepStrictEqual(t.selected(), ['Days']);
});

check('3. Windows/Linux: ctrl+click toggles, Win key is not ctrl (guard)', () => {
	Common.Utils.isMac = false;
	let t = makeList();
	t.click('Years');
	t.click('Months', { ctrlKey: true });
	assert.deepStrictEqual(t.selected(), ['Months', 'Years']);
	t.list.onKeyUp({ keyCode: 17 });
	t.click('Days');
	assert.deepStrictEqual(t.selected(), ['Days']);
	t = makeList();
	t.click('Years');
	t.click('Months', { metaKey: true });
	assert.deepStrictEqual(t.selected(), ['Months']);
});

check('4. Shift+click still selects a range (guard)', () => {
	Common.Utils.isMac = true;
	const t = makeList();
	t.click('Months');
	t.click('Years', { shiftKey: true });
	assert.deepStrictEqual(t.selected(), ['Months', 'Quarters', 'Years']);
});

if (failures.length) {
	console.log(`\n#1655: ${failures.length} check(s) FAILED`);
	process.exit(1);
}
console.log('\n#1655: all checks passed');

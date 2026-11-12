/*
 * #947 "Writer - Align vertically in cell option displaying": "Display vertical
 * centering options in more place than just right-clicking onto cell (and
 * permit to apply it to more than one cell at a time)".
 *
 * Before: in the document editor the vertical alignment of table cells was
 * only in the table context menu (Cell Vertical Alignment). The right-hand
 * Table settings panel had no such control. (sdkjs already applies
 * CTableProp.CellsVAlign to every selected cell - CTable.Set_Props,
 * word/Editor/Table.js "CellsVAlign" - and reports null when the selected
 * cells differ; the gap was the UI only.)
 *
 * Now (web-apps, documenteditor TableSettings panel): under "Rows & columns
 * size" there is "Cell vertical alignment" with Top / Middle / Bottom toggle
 * buttons. A click sends api.tblApply(CTableProp{CellsVAlign}) - the same call
 * the context menu makes - so it acts on all selected cells; the pressed button
 * follows the selection (none pressed when the selected cells differ).
 *
 * This extracts the REAL #947 block of TableSettings.createDelayedControls,
 * onCellsVAlignClick, updateCellsVAlign and ChangeSettings by brace matching /
 * markers and runs them against stubs (Common.UI.Button, Asc, api); it also
 * checks the template holds the three button hosts and that en.json has the
 * strings.
 *
 * NOT claimed: the panel's look (button placement, icons, hints) - needs a GUI
 * check; nothing about the table advanced settings dialog.
 *
 *   node fork-fix-tests/issue-0947-table-cell-valign-panel-test.js
 *   RD_REPO=<web-apps checkout>   (default ../web-apps)
 *   BASELINE=1                    runs against BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'web-apps');
const BASE_REF = process.env.BASE_REF || '34fa78bf7d^';
const BASELINE = !!process.env.BASELINE;
const DE = 'apps/documenteditor/main/';

function src(rel) {
	try {
		return BASELINE
			? execFileSync('git', ['-C', REPO, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28, stdio: ['ignore', 'pipe', 'ignore'] })
			: fs.readFileSync(path.join(REPO, rel), 'utf8');
	} catch (e) { return ''; }
}
function extract(text, marker) {
	const at = text.indexOf(marker);
	if (at === -1) return null;
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(at, i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}
function fnOf(text, name) {
	const s = extract(text, name + ': function');
	return s && s.slice(s.indexOf('function'));
}

const viewJs = src(DE + 'app/view/TableSettings.js');
const tpl = src(DE + 'app/template/TableSettings.template');
const en = JSON.parse(src(DE + 'locale/en.json') || '{}');

const VA = { Top: 0, Center: 1, Bottom: 3 };   // Asc.c_oAscVertAlignJc
const Asc = {
	c_oAscVertAlignJc: VA,
	CTableProp: function () { this.put_CellsVAlign = (v) => { this.CellsVAlign = v; }; },
};
const _ = {
	bind: (fn, c) => fn.bind(c),
	each: (a, f) => a.forEach(f),
};
function Button(opts) {
	this.options = opts; this.pressed = false; this.handlers = {};
	this.on = (ev, f) => { this.handlers[ev] = f; return this; };
	this.toggle = (v) => { this.pressed = !!v; };
	this.click = () => this.handlers.click(this);
}
const $ = (sel) => ({ sel });

/* build the panel's buttons from the real #947 block */
function makePanel() {
	const start = viewJs.indexOf('// #947');
	assert.ok(start !== -1, 'TableSettings: no #947 cell vertical alignment block');
	const end = viewJs.indexOf('this.btnAddFormula = new Common.UI.Button', start);
	const block = viewJs.slice(start, end);
	const onClick = fnOf(viewJs, 'onCellsVAlignClick');
	const update = fnOf(viewJs, 'updateCellsVAlign');
	assert.ok(onClick && update, 'onCellsVAlignClick / updateCellsVAlign missing');
	const calls = [], events = [];
	const me = {
		$el: {}, lockedControls: [], _locked: false, _state: { CellsVAlign: undefined },
		textAlignTop: 'T', textAlignMiddle: 'M', textAlignBottom: 'B',
		api: { tblApply: (p) => calls.push(p) },
		fireEvent: (e) => events.push(e),
	};
	const mk = (code) => new Function('Common', 'Asc', '_', '$', 'return ' + code)({ UI: { Button } }, Asc, _, $);
	me.onCellsVAlignClick = mk(onClick);
	me.updateCellsVAlign = mk(update);
	new Function('me', 'Common', 'Asc', '_', '$', block).call(me, me, { UI: { Button } }, Asc, _, $);
	return { me, calls, events };
}

const cases = [
	['A. template has the label and three button hosts', () => {
		assert.ok(/scope\.textCellVAlign/.test(tpl), 'template: no textCellVAlign label');
		for (const id of ['top', 'middle', 'bottom'])
			assert.ok(tpl.includes(`id="table-btn-valign-${id}"`), 'template: no table-btn-valign-' + id);
	}],
	['B. en.json has the strings', () => {
		for (const k of ['textCellVAlign', 'textAlignTop', 'textAlignMiddle', 'textAlignBottom'])
			assert.ok(en['DE.Views.TableSettings.' + k], 'en.json: missing DE.Views.TableSettings.' + k);
	}],
	['C. three toggle buttons in one group, lockable, Top/Center/Bottom', () => {
		const { me } = makePanel();
		const b = me._btnsCellVAlign;
		assert.strictEqual(b.length, 3);
		assert.deepStrictEqual(b.map((x) => x.options.valign), [VA.Top, VA.Center, VA.Bottom]);
		assert.deepStrictEqual(b.map((x) => x.options.parentEl.sel), ['#table-btn-valign-top', '#table-btn-valign-middle', '#table-btn-valign-bottom']);
		b.forEach((x) => {
			assert.strictEqual(x.options.enableToggle, true);
			assert.strictEqual(x.options.toggleGroup, 'table-cells-valign');
			assert.ok(me.lockedControls.includes(x), 'button not disabled with the panel');
		});
	}],
	['D. a click applies CellsVAlign through tblApply (all selected cells, like the context menu)', () => {
		const { me, calls, events } = makePanel();
		me._btnsCellVAlign[1].click();
		me._btnsCellVAlign[2].click();
		assert.deepStrictEqual(calls.map((p) => p.CellsVAlign), [VA.Center, VA.Bottom]);
		assert.strictEqual(events.filter((e) => e === 'editcomplete').length, 2);
	}],
	['E. a locked panel applies nothing', () => {
		const { me, calls } = makePanel();
		me._locked = true;
		me._btnsCellVAlign[0].click();
		assert.strictEqual(calls.length, 0);
	}],
	['F. the pressed button follows the selection; mixed cells (null) press none', () => {
		const { me } = makePanel();
		const pressed = () => me._btnsCellVAlign.map((x) => x.pressed);
		me.updateCellsVAlign(VA.Bottom);
		assert.deepStrictEqual(pressed(), [false, false, true]);
		me.updateCellsVAlign(VA.Top);
		assert.deepStrictEqual(pressed(), [true, false, false]);
		me.updateCellsVAlign(null);
		assert.deepStrictEqual(pressed(), [false, false, false]);
	}],
	['G. ChangeSettings passes the selection\'s CellsVAlign to the buttons', () => {
		const cs = fnOf(viewJs, 'ChangeSettings');
		assert.ok(cs && /this\.updateCellsVAlign\(props\.get_CellsVAlign\(\)\)/.test(cs), 'ChangeSettings does not update the buttons');
	}],
];

let failed = 0;
for (const [name, fn] of cases) {
	try { fn(); console.log('PASS ' + name); }
	catch (e) { failed++; console.log('FAIL ' + name + ': ' + e.message); }
}
console.log(failed ? `${failed} of ${cases.length} FAILED${BASELINE ? ' (baseline ' + BASE_REF + ')' : ''}` : `all ${cases.length} passed`);
process.exit(failed ? 1 : 0);

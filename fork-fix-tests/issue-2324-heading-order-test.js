/*
 * #2324 - "Inverse heading style order". The style gallery on the Home tab lists
 * Heading 9, Heading 8, ... Heading 1, the reverse of Word's order.
 *
 * web-apps does not order that list - it renders
 * stylePainter.get_MergedStyles() in the order it is handed
 * (apps/documenteditor/main/app/controller/Toolbar.js, _onInitEditorStyles).
 * The order is decided in sdkjs, in
 * StylePreviewGenerator.prototype.OnEnd (word/Drawing/stylespainter.js): styles
 * are bucketed by w:uiPriority - every heading is uiPriority 9 - and each bucket
 * is then meant to be sorted by name, which would give Heading 1 ... Heading 9.
 *
 * That sort never ran. Its comparator reads a.Name/b.Name, but the objects in
 * the bucket are AscCommon.CStyleImage, which keeps the name in "name"
 * (common/apiCommon.js:6700). undefined < undefined and undefined > undefined
 * are both false, so the comparator returned 0 for every pair and the bucket
 * kept whatever order the style manager happened to hold - which is where the
 * reversed headings come from. The same typo made the _map_document dedupe key
 * every entry under undefined.
 *
 * This extracts the real OnEnd by brace matching and runs it over CStyleImage
 * objects built by the real CStyleImage constructor, also brace-matched out of
 * common/apiCommon.js.
 *
 * BASELINE=1 re-reads word/Drawing/stylespainter.js from git and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'word/Drawing/stylespainter.js';
const BASE_REF = process.env.BASE_REF || 'HEAD';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

const apiCommon = fs.readFileSync(path.join(SDKJS, 'common/apiCommon.js'), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

/* --- the real CStyleImage --- */
const ciAt = apiCommon.indexOf('function CStyleImage(name, type, image, uiPriority)');
assert.notStrictEqual(ciAt, -1, 'CStyleImage not found in common/apiCommon.js');
const CStyleImage = new Function('"use strict"; return ' + matched(apiCommon, ciAt))();
{
	const probe = new CStyleImage('Heading 1', 0, 'png', 9);
	assert.strictEqual(probe.name, 'Heading 1');
	assert.strictEqual(probe.Name, undefined,
		'CStyleImage has no "Name" - that is the whole point of this test');
	assert.strictEqual(probe.uiPriority, 9);
}

/* --- the real OnEnd --- */
const onEndAt = source.indexOf('StylePreviewGenerator.prototype.OnEnd = function()');
assert.notStrictEqual(onEndAt, -1, 'StylePreviewGenerator.OnEnd not found');
const onEndSrc = matched(source, source.indexOf('(', onEndAt + 'StylePreviewGenerator.prototype.OnEnd = function'.length - 1));
assert.ok(onEndSrc.includes('aPriorityStyles'), 'extracted the wrong function');
const OnEnd = new Function('"use strict"; return function' + onEndSrc)();

/* --- 0. the premise: web-apps renders what it is given, in order ---
 * If the toolbar ever starts sorting the list itself, this stops being the
 * place to fix #2324. */
{
	const toolbar = path.resolve(__dirname, '..', 'web-apps',
		'apps/documenteditor/main/app/controller/Toolbar.js');
	if (fs.existsSync(toolbar)) {
		const src = fs.readFileSync(toolbar, 'utf8');
		const at = src.indexOf('_onInitEditorStyles: function(styles)');
		assert.notStrictEqual(at, -1, '_onInitEditorStyles not found in web-apps');
		const body = matched(src, at);
		assert.ok(body.includes('get_MergedStyles()'), 'the toolbar reads the merged list');
		assert.ok(!/\.sort\s*\(/.test(body),
			'the toolbar must not sort the style list - ordering belongs to sdkjs');
	}
}

/* drive OnEnd the way the generator does, and collect what it hands upward */
function mergedOrder(styleNames) {
	const captured = { list: null };
	const self = {
		defaultStyles: [],
		docStyles: styleNames.map(n => new CStyleImage(n, 0, 'png', 9)),
		api: {},
		stylePainter: { OnEndGenerate: function (styles) { captured.list = styles; } }
	};
	OnEnd.call(self);
	assert.ok(captured.list, 'OnEnd must hand the merged list to the painter');
	return captured.list.map(s => s.name);
}

/* --- 1. the defect: the headings come back in the order they went in --- */
{
	const reversed = ['Heading 9', 'Heading 8', 'Heading 7', 'Heading 6', 'Heading 5',
		'Heading 4', 'Heading 3', 'Heading 2', 'Heading 1'];
	const out = mergedOrder(reversed);

	assert.deepStrictEqual(out,
		['Heading 1', 'Heading 2', 'Heading 3', 'Heading 4', 'Heading 5',
			'Heading 6', 'Heading 7', 'Heading 8', 'Heading 9'],
		'the headings must be listed Heading 1 first whatever order the style ' +
		'manager held them in - this is #2324 (got ' + out.join(', ') + ')');
}

/* --- 2. an order that is already right stays right --- */
{
	const ordered = ['Heading 1', 'Heading 2', 'Heading 3'];
	assert.deepStrictEqual(mergedOrder(ordered), ordered);
}

/* --- 3. uiPriority still wins over the name --- */
{
	const captured = { list: null };
	const self = {
		defaultStyles: [],
		docStyles: [
			new CStyleImage('Title', 0, 'png', 10),
			new CStyleImage('Heading 2', 0, 'png', 9),
			new CStyleImage('Normal', 0, 'png', 0),
			new CStyleImage('Heading 1', 0, 'png', 9)
		],
		api: {},
		stylePainter: { OnEndGenerate: function (styles) { captured.list = styles; } }
	};
	OnEnd.call(self);
	assert.deepStrictEqual(captured.list.map(s => s.name),
		['Normal', 'Heading 1', 'Heading 2', 'Title'],
		'styles are grouped by uiPriority first, then named order inside a group');
}

/* --- 4. a document style must not be dropped, and the dedupe key must be a name ---
 * _map_document used to key every entry under undefined, so the first document
 * style suppressed every default one. */
{
	const captured = { list: null };
	const self = {
		defaultStyles: [
			new CStyleImage('Heading 1', 1, 'png', 9),
			new CStyleImage('Quote', 1, 'png', 29)
		],
		docStyles: [new CStyleImage('Heading 1', 0, 'png', 9)],
		api: {},
		stylePainter: { OnEndGenerate: function (styles) { captured.list = styles; } }
	};
	OnEnd.call(self);
	const names = captured.list.map(s => s.name);
	assert.deepStrictEqual(names, ['Heading 1', 'Quote'],
		'the document copy of Heading 1 replaces the default one, and an unrelated ' +
		'default style is still listed');
	assert.strictEqual(captured.list[0].type, 0, 'the document copy is the one kept');
}

console.log('ok - the style gallery lists Heading 1 through Heading 9 in order');

/*
 * #2448 - placeholders added in Slide Master view lost their idx on save, so
 * after reopening, new slides bound several slide placeholders to one layout
 * placeholder (one shown twice, the others missing).
 *
 * Insert Placeholder called ph.setIdx(nMaxIdx + 1) with a number. The editor
 * kept the number, but the history change is a CChangesDrawingsString, whose
 * constructor turns any non-string into undefined. The desktop save replays
 * those changes in x2t, so the file got the placeholder with no idx at all;
 * co-authors received the same. The reporter's file (written by 9.4.0.129)
 * shows exactly that: every added "Text Placeholder 9" without idx, all id 10.
 *
 * This extracts the real Ph.prototype.setIdx (Format.js), the real
 * CChangesDrawingsString constructor (DrawingsChanges.js) and, on the fixed
 * tree, the idx helpers (SlideMaster.js), and drives them with stubs. Run with
 * BASELINE=1 to check the same test against the parent of the fix, where it
 * must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD: once the
// fix is committed HEAD carries it and the baseline would test nothing.
const BASE_REF = process.env.BASE_REF || '6957873dd2^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

/* Brace-match a block starting at `from`, returning the source through its close. */
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
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const format = src('common/Drawings/Format/Format.js');
const changes = src('common/Drawings/DrawingsChanges.js');

/* --- stubs --- */
const recorded = [];
const AscDFH = {
	historyitem_Ph_SetIdx: 1,
	CChangesBaseStringProperty: { call(self, Class, Old, New) { self.Class = Class; self.Old = Old; self.New = New; } },
};
const AscCommon = { History: { Add(change) { recorded.push(change); } } };

const CChangesDrawingsString = new Function('AscDFH',
	extract(changes, 'function CChangesDrawingsString(') + '\nreturn CChangesDrawingsString;')(AscDFH);

function Ph() { this.idx = null; }
new Function('Ph', 'AscCommon', 'CChangesDrawingsString', 'AscDFH',
	extract(format, 'Ph.prototype.setIdx = function') + ';')(Ph, AscCommon, CChangesDrawingsString, AscDFH);

/* 1. a numeric idx - what Insert Placeholder and ApiPlaceholder.SetIndex pass -
      must reach the history change, because that change is what gets saved. */
const ph = new Ph();
ph.setIdx(3);
assert.strictEqual(recorded.length, 1);
assert.strictEqual(recorded[0].New, '3', 'the recorded change lost the idx: saved file and co-authors get none');
assert.strictEqual(ph.idx, '3', 'in-memory idx must match what was recorded');

/* 2. replaying the change (what x2t does on save) reproduces the idx. */
const replayed = new Ph();
replayed.idx = recorded[0].New;
assert.strictEqual(replayed.idx, '3');

/* 3. the idx helpers: next idx is numeric max + 1 over string idx values, and a
      pasted copy is detected as a twin of its source. */
if (!process.env.BASELINE) {
	const master = src('slide/Editor/Format/SlideMaster.js');
	const helpers = new Function(
		extract(master, 'function GetNextPlaceholderIdx(') + '\n' +
		extract(master, 'function HasPlaceholderTwin(') +
		'\nreturn {GetNextPlaceholderIdx, HasPlaceholderTwin};')();
	const sp = (type, idx) => ({
		isPlaceholder: () => type !== undefined,
		getPlaceholderType: () => type,
		getPlaceholderIndex: () => (type === undefined ? null : idx),
	});
	const shape = sp(undefined);
	const body11 = sp(0, '11'), body9 = sp(0, '9'), title = sp(15, null);
	const layout = { cSld: { spTree: [shape, title, body9, body11] } };

	assert.strictEqual(helpers.GetNextPlaceholderIdx(layout), '12', '"11" + 1 must not become "111"');
	assert.strictEqual(helpers.GetNextPlaceholderIdx({ cSld: { spTree: [shape, title] } }), '1');

	const pasted = sp(0, '11');
	layout.cSld.spTree.push(pasted);
	assert.strictEqual(helpers.HasPlaceholderTwin(layout, pasted), true, 'pasted copy shares (body, 11)');
	assert.strictEqual(helpers.GetNextPlaceholderIdx(layout, pasted), '12');
	assert.strictEqual(helpers.HasPlaceholderTwin(layout, body9), false);
	const otherBody = sp(0, null), secondBody = sp(0, null);
	assert.strictEqual(helpers.HasPlaceholderTwin({ cSld: { spTree: [otherBody, secondBody] } }, secondBody), true,
		'two body placeholders without idx are twins');
}

console.log('PASS #2448: placeholder idx survives into the saved change' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));

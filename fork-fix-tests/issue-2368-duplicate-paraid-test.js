/*
 * #2368 - a saved docx carried duplicate w14:paraId values.
 *
 * w14:paraId identifies a paragraph within the document and must be unique.
 * The clipboard binary round-trips it (Serialize2.js: writer emits ParaID,
 * ReadParagraph calls paragraph.SetParaId with the value read back), so
 * pasting a paragraph - or a table row - inside the same document leaves two
 * paragraphs holding one id. The reporter's attached file has six such ids,
 * one of them on five different paragraphs.
 *
 * This extracts the real ParaId-writing block out of Serialize2.js by brace
 * matching and drives it with stubs, over the exact id sequence taken from
 * that file. Run with BASELINE=1 to check the same test against HEAD, where
 * it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'word/Editor/Serialize2.js';
// Pinned to the parent of the commit that landed this fix. It must NOT default to
// HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
// and the test passes forever while testing nothing.
const BASE_REF = process.env.BASE_REF || '7cf9e26ee1^';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

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

/* 1. the real DocSaveParams constructor - supplies usedParaIds, or does not. */
const ctorAt = source.indexOf('function DocSaveParams(');
assert.notStrictEqual(ctorAt, -1, 'DocSaveParams not found');
const ctorSrc = block(source, ctorAt);

/* 2. the real ParaId-writing block from the paragraph writer. */
const paraAt = source.indexOf('let paraId = par.GetParaId();');
assert.notStrictEqual(paraAt, -1, 'ParaId writer not found');
const ifAt = source.indexOf('if (undefined !== paraId && null !== paraId)', paraAt);
const paraSrc = source.slice(paraAt, ifAt) + block(source, ifAt);
assert.ok(paraSrc.includes('WriteLong(paraId)'), 'extracted the wrong block');

/* --- stubs --- */
let nextSynthetic = 0x60000000;
const AscCommon = { CreateDurableId: () => nextSynthetic++ };
const c_oSerParType = { ParaID: 0x2f };

const written = [];
const writer = {
	memory: { WriteByte() {}, WriteLong(v) { written.push(v); } },
	bs: { WriteItemWithLength(fn) { fn(); } },
};

const DocSaveParams = new Function('return ' + ctorSrc)();
writer.saveParams = new DocSaveParams(false, false, false, undefined);

const writeParaId = new Function(
	'AscCommon', 'c_oSerParType', 'par', 'oThis',
	'"use strict";\n' + paraSrc
).bind(writer);

/* Paragraph ids exactly as they appear in the reporter's broken.docx: three
 * ids repeat (two of them once, one of them five times over a copied table
 * column), the rest are distinct. */
const ids = [
	0x760F7FAD, 0x21190F21, 0x71F6FEB4,          // originals
	0x0AB2418A, 0x21190F21, 0x71F6FEB4,          // pasted back - ids reused
	0x4FEF352E, 0x4FEF352E, 0x4FEF352E,          // a copied table column
	0x4FEF352E, 0x4FEF352E,
	0x11111111, 0x22222222,                      // untouched paragraphs
];

for (const id of ids) {
	const par = { GetParaId: () => id };
	writeParaId(AscCommon, c_oSerParType, par, writer);
}

/* --- assertions --- */
assert.strictEqual(written.length, ids.length, 'every paragraph must still write an id');

const seen = new Set(written);
assert.strictEqual(seen.size, written.length,
	`duplicate w14:paraId written: ${written.map(v => v.toString(16)).join(',')}`);

/* The first paragraph to claim an id keeps it - only later claimants move. */
const firsts = [];
const claimed = new Set();
ids.forEach((id, i) => {
	if (!claimed.has(id)) { claimed.add(id); firsts.push(i); }
});
for (const i of firsts) {
	assert.strictEqual(written[i], ids[i],
		`paragraph ${i} was the first to use ${ids[i].toString(16)} and must keep it`);
}

/* Ids that were never duplicated must be untouched. */
assert.strictEqual(written[ids.indexOf(0x11111111)], 0x11111111);
assert.strictEqual(written[ids.indexOf(0x22222222)], 0x22222222);

/* Nothing is renumbered when there is nothing to fix. */
writer.saveParams = new DocSaveParams(false, false, false, undefined);
written.length = 0;
for (const id of [1, 2, 3, 4]) writeParaId(AscCommon, c_oSerParType, { GetParaId: () => id }, writer);
assert.deepStrictEqual(written, [1, 2, 3, 4], 'a clean document must be written unchanged');

console.log('ok - %d paragraph ids written, all distinct, %d renumbered',
	ids.length, ids.length - new Set(ids).size);

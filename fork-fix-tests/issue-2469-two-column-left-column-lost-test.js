/*
 * #2469 - in a document with a 1-column title, a continuous section break and
 * a 2-column section, the whole left column of page 1 was not drawn (its text
 * appeared nowhere) for a narrow range of vertical offsets; one more Enter
 * brought it back (upstream bug 81956, fixed in 10.0 by sdkjs 0f67b0544a;
 * backported here).
 *
 * Cause: CDocument.prototype.Recalculate_PageColumn (word/Editor/Document.js),
 * on a recalcresult_PrevPage result with recalcresultflags_Column - an element
 * at the top of a column needs the PREVIOUS column recalculated (keep-with-next,
 * widow control...) - steps back to that column and restarts layout from its
 * first element. It then always called PageSection.Init on the page section,
 * which resets every column of the section. When the column it stepped back to
 * is not the first one (the right column), the left column is reset too but is
 * not recalculated - layout restarts at the right column's first element - so
 * the left column's content was laid out nowhere. Now the section is only
 * re-initialised when layout restarts at its first column.
 *
 * Reproduced headless in docbuilder with the reporter's two-columns-repro.docx:
 * the 9.4 build's PDF of page 1 has the title and the right column only (256
 * words); with the fix, 493 words with the left column. Same layout as x2t.
 *
 * This brace-matches the REAL `else if (RecalcResult & recalcresult_PrevPage)`
 * branch out of Recalculate_PageColumn (and the real recalcresult constants)
 * and runs it against stub pages/sections: stepping back from the left column
 * of page 2 to the right column of page 1 must leave page 1's left column as
 * it was; stepping back to a first column must still re-initialise the section.
 * NOT claimed: the rest of Recalculate_PageColumn, or which element returns
 * recalcresult_PrevPage for the reporter's file (that part is covered only by
 * the docbuilder run described above).
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads the source at
 * BASE_REF (default: the parent of the fix commit) with git show, where it
 * must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the fix commit, never HEAD.
const BASE_REF = process.env.BASE_REF || 'ba6466c2e1^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}

function block(text, from) {
	let depth = 0;
	for (let i = text.indexOf('{', from); i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const documentSrc = src('word/Editor/Document.js');
const fnAt = documentSrc.indexOf('CDocument.prototype.Recalculate_PageColumn');
assert.notStrictEqual(fnAt, -1, 'Recalculate_PageColumn not found');
const fn = block(documentSrc, fnAt);
const marker = 'if (RecalcResult & recalcresult_PrevPage)';
const branchAt = fn.indexOf('else ' + marker);
assert.notStrictEqual(branchAt, -1, 'recalcresult_PrevPage branch not found');
const branch = block(fn, branchAt + 'else '.length);

const constants = (documentSrc.match(/^var recalcresult\w*\s*=\s*0x[0-9A-Fa-f]+;/mg) || []).join('\n');
assert.ok(/recalcresult_PrevPage/.test(constants) && /recalcresultflags_Column/.test(constants), 'constants not found');

// The branch reads and writes locals of Recalculate_PageColumn; run it with those
// as locals of a wrapper and hand back the ones it sets. `break` leaves the loop.
const run = new Function('state', constants + `
	var RecalcResult = state.RecalcResult, PageIndex = state.PageIndex, SectionIndex = state.SectionIndex,
		ColumnIndex = state.ColumnIndex;
	var bReDraw = true, bContinue = false, _PageIndex, _SectionIndex, _ColumnIndex, _StartIndex, _sectPr, _bStart;
	for (;;) {
		${branch}
		break;
	}
	return { bContinue, _PageIndex, _SectionIndex, _ColumnIndex, _StartIndex, _bStart };
`);

/* --- stubs: a page section whose Init resets all its columns, as the real one does --- */
function column(pos, endPos) { return { Pos: pos, EndPos: endPos, Empty: false, laidOut: true }; }
function section(columns, sectPr) {
	return {
		Columns: columns, inits: 0, Y: 0, sectPr,
		GetSectPr() { return this.sectPr; },
		GetBottomLimit() { return 100; },
		Init() { this.inits++; this.Columns.forEach(c => { c.laidOut = false; c.Empty = true; }); },
	};
}
function makeDoc(pages) {
	return {
		Pages: pages,
		Layout: { GetSectionIndex() { return 0; } },
		RecalcInfo: { HaveFlowObject() { return false; } },
		run(state) { return run.call(this, state); },
	};
}

const PrevColumn = (() => {
	const c = new Function(constants + '\nreturn recalcresult_PrevPage | recalcresultflags_Column;')();
	return c;
})();

/* 1. the reporter's case: page 1 = title section + 2-column section; layout of
      page 2's left column asks for the previous column, i.e. page 1's RIGHT one. */
{
	const title = section([column(0, 0)], 'title');
	const twoCol = section([column(1, 20), column(21, 40)], 'twoCol');
	const page2 = section([column(41, 50), column(51, 60)], 'twoCol');
	const doc = makeDoc([{ Sections: [title, twoCol], YLimit: 800 }, { Sections: [page2], YLimit: 800 }]);
	const r = doc.run({ RecalcResult: PrevColumn, PageIndex: 1, SectionIndex: 0, ColumnIndex: 0 });
	assert.strictEqual(r._PageIndex, 0);
	assert.strictEqual(r._SectionIndex, 1);
	assert.strictEqual(r._ColumnIndex, 1, 'layout restarts at the right column');
	assert.strictEqual(r._StartIndex, 21);
	assert.strictEqual(twoCol.Columns[0].laidOut, true,
		'page 1\'s left column was reset although layout restarts at the right column - its text is laid out nowhere');
	assert.strictEqual(twoCol.inits, 0, 'the section must not be re-initialised from its second column');
}

/* 2. stepping back to a section's FIRST column still re-initialises the section
      (and places it under the previous section), as before. */
{
	const title = section([column(0, 0)], 'title');
	const twoCol = section([column(1, 20), column(21, 40)], 'twoCol');
	const doc = makeDoc([{ Sections: [title, twoCol], YLimit: 800 }]);
	const r = doc.run({ RecalcResult: PrevColumn, PageIndex: 0, SectionIndex: 1, ColumnIndex: 1 });
	assert.strictEqual(r._ColumnIndex, 0);
	assert.strictEqual(r._StartIndex, 1);
	assert.strictEqual(twoCol.inits, 1, 'restarting at the first column must re-initialise the section');
	assert.ok(Math.abs(twoCol.Y - 100.001) < 1e-9, 'the section must start below the previous one');
}

console.log('PASS #2469: stepping back to a later column keeps the earlier columns of the section' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));

/*
 * #2425, part 2 - "Fill handle is hard to trigger": the cursor turns into the
 * black cross only on a very small, precise area at the corner of the selection,
 * and usually shows the move cursor instead.
 *
 * Two pieces of cell/view/WorksheetView.js disagreed about how big the handle is.
 *
 *   drawing   - _drawSelectionElement paints it as a 5px square inside a 2px
 *               border, and doubles both on a retina canvas:
 *                   retinaKf   = isRetina ? 2 : 1
 *                   size       = 5 * retinaKf
 *                   sizeBorder = size + 2 * retinaKf
 *                   diffBorder = floor(sizeBorder / 2) + retinaKf
 *               so the square runs from x2 - diffBorder, i.e. 4 device pixels
 *               left of the corner on an ordinary screen and 9 on a 2x one.
 *
 *   hit test  - _hitResizeCorner allowed KoefPixToMM + 2, a flat 3 device pixels
 *               on the desktop (KoefPixToMM is 1 there, 5 on touch), with no
 *               retina scaling at all.
 *
 * On a 2x display that is a third of the drawn square. The move-border test in
 * _hitInRange *is* retina-scaled, which is why the move cursor wins.
 *
 * _hitResizeCorner now derives its tolerance from the same numbers the drawing
 * uses. This extracts the real method by brace matching and probes it around a
 * corner; the drawing constants are read out of the real source too, so the test
 * fails if the square is ever resized without the hit test following.
 *
 * BASELINE=1 re-reads cell/view/WorksheetView.js from git and must FAIL there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(__dirname, '..', 'sdkjs');
const REL = 'cell/view/WorksheetView.js';
const BASE_REF = process.env.BASE_REF || 'HEAD';

const source = process.env.BASELINE
	? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${REL}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
	: fs.readFileSync(path.join(SDKJS, REL), 'utf8');

function matched(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

/* --- 0. the premise: how big the handle is actually drawn ---
 * Read it out of _drawSelectionElement rather than trusting this comment. */
const drawn = (function () {
	const at = source.indexOf('// Drawing squares for move/resize');
	assert.notStrictEqual(at, -1, 'the selection-handle drawing block moved');
	const block = source.slice(at, at + 1400);
	assert.ok(/let\s+size\s*=\s*5\s*\*\s*retinaKf;/.test(block),
		'the handle is no longer a 5px square - retune _hitResizeCorner');
	assert.ok(/let\s+sizeBorder\s*=\s*size\s*\+\s*2\s*\*\s*retinaKf;/.test(block),
		'the handle border is no longer 2px - retune _hitResizeCorner');
	assert.ok(/let\s+diffBorder\s*=\s*Math\.floor\(sizeBorder\s*\/\s*2\)\s*\+\s*1\s*\*\s*retinaKf;/.test(block),
		'the handle is no longer anchored at x2 - diffBorder');
	assert.ok(/let\s+retinaKf\s*=\s*isRetina\s*&&\s*\(!isResize\s*\|\|\s*isAllowRetinaResize\)\s*\?\s*2\s*:\s*1;/.test(block),
		'the retina doubling of the handle changed');
	return function (retinaKf) {
		const size = 5 * retinaKf;
		const sizeBorder = size + 2 * retinaKf;
		const diffBorder = Math.floor(sizeBorder / 2) + 1 * retinaKf;
		// the square, relative to the corner at x2: [-diffBorder, sizeBorder - diffBorder]
		return { from: -diffBorder, to: sizeBorder - diffBorder };
	};
})();
assert.deepStrictEqual(drawn(1), { from: -4, to: 3 });
assert.deepStrictEqual(drawn(2), { from: -9, to: 5 });

/* --- the real hit test --- */
const hitAt = source.indexOf('WorksheetView.prototype._hitResizeCorner = function');
assert.notStrictEqual(hitAt, -1, '_hitResizeCorner not found');
const hitSrc = matched(source, source.indexOf('(', hitAt + 'WorksheetView.prototype._hitResizeCorner = function'.length - 1));
const AscCommon = { global_mouseEvent: { KoefPixToMM: 1 } };
const hitResizeCorner = new Function('AscCommon', '"use strict"; return function' + hitSrc)(AscCommon);

/* a WorksheetView stand-in: the method only needs the pixel ratio */
function view(ratio) {
	return { getRetinaPixelRatio: function () { return ratio; } };
}
/* does the corner at (0,0) answer to a pointer d pixels up and to the left? */
function hits(ratio, d) {
	return hitResizeCorner.call(view(ratio), 0, 0, -d, -d);
}

/* --- 1. the defect: on a 2x display the drawn square is not all grabbable --- */
{
	const ratio = 2;
	const box = drawn(2);
	// a pointer sitting squarely inside the painted handle, 6px up-left of the corner
	assert.ok(-6 > box.from, 'sanity: 6px up-left is inside the painted square');
	assert.strictEqual(hits(ratio, 6), true,
		'a pointer inside the painted fill handle must trigger it - on a retina ' +
		'display the grabbable area was a fraction of the square, which is #2425');

	// and the far edge of the painted square too
	assert.strictEqual(hits(ratio, -box.from), true,
		'the whole painted square must be grabbable');
}

/* --- 2. an ordinary display keeps at least the reach it had --- */
{
	AscCommon.global_mouseEvent.KoefPixToMM = 1;
	for (let d = 0; d <= 3; ++d) {
		assert.strictEqual(hits(1, d), true,
			'a 1x display must not lose reach it already had (d=' + d + ')');
	}
	assert.strictEqual(hits(1, 4), true,
		'the painted square reaches 4px up-left on a 1x display');
}

/* --- 3. it must not swallow the whole cell --- */
{
	assert.strictEqual(hits(1, 30), false, 'far from the corner is not the handle');
	assert.strictEqual(hits(2, 30), false, 'far from the corner is not the handle');
	assert.strictEqual(hitResizeCorner.call(view(2), 0, 0, -6, -40), false,
		'both axes have to be close, not just one');
}

/* --- 4. a touch pointer still gets the wider allowance it had --- */
{
	AscCommon.global_mouseEvent.KoefPixToMM = 5;   // set by the mobile touch manager
	const touch1x = hits(1, 7);
	AscCommon.global_mouseEvent.KoefPixToMM = 1;
	assert.strictEqual(touch1x, true,
		'touch used to reach KoefPixToMM + 2 = 7px and must not reach less');
}

console.log('ok - the fill handle can be grabbed anywhere on the square it is drawn as');

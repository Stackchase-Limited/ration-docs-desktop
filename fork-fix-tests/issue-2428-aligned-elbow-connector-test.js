/*
 * #2428 - an elbow connector between the top anchors of two rectangles placed
 * side by side was drawn as a straight line through both anchors, and its
 * yellow adjustment handle could not be dragged. Same for any two anchors that
 * are level across the route (bottom-bottom, left-left of stacked shapes...).
 *
 * Cause: fCalculateSpPr (common/Drawings/Format/CnxShape.js) rotates the route
 * to start eastwards and stores the elbow positions (adj1..adj3) as fractions
 * of the route's extent. For aligned anchors that extent is 0: the fraction is
 * Infinity and `(100000 + Infinity) >> 0` is 0, i.e. the elbow sits on the
 * anchor line (a straight connector) and handle drags, again fractions of a
 * zero extent, do nothing. Reproduced headless in docbuilder with the real
 * AscFormat.fCalculateSpPr: top-top gave bentConnector3 ext=(0, 60) adj1=0.
 *
 * Fix: route over a minimal extent of one line width (penW) where an
 * adjustment depends on the zero axis.
 *
 * This extracts the real fCalculateSpPr, ConnectionParams, CGraphicBounds and
 * the real CMatrix/CGlobalMatrixTransformer, routes three aligned cases plus a
 * straight E-to-W case, and walks the resulting bentConnector3 path (the
 * standard OOXML preset: start, (adj1*w, 0), (adj1*w, h), end) back to slide
 * coordinates. NOT claimed: on-screen drawing or the handle-drag track in the
 * GUI (they only use the stored extent/adj, which this checks are finite).
 *
 * RD_REPO overrides the sdkjs checkout (default ../sdkjs). BASELINE=1 reads the
 * sources at BASE_REF (default: parent of the fix) and must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || '552dc5202c^';

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

const cnx = src('common/Drawings/Format/CnxShape.js');
const base = src('common/Drawings/Format/GraphicObjectBase.js');
const meta = src('common/Drawings/Metafile.js');

/* real matrix code */
const M = new Function(
	extract(meta, 'function CMatrix()') + '\nCMatrix.prototype = ' + block(meta, meta.indexOf('{', meta.indexOf('CMatrix.prototype ='))) + ';\n' +
	extract(meta, 'function CGlobalMatrixTransformer()') +
	'\nreturn {CMatrix: CMatrix, transformer: new CGlobalMatrixTransformer()};')();

/* real bounds */
const CGraphicBounds = new Function(
	extract(base, 'function CGraphicBounds(') + '\n' +
	['fromOther', 'copy', 'transform', 'checkWH'].map(m => extract(base, 'CGraphicBounds.prototype.' + m + ' = function') + ';').join('\n') +
	'\nreturn CGraphicBounds;')();

/* stubs for the spPr/geometry objects the result is written to */
function CXfrm() {}
['OffX', 'OffY', 'ExtX', 'ExtY', 'Rot', 'FlipH', 'FlipV'].forEach(k => {
	CXfrm.prototype['set' + k] = function(v) { this[k.charAt(0).toLowerCase() + k.slice(1)] = v; };
});
CXfrm.prototype.setParent = function() {};
function CSpPr() {}
CSpPr.prototype.setXfrm = function(x) { this.xfrm = x; };
CSpPr.prototype.setGeometry = function(g) { this.geometry = g; };

const AscFormat = {
	CARD_DIRECTION_N: 0, CARD_DIRECTION_E: 2, CARD_DIRECTION_S: 4, CARD_DIRECTION_W: 6,
	CGraphicBounds, CSpPr, CXfrm,
	isRealNumber: n => typeof n === 'number' && !isNaN(n),
	ExecuteNoHistory: (f, t, args) => f.apply(t, args),
	CreateGeometry: preset => ({ preset, adj: {}, setAdjValue(k, v) { this.adj[k] = v; }, setParent() {} }),
	normalizeRotate: r => { while (r >= 2 * Math.PI) r -= 2 * Math.PI; while (r < 0) r += 2 * Math.PI; return r; },
};
const AscCommon = { CMatrix: M.CMatrix, global_MatrixTransformer: M.transformer };

const lib = new Function('AscFormat', 'AscCommon',
	'var CONNECTOR_MARGIN = 6.35;\n' +
	extract(cnx, 'function ConnectionParams()') + '\n' +
	extract(cnx, 'ConnectionParams.prototype.copy = function') + ';\n' +
	extract(cnx, 'ConnectionParams.prototype.transform = function') + ';\n' +
	extract(cnx, 'function fCalculateSpPr(') +
	'\nreturn {ConnectionParams: ConnectionParams, fCalculateSpPr: fCalculateSpPr};')(AscFormat, AscCommon);

function anchor(bounds, x, y, dir) {
	const c = new lib.ConnectionParams();
	c.bounds = new CGraphicBounds(bounds[0], bounds[1], bounds[2], bounds[3]);
	c.x = x; c.y = y; c.dir = AscFormat['CARD_DIRECTION_' + dir];
	return c;
}

/* walk a bentConnector3 back to slide coordinates */
function routePoints(spPr) {
	const x = spPr.xfrm, g = spPr.geometry;
	assert.strictEqual(g.preset, 'bentConnector3');
	const adj1 = g.adj.adj1 === undefined ? 50000 : g.adj.adj1;
	const w = x.extX, h = x.extY, x1 = w * adj1 / 100000;
	const cx = x.offX + w / 2, cy = x.offY + h / 2, c = Math.cos(x.rot), s = Math.sin(x.rot);
	return [[0, 0], [x1, 0], [x1, h], [w, h]].map(([px, py]) => {
		let dx = px - w / 2, dy = py - h / 2;
		if (x.flipH) dx = -dx;
		if (x.flipV) dy = -dy;
		return [cx + dx * c - dy * s, cy + dx * s + dy * c];
	});
}
const near = (p, q, tol) => Math.abs(p[0] - q[0]) <= tol && Math.abs(p[1] - q[1]) <= tol;

const failures = [];
function check(name, fn) {
	try { fn(); console.log('ok   ' + name); }
	catch (e) { failures.push(name); console.log('FAIL ' + name + ': ' + e.message); }
}

const A = [20, 30, 50, 50], B = [80, 30, 110, 50];   // side by side, tops level at y=30
const ELBOW = 6.35 - 0.5;                            // CONNECTOR_MARGIN, minus slack

function elbow(name, from, to, axis, sign, penW = 12700) {
	check(name, () => {
		const sp = lib.fCalculateSpPr(from, to, 'bentConnector3', penW);
		const p = routePoints(sp);
		assert.ok(near(p[0], [from.x, from.y], 0.5) && near(p[3], [to.x, to.y], 0.5),
			'connector ends are not on the anchors: ' + JSON.stringify(p));
		const out = sign * (p[1][axis] - [from.x, from.y][axis]);
		assert.ok(out >= ELBOW, 'no elbow: route leaves the anchor by ' + out.toFixed(2) + 'mm (straight line through the anchors); ' +
			'ext=(' + sp.xfrm.extX + ',' + sp.xfrm.extY + ') adj=' + JSON.stringify(sp.geometry.adj));
		assert.ok(sp.xfrm.extX > 0 && sp.xfrm.extY > 0, 'zero extent: handle drags (fractions of it) cannot move the elbow');
	});
}

elbow('top anchors of side-by-side shapes: elbow goes up over them',
	anchor(A, 35, 30, 'N'), anchor(B, 95, 30, 'N'), 1, -1);
elbow('bottom anchors of side-by-side shapes: elbow goes down under them',
	anchor(A, 35, 50, 'S'), anchor(B, 95, 50, 'S'), 1, +1);
elbow('left anchors of stacked shapes: elbow goes out to the left',
	anchor([20, 10, 50, 30], 20, 20, 'W'), anchor([20, 60, 50, 80], 20, 70, 'W'), 0, -1);

// CnxShape.recalculate passes `this.pen && this.pen.w`, which is undefined for a default-width line
elbow('top anchors with no line width given: still an elbow, finite extent',
	anchor(A, 35, 30, 'N'), anchor(B, 95, 30, 'N'), 1, -1, undefined);

check('right anchor to left anchor at the same height: still a perfectly straight line', () => {
	const sp = lib.fCalculateSpPr(anchor(A, 50, 40, 'E'), anchor(B, 80, 40, 'W'), 'bentConnector3', 12700);
	assert.strictEqual(sp.xfrm.extY, 0);
	routePoints(sp).forEach(pt => assert.ok(Math.abs(pt[1] - 40) < 1e-9, 'straight connector got a step'));
});

if (failures.length) {
	console.log('FAIL #2428: ' + failures.length + ' check(s) failed' + (process.env.BASELINE ? ' (expected on BASELINE)' : ''));
	process.exit(1);
}
console.log('PASS #2428: connectors between aligned anchors are routed as elbows' + (process.env.BASELINE ? ' (BASELINE?!)' : ''));

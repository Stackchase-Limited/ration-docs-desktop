/*
 * RD-0020 - one animation edit on a slide threw away the slide's video/audio
 * playback settings.
 *
 * PowerPoint keeps a media object's settings in the slide timing root, next to
 * the animation sequences: <p:video fullScrn="1"><p:cMediaNode vol="50000"
 * mute="1" showWhenStopped="0"><p:cTn repeatCount="indefinite" fill="remove">
 * (volume, mute, play full screen, hide while not playing, loop, rewind).
 * CTiming.buildTree (slide/Editor/Format/Timing.js), which every animation edit
 * goes through, made a fresh root and refilled it with the main and
 * interactive sequences only - the p:video/p:audio nodes were never put back.
 *
 * Measured in the real slide editor (headless Chromium, .rd-work/wt/eb-tmp/h/
 * rt.js, a pptx with a muted, looping, hidden-when-stopped, full-screen video
 * and a "Start: Automatically" effect): open, add a Fade entrance to the video,
 * save, x2t to pptx. Before: the slide's <p:video> node is gone (no mute, loop,
 * hide, full screen, volume). After: it is written after the sequences with all
 * its attributes, cTn ids unique.
 *
 * This extracts the REAL CTiming.prototype.buildTree and runs it on a stub
 * timing whose root holds a main sequence, a p:video and a p:audio media node
 * (and one media node whose drawing was deleted).
 * NOT claimed: the PPTY/XML writing of the nodes (unchanged, round trip checked
 * by hand as above); undo of the edit (history of the copied nodes is the
 * ordinary createDuplicate/pushToChildTnLst path, not driven here).
 *
 * RD_REPO=<sdkjs checkout> overrides the tree. BASELINE=1 reads the sources at
 * BASE_REF (the parent of the fix) with git show, and must fail there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// the parent of the fix; the integrator re-pins it after cherry-picking
const BASE_REF = process.env.BASE_REF || '8cdef5ad4c^';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
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
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const timing = src('slide/Editor/Format/Timing.js');

/* --- stubs: time nodes, a root container, a timing --- */
function Node(kind, target) { this.kind = kind; this.target = target; this.children = []; }
Node.prototype.isVideo = function () { return this.kind === 'video'; };
Node.prototype.isAudio = function () { return this.kind === 'audio'; };
Object.defineProperty(Node.prototype, 'cMediaNode', {
	get() { return (this.kind === 'video' || this.kind === 'audio') ? { getTargetObjectId: () => this.target } : null; },
});
Node.prototype.createDuplicate = function () { const n = new Node(this.kind, this.target); n.copyOf = this; return n; };
Node.prototype.getChildrenTimeNodes = function () { return this.children.slice(); };
Node.prototype.clearChildTnLst = function () { this.children = []; };
Node.prototype.pushToChildTnLst = function (n) { this.children.push(n); };
Node.prototype.addToChildTnLst = function (i, n) { this.children.splice(i, 0, n); };
Node.prototype.addEffectToTheEndOfSeq = function (e) { this.children.push(e); };
Object.defineProperty(Node.prototype, 'cTn', { get() { return null; } });

function Timing() { this.root = null; this.renumbered = false; }
Timing.prototype.getTimingRootNode = function () { return this.root; };
Timing.prototype.createTimingRoot = function () { this.root = new Node('root'); };
Timing.prototype.checkTimeRoot = function () { if (!this.root) this.createTimingRoot(); return this.root; };
Timing.prototype.checkMainSequence = function () {
	let seq = this.root.children.find(n => n.kind === 'mainSeq');
	if (!seq) { seq = new Node('mainSeq'); this.root.addToChildTnLst(0, seq); }
	return seq;
};
Timing.prototype.checkInteractiveSequence = function (id) {
	let seq = this.root.children.find(n => n.kind === 'interactiveSeq' && n.target === id);
	if (!seq) { seq = new Node('interactiveSeq', id); this.root.pushToChildTnLst(seq); }
	return seq;
};
Timing.prototype.updateNodesIDs = function () { this.renumbered = this.root.children.map(n => n.kind); };
new Function('CTiming', extract(timing, 'CTiming.prototype.buildTree = function') + ';')(Timing);

function slide() {
	const t = new Timing();
	t.createTimingRoot();
	const main = new Node('mainSeq'), oldEffect = new Node('effect', 'sp1');
	main.children.push(oldEffect);
	t.root.children.push(main, new Node('video', 'video1'), new Node('audio', 'audio1'), new Node('video', null));
	return t;
}
const kinds = t => t.root.children.map(n => n.kind + (n.target ? ':' + n.target : ''));

let failures = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failures++; console.log('FAIL ' + label + '\n     ' + e.message); }
}

check('adding an effect keeps the slide\'s p:video and p:audio media nodes', () => {
	const t = slide();
	const fade = new Node('effect', 'video1');
	t.buildTree([[null, t.root.children[0].children[0], fade]]);
	assert.deepStrictEqual(kinds(t), ['mainSeq', 'video:video1', 'audio:audio1'], JSON.stringify(kinds(t)));
});
check('the kept nodes are copies of the old ones (old root left untouched), placed before ids are renumbered', () => {
	const t = slide();
	const oldVideo = t.root.children[1];
	t.buildTree([[null, new Node('effect', 'sp1')]]);
	const video = t.root.children.find(n => n.kind === 'video');
	assert.ok(video && video.copyOf === oldVideo, 'not a copy of the old p:video');
	assert.deepStrictEqual(t.renumbered, ['mainSeq', 'video', 'audio']);
});
check('removing the last effect keeps the media nodes too', () => {
	const t = slide();
	t.buildTree([[null]]);
	assert.deepStrictEqual(kinds(t), ['video:video1', 'audio:audio1'], JSON.stringify(kinds(t)));
});
check('a media node whose drawing is gone (no target) is not carried over', () => {
	const t = slide();
	t.buildTree([[null, new Node('effect', 'sp1')]]);
	assert.ok(!t.root.children.some(n => n.kind === 'video' && !n.target), JSON.stringify(kinds(t)));
});
check('interactive sequences are still rebuilt as before, media nodes after them', () => {
	const t = slide();
	t.buildTree([[null, new Node('effect', 'sp1')], ['video1', new Node('effect', 'video1')]]);
	assert.deepStrictEqual(kinds(t), ['mainSeq', 'interactiveSeq:video1', 'video:video1', 'audio:audio1'], JSON.stringify(kinds(t)));
});

console.log(process.env.BASELINE ? `baseline sources (${BASE_REF})` : 'fixed sources');
if (failures) { console.log(`${failures} FAILED`); process.exit(1); }
console.log('ALL PASS');

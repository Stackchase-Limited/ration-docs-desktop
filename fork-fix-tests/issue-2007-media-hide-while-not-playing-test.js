/*
 * #2007 - Presentation: hide a video while it is not playing.
 *
 * PowerPoint's Playback > "Hide While Not Playing" is <p:cMediaNode
 * showWhenStopped="0"> in the slide timing. It survived open/save (x2t and the
 * sdkjs model: a python-pptx deck through pptx -> Editor.bin -> sdkjs ->
 * Editor.bin -> pptx keeps it), but the slide show drew the video's poster frame
 * regardless, and nothing in the editor could set it.
 *
 * Now (sdkjs slide/Editor/Format/Timing.js):
 * - CAnimationDrawer.isMediaHiddenWhileStopped / drawObject: in a slide show a
 *   media drawing whose media node (slide, layout or master timing) says
 *   showWhenStopped="0" is not drawn unless its player is open (the selected
 *   video; the desktop draws the playing video over the slide). The editor and
 *   its animation preview are unchanged.
 * - getMediaSettings / setMediaSettings gain "HideWhileNotPlaying" (api
 *   asc_get/setMediaSettings, from #2003), and web-apps has the checkbox.
 *
 * Measured in the real slide editor (headless Chromium, .rd-work/wt/eb-tmp/h/
 * show.js: StartDemonstration on a deck whose video has showWhenStopped="0",
 * logging what the animation drawer draws): before, the video was drawn in
 * every frame; after, not at all until the video is selected, then drawn.
 *
 * This extracts the REAL functions above and runs them against stub drawings,
 * timings and api. NOT claimed: the poster after playback ends (the desktop
 * keeps the player open, showing its last frame, until the slide changes); a
 * hidden video can still be clicked where it is, which starts it, as in
 * PowerPoint's "When Clicked On"; the web-apps panel rendered (GUI check).
 *
 * RD_REPO=<sdkjs checkout>, RD_WEBAPPS=<web-apps checkout> override the trees.
 * BASELINE=1 reads the sources at BASE_REF / WEBAPPS_BASE_REF (the parents of
 * the fixes) with git show, and must fail there.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.resolve(__dirname, '..', 'web-apps');
// the parents of the fixes; the integrator re-pins them after cherry-picking
const BASE_REF = process.env.BASE_REF || '7eef14211f^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '93947f7455^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
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
function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return '';
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const timing = src(SDKJS, BASE_REF, 'slide/Editor/Format/Timing.js');

/* --- stubs --- */
const api = { show: true, mediaData: null, isSlideShow() { return this.show; }, getMediaData() { return this.mediaData; } };
const Asc = { editor: api };
function Drawing(id, media) { this.id = id; this.media = media; this.selected = false; }
Drawing.prototype.Get_Id = function () { return this.id; };
Drawing.prototype.GetId = Drawing.prototype.Get_Id;
Drawing.prototype.getMediaFileName = function () { return this.media ? this.id + '.mp4' : null; };
Drawing.prototype.isVideo = function () { return true; };
function mediaNode(spid, showWhenStopped) {
	return { isVideo: () => true, isAudio: () => false,
		cMediaNode: { showWhenStopped, mute: null, getTargetObjectId: () => spid, setShowWhenStopped(v) { this.showWhenStopped = v; }, setMute(v) { this.mute = v; } } };
}
function CTiming(nodes) { this.nodes = nodes; }
CTiming.prototype.getTimingRootNode = function () {
	const nodes = this.nodes;
	return { traverseTimeNodes(cb) { for (const n of nodes) if (cb(n)) return true; return false; } };
};
CTiming.prototype.checkMediaNode = function (d) {
	let n = this.getMediaNode(d.Get_Id());
	if (!n) { n = mediaNode(d.Get_Id(), null); this.nodes.push(n); }
	return n;
};
function CAnimationDrawer(timings) { this.player = { timings }; this.drawn = []; this.docStructureByDrawing = {}; }
CAnimationDrawer.prototype.getSandwich = function () { return null; };
CAnimationDrawer.prototype.getAllAnimationDrawingObjects = function (d) { return [d]; };
CAnimationDrawer.prototype.isDrawingVisible = function () { return true; };
CAnimationDrawer.prototype.drawDrawingWithoutAnimation = function (g, d) { this.drawn.push(d.id); };

new Function('CTiming', 'CAnimationDrawer', 'Asc', [
	extract(timing, 'CTiming.prototype.getMediaNode = function', true),
	extract(timing, 'function getMediaSettings(', true),
	extract(timing, 'CTiming.prototype.getMediaSettings = function', true),
	extract(timing, 'CTiming.prototype.setMediaSettings = function', true),
	extract(timing, 'CAnimationDrawer.prototype.isMediaHiddenWhileStopped = function', true),
	extract(timing, 'CAnimationDrawer.prototype.drawObject = function'),
].join(';\n') + ';')(CTiming, CAnimationDrawer, Asc);

const graphics = { m_oCoordTransform: { sx: 1 } };
function drawn(drawer, d) { drawer.drawn.length = 0; drawer.drawObject(d, graphics); return drawer.drawn.length > 0; }

let failures = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failures++; console.log('FAIL ' + label + '\n     ' + e.message); }
}

const hidden = new Drawing('v-hidden', true), plain = new Drawing('v-plain', true), shape = new Drawing('sp', false), onLayout = new Drawing('v-layout', true);
const slideTiming = new CTiming([mediaNode('v-hidden', false), mediaNode('v-plain', null)]);
const layoutTiming = new CTiming([mediaNode('v-layout', false)]);
const drawer = new CAnimationDrawer([slideTiming, layoutTiming]);

check('slide show: a video with showWhenStopped="0" is not drawn while its player is closed', () => {
	api.show = true; api.mediaData = null;
	assert.strictEqual(drawn(drawer, hidden), false);
});
check('slide show: ... and is drawn once it is selected (its player is open)', () => {
	hidden.selected = true; api.mediaData = { getDrawing: () => hidden };
	const r = drawn(drawer, hidden);
	hidden.selected = false; api.mediaData = null;
	assert.strictEqual(r, true);
});
check('slide show: hovering it (player data, not selected) does not show it', () => {
	api.mediaData = { getDrawing: () => hidden };
	const r = drawn(drawer, hidden);
	api.mediaData = null;
	assert.strictEqual(r, false);
});
check('slide show: the setting on a layout\'s timing counts too', () => {
	assert.strictEqual(drawn(drawer, onLayout), false);
});
check('slide show: a video without the setting and a shape are drawn as before', () => {
	assert.strictEqual(drawn(drawer, plain), true);
	assert.strictEqual(drawn(drawer, shape), true);
});
check('editor / animation preview (no slide show): the hidden video is drawn', () => {
	api.show = false;
	const r = drawn(drawer, hidden);
	api.show = true;
	assert.strictEqual(r, true);
});
check('settings: HideWhileNotPlaying is read from and written to showWhenStopped', () => {
	assert.ok(typeof slideTiming.getMediaSettings === 'function', 'no getMediaSettings');
	assert.strictEqual(slideTiming.getMediaSettings('v-hidden')['HideWhileNotPlaying'], true);
	assert.strictEqual(slideTiming.getMediaSettings('v-plain')['HideWhileNotPlaying'], false);
	slideTiming.setMediaSettings(plain, { 'HideWhileNotPlaying': true });
	assert.strictEqual(slideTiming.getMediaNode('v-plain').cMediaNode.showWhenStopped, false);
	slideTiming.setMediaSettings(plain, { 'HideWhileNotPlaying': false });
	assert.strictEqual(slideTiming.getMediaNode('v-plain').cMediaNode.showWhenStopped, true);
	const fresh = new Drawing('v-new', true);
	slideTiming.setMediaSettings(fresh, { 'HideWhileNotPlaying': true });
	assert.strictEqual(slideTiming.getMediaNode('v-new').cMediaNode.showWhenStopped, false);
});
check('web-apps: the Playback section has "Hide while not playing" wired to HideWhileNotPlaying', () => {
	const view = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/presentationeditor/main/app/view/ImageSettings.js');
	const tmpl = src(WEBAPPS, WEBAPPS_BASE_REF, 'apps/presentationeditor/main/app/template/ImageSettings.template');
	assert.ok(/id="image-checkbox-hide-stopped"/.test(tmpl), 'no checkbox in the template');
	assert.ok(/onMediaSettingChange, this, 'HideWhileNotPlaying'/.test(view), 'checkbox not wired');
	assert.ok(/chHideStopped\.setValue\(!!media\['HideWhileNotPlaying'\]/.test(view), 'checkbox not filled');
});

console.log(process.env.BASELINE ? `baseline sources (${BASE_REF}, ${WEBAPPS_BASE_REF})` : 'fixed sources');
if (failures) { console.log(`${failures} FAILED`); process.exit(1); }
console.log('ALL PASS');

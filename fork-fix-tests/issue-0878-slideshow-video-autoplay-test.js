/*
 * #878 - a video in a slide show showed only its first frame: a video set to
 * start "Automatically" or "On Click" (Playback > Start in PowerPoint, the
 * default for an inserted video) never played.
 *
 * PowerPoint writes that setting as a mediacall effect in the slide's main
 * sequence, <p:cmd type="call" cmd="playFrom(0.0)">. When the timeline reached
 * it, CCmd.setState (Timing.js) passed the string to the desktop player as is:
 * - getPlayerData (apiBase.js) meant to turn "playFrom(...)" into "play" but
 *   tested `sCmd.startsWith("playFrom") === 0` - a boolean is never 0 - so the
 *   AppKit and Qt players got Cmd "playFrom(0.0)", which neither knows;
 * - the desktop opens a player only for a selected video (showMediaControl with
 *   IsSelected - what a click on the video does) and the timeline never opened
 *   one, so even a "play" reached no player.
 * And a window resize during the show (the desktop goes full screen right
 * after the show starts) re-ran StartSlide, whose first step closed any open
 * player - stopping a video that had just started.
 *
 * Measured in the real slide editor (headless Chromium, .rd-work/wt/cx-tmp/h/
 * p878.js, a pptx with one "Automatically" and one "On Click" video): before,
 * the player got ["playFrom(0.0) sel=false"] then "hideMediaControl" on a
 * resize; after, ["showMediaControl sel=true", "seek From=0", "play"] and a
 * resize sends nothing that closes it.
 *
 * This extracts the real CCmd.prototype.setState (Timing.js), the real
 * getPlayerData/callMediaPlayerCommand (apiBase.js), callTimelineMediaCommand
 * (slide/api.js, fixed tree only) and the demonstration manager's StartSlide
 * and Resize (Transitions.js), and drives them with stubs for the drawing,
 * the slide's selection and AscDesktopEditor.CallMediaPlayerCommand.
 * NOT claimed: that the native players then play (they handle "play"/"seek"
 * since #1943's tests); the timeline parsing of p:cmd; the GUI full screen
 * switch actually resizing after the first effect (it needs the real app).
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
// the parent of the first #878 commit; the integrator re-pins it after cherry-picking
const BASE_REF = process.env.BASE_REF || '78aab3b128^';

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
function extract(text, marker, optional) {
	const at = text.indexOf(marker);
	if (at === -1 && optional) return null;
	assert.notStrictEqual(at, -1, marker + ' not found');
	return block(text, at);
}

const apiBase = src('common/apiBase.js');
const timing = src('slide/Editor/Format/Timing.js');
const slideApi = src('slide/api.js');
const transitions = src('slide/Drawing/Transitions.js');

/* --- stubs: one slide with two videos, the desktop player, the slide's selection --- */
const sent = [];
global.window = {
	AscDesktopEditor: { CallMediaPlayerCommand(d) { sent.push(d); } },
};
global.window['AscDesktopEditor'] = global.window.AscDesktopEditor;
const AscFormat = {
	isRealNumber: v => typeof v === 'number' && !isNaN(v),
	IsEqualObjects: (a, b) => JSON.stringify(a) === JSON.stringify(b),
};
const c_oEditorId = { Word: 0, Spreadsheet: 1, Presentation: 2 };

function MediaData(drawing) { this.drawing = drawing; }
MediaData.prototype.getDrawing = function () { return this.drawing; };
MediaData.prototype.getName = function () { return this.drawing.file; };
MediaData.prototype.isValid = function () { return true; };
function Video(file) { this.file = file; this.selected = false; }
Video.prototype.getMediaData = function () { return new MediaData(this); };
const video1 = new Video('media1.mp4'), video2 = new Video('media2.mp4');

const manager = { Mode: true, SlideNum: 0 };
const slide = {
	graphicObjects: {
		resetSelection() { video1.selected = video2.selected = false; api.mediaData = null; },
		// what a click on a video does: CommonController.selectObject -> checkShowMediaControlOnSelect
		selectObject(sp) { sp.selected = true; api.callMediaPlayerCommand('showMediaControl', sp.getMediaData()); },
	},
};
const api = {
	editorId: c_oEditorId.Presentation,
	mediaData: null,
	slideShow: true,
	isSlideShow() { return this.slideShow; },
	getMediaData() { return this.mediaData; },
	WordControl: {
		DemonstrationManager: manager,
		m_oLogicDocument: { GetSlide: () => slide },
		GetMediaPlayerData(md) {
			return { Cmd: null, MediaFile: md.getName(), IsSelected: md.getDrawing().selected, From: 0 };
		},
	},
};
for (const name of ['getPlayerData', 'callMediaPlayerCommand', 'hideMediaControl', 'onUpdateMediaPlayer']) {
	api[name] = new Function('window', 'AscFormat', 'c_oEditorId',
		'return ' + extract(apiBase, `baseEditorsApi.prototype.${name} = function`).replace(/^[^=]*=\s*/, ''))(global.window, AscFormat, c_oEditorId);
}
const timelineSrc = extract(slideApi, 'asc_docs_api.prototype.callTimelineMediaCommand = function', true);
if (timelineSrc)
	api.callTimelineMediaCommand = new Function('AscFormat', 'return ' + timelineSrc.replace(/^[^=]*=\s*/, ''))(AscFormat);

/* the real CCmd.setState on a stub time node targeting a video */
const TIME_NODE_STATE_ACTIVE = 1, TLCommandTypeCall = 0;
function CTimeNodeBase() {}
CTimeNodeBase.prototype.setState = function () {};
function CCmd(cmd, sp) { this.type = TLCommandTypeCall; this.cmd = cmd; this.sp = sp; }
CCmd.prototype.getMediaData = function () { return this.sp.getMediaData(); };
new Function('CCmd', 'CTimeNodeBase', 'TIME_NODE_STATE_ACTIVE', 'TLCommandTypeCall', 'Asc',
	extract(timing, 'CCmd.prototype.setState = function') + ';')(CCmd, CTimeNodeBase, TIME_NODE_STATE_ACTIVE, TLCommandTypeCall, { editor: api });

const fire = (cmd, sp) => { sent.length = 0; new CCmd(cmd, sp).setState(TIME_NODE_STATE_ACTIVE); return sent.map(d => `${d.Cmd} ${d.MediaFile || ''} sel=${d.IsSelected} From=${d.From}`.replace('  ', ' ')); };

let failures = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failures++; console.log('FAIL ' + label + '\n     ' + e.message); }
}

/* 1. "Start: Automatically"/"On Click" in a slide show: the player is opened, put at the position, played */
check('slide show: timeline playFrom(0.0) opens the video\'s player, seeks to 0 and plays', () => {
	const got = fire('playFrom(0.0)', video1);
	assert.deepStrictEqual(got, ['showMediaControl media1.mp4 sel=true From=0', 'seek media1.mp4 sel=true From=0', 'play media1.mp4 sel=true From=0'], JSON.stringify(got));
});
check('slide show: playFrom(2.5) of another video switches the player to it and seeks to 2500 ms', () => {
	const got = fire('playFrom(2.5)', video2);
	assert.deepStrictEqual(got, ['showMediaControl media2.mp4 sel=true From=0', 'seek media2.mp4 sel=true From=2500', 'play media2.mp4 sel=true From=0'], JSON.stringify(got));
});
check('no Cmd the players do not know ("playFrom(...)") is ever sent', () => {
	api.mediaData = null; video1.selected = video2.selected = false;
	const got = fire('playFrom(0.0)', video1);
	assert.ok(got.every(s => !/playFrom/.test(s)), JSON.stringify(got));
});
check('slide show: a timeline pause goes to the open player as before', () => {
	const got = fire('pause', video1);
	assert.deepStrictEqual(got, ['pause media1.mp4 sel=true From=0'], JSON.stringify(got));
});
check('editor (animation preview, no slide show): play does not select anything, only maps to "play"', () => {
	api.slideShow = false; api.mediaData = null; video1.selected = video2.selected = false;
	const got = fire('playFrom(0.0)', video1);
	api.slideShow = true;
	assert.deepStrictEqual(got, ['play media1.mp4 sel=false From=0'], JSON.stringify(got));
	assert.strictEqual(video1.selected, false);
});

/* 2. a resize of the show (the desktop's full screen switch) keeps the open player */
const mgrSrc = ['StartSlide', 'Resize'].map(n => extract(transitions, `this.${n} = function`)).join(';\n');
function Manager() {
	const oThis = this;
	this.Mode = true; this.SlideNum = 0; this.DivWidth = 800; this.DivHeight = 600;
	this.DemonstrationDiv = { clientWidth: 1440, clientHeight: 900 };
	this.Canvas = { style: {} }; this.Overlay = null; this.DivEndPresentation = null; this.SlideIndexes = [0, 0];
	this.Transition = { IsPlaying: () => false, CalculateRectDemonstration() {} };
	this.HtmlPage = { m_oApi: api, m_oDrawingDocument: { m_sLockedCursorType: '' }, m_oLogicDocument: { Slides: [{ transition: { TransitionType: 0, TransitionDuration: 0 } }] } };
	this.GetSlidesCount = () => 1;
	this.StopTransition = () => {};
	this.StartAnimation = () => {};
	this.OnPaintSlide = () => {};
	new Function('oThis', 'AscCommon', 'c_oAscSlideTransitionTypes', mgrSrc).call(this, oThis,
		{ AscBrowser: { convertToRetinaValue: v => v } }, { None: 0 });
}
check('a resize during the show does not close the open video player (it is moved: "update")', () => {
	api.mediaData = null; video1.selected = video2.selected = false;
	fire('playFrom(0.0)', video1);
	sent.length = 0;
	new Manager().Resize(true);
	const got = sent.map(d => d.Cmd);
	assert.ok(!got.includes('hideMediaControl'), 'player closed: ' + JSON.stringify(got));
	assert.deepStrictEqual(got, ['update'], JSON.stringify(got));
});
check('moving to a slide still closes the player', () => {
	sent.length = 0;
	new Manager().StartSlide(true, false);
	assert.deepStrictEqual(sent.map(d => d.Cmd), ['hideMediaControl']);
});

console.log(process.env.BASELINE ? `baseline sources (${BASE_REF})` : 'fixed sources');
if (failures) { console.log(`${failures} FAILED`); process.exit(1); }
console.log('ALL PASS');

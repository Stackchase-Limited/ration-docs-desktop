/*
 * #1885 - "Hyperlink Export on PDF": a presentation exported to PDF had no clickable links where
 * the slides had hyperlinked shapes or pictures (the reporter's PowerPoint deck). Only hyperlinks
 * on TEXT became PDF links: Paragraph drawing calls AddHyperlink/AddLink on renderers that write
 * links (CDocumentRenderer in common/Drawings/Metafile.js, used by every PDF export and by x2t).
 * A click hyperlink on an object - cNvPr.hlinkClick, set by Insert > Hyperlink on a selected
 * shape/picture or read from PowerPoint - is kept and works in the slide show, but Slide.draw
 * (sdkjs slide/Editor/Format/Slide.js) never told the renderer about it.
 *
 * Fix: Slide.draw passes each drawn object to Slide.drawHyperlinkAreas when the renderer has
 * AddHyperlink/AddLink: the object's bounds become a URI link (web/mail address) or a link to a
 * page (first/last/next/previous slide, slide N), recursing into groups; actions with no PDF
 * meaning (open a file, custom show, macro) and hidden objects are skipped.
 *
 * This extracts the REAL Slide.prototype.draw and Slide.prototype.drawHyperlinkAreas and the REAL
 * AscCommon.IsLinkPPAction (common/editorscommon.js) by brace matching and runs them on stub
 * slides/shapes with a recording renderer, plus a screen renderer without AddHyperlink.
 * End to end (not part of this test, see the commit): x2t with the built slide sdk-all on the
 * sample deck with 137 linked shapes gives URI link annotations where it gave none.
 *
 *   RD_REPO=<sdkjs> (default ../sdkjs). BASELINE=1 reads sources at BASE_REF -> must FAIL.
 * NOT claimed: text hyperlinks (unchanged), spreadsheet cell hyperlinks (still not exported -
 * cell/ PDF printing never emits links), rotated objects get their axis-aligned bounds.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const SDKJS = process.env.RD_REPO || path.resolve(__dirname, '..', 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'd54317276d^';
function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', SDKJS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(SDKJS, rel), 'utf8');
}
function matched(text, start) {
	let depth = 0;
	for (let i = text.indexOf('{', start); i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(text.indexOf('{', start), i + 1);
	}
	throw new Error('unbalanced');
}
function fnAt(text, marker) {
	const at = text.indexOf(marker);
	if (at < 0) return null;
	const p = text.indexOf('function', at);
	return text.slice(p, text.indexOf(')', p) + 1) + matched(text, p);
}

const slideJs = src('slide/Editor/Format/Slide.js');
const common = src('common/editorscommon.js');
const AscCommon = {
	IsLinkPPAction: new Function('return ' + fnAt(common, 'function IsLinkPPAction'))(),
	IsHiddenObj: (o) => !!o.hidden,
	CMatrix: function () {},
	UserInfoParser: { canViewComment: () => true },
};
const AscFormat = { isRealNumber: (n) => typeof n === 'number' && !isNaN(n) };
const Asc = { editor: { private_GetLogicDocument: () => ({ GetSlidesCount: () => 5 }) } };
const make = (marker) => { const f = fnAt(slideJs, marker); return f && new Function('AscCommon', 'AscFormat', 'Asc', 'return ' + f)(AscCommon, AscFormat, Asc); };
const draw = make('Slide.prototype.draw = function');
const areas = make('Slide.prototype.drawHyperlinkAreas = function');

function shape(link, b, extra) {
	return Object.assign({
		bounds: { l: b[0], t: b[1], r: b[2], b: b[3] },
		getCNvProps: () => (link === undefined ? {} : { hlinkClick: { id: link, tooltip: null } }),
		isGroupObject: () => false,
		draw() {},
	}, extra || {});
}
function slide(num, spTree) {
	const s = {
		num, cSld: { spTree }, timing: null, slideComments: null,
		graphicObjects: { isSlideShow: () => false, canEdit: () => true },
		collaborativeMarks: { Init_Drawing() {}, Check: () => null },
		drawBgMasterAndLayout() {}, drawViewPrMarks() {},
	};
	if (areas) s.drawHyperlinkAreas = areas;
	return s;
}
function pdfRenderer() {
	const out = [];
	return {
		out, isBoundsChecker: () => false,
		AddHyperlink: (x, y, w, h, url) => out.push(`uri ${url} @${x},${y},${w},${h}`),
		AddLink: (x, y, w, h, dx, dy, page) => out.push(`page ${page} @${x},${y},${w},${h}`),
	};
}

let failures = 0;
function check(what, got, want) {
	const ok = JSON.stringify(got) === JSON.stringify(want);
	failures += !ok;
	console.log(`  ${what.padEnd(48)} ${ok ? 'ok' : 'FAILED\n     got  ' + JSON.stringify(got) + '\n     want ' + JSON.stringify(want)}`);
}

console.log('sdkjs ' + (process.env.BASELINE ? '@ ' + BASE_REF : SDKJS));
const group = shape(undefined, [0, 0, 50, 50], {
	isGroupObject: () => true,
	spTree: [shape('mailto:a@b.c', [1, 2, 3, 4]), shape('ppaction://hlinksldjumpslide3', [5, 5, 6, 6])],
});
const sp = [
	shape('https://example.com/x', [10, 20, 110, 70]),
	shape('ppaction://hlinkshowjump?jump=nextslide', [0, 0, 10, 10]),
	shape('ppaction://hlinkshowjump?jump=previousslide', [0, 0, 10, 10]),
	shape('ppaction://hlinkshowjump?jump=lastslide', [0, 0, 10, 10]),
	shape('ppaction://hlinkfile', [0, 0, 10, 10]),
	shape('https://hidden.example', [0, 0, 10, 10], { hidden: true }),
	shape('https://flat.example', [0, 0, 10, 0]),
	shape(undefined, [0, 0, 10, 10]),
	group,
];
let r = pdfRenderer();
draw.call(slide(1, sp), r);
check('PDF export of slide 2 (index 1)', r.out, [
	'uri https://example.com/x @10,20,100,50',
	'page 2 @0,0,10,10',
	'page 0 @0,0,10,10',
	'page 4 @0,0,10,10',
	'uri mailto:a@b.c @1,2,2,2',
	'page 3 @5,5,1,1',
]);
r = pdfRenderer();
draw.call(slide(4, [shape('ppaction://hlinkshowjump?jump=nextslide', [0, 0, 10, 10])]), r);
check('"next slide" on the last slide -> no link', r.out, []);
const screen = { isBoundsChecker: () => false };
let threw = null;
try { draw.call(slide(0, sp), screen); } catch (e) { threw = String(e); }
check('screen renderer (no AddHyperlink): draws, no error', threw, null);

console.log(failures ? '\nFAILED' : '\nok - hyperlinked slide objects become PDF links');
process.exit(failures ? 1 : 0);

/*
 * Upstream c0758e150e (ONLYOFFICE bug 81775, 9.4.1 hotfix) - when a
 * background image finished loading while fonts were still loading, the
 * editors redrew at once (asyncImageEndLoadedBackground in word/api.js,
 * slide/api.js, cell/api.js; the layout thumbnails in slide/Drawing/HtmlPage.js),
 * drawing text whose fonts were not loaded yet. Fix: those callbacks do nothing
 * while FontLoader.isFontLoadInProgress(); the redraw after the font load draws
 * the images.
 *
 * What runs: the WHOLE word, slide and cell engines headless in docbuilder
 * (shared harness ../lib/sdkjs-docbuilder.js), one run each. The real
 * asyncImageEndLoadedBackground is called with the font loader reporting a
 * load in progress, then not; the redraw it would trigger
 * (DrawingDocument.CheckRasterImageOnScreen for word/slide,
 * objectRender.showDrawingObjects for cell) is replaced by a counter.
 * Claimed: no redraw while fonts load; one redraw otherwise (control).
 * NOT claimed: the crash/garbage of bug 81775 itself (needs the browser's
 * async font and image loading); the HtmlPage layout-thumbnail hunk.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const STUB = {
	word: `var dd = editor.WordControl.m_oDrawingDocument; dd.CheckRasterImageOnScreen = function () { calls++; }; dd.LastDrawingUrl = null;`,
	slide: `editor.WordControl.m_oDrawingDocument.CheckRasterImageOnScreen = function () { calls++; };`,
	cell: `var wsv = Asc.editor.wb.getWorksheet();
wsv.objectRender.drawingArea = wsv.objectRender.drawingArea || {};
wsv.objectRender.drawingArea.frozenPlaces = [1];
wsv.objectRender.showDrawingObjects = function () { calls++; };`,
};
const ck = h.checker();
for (const editor of ['word', 'slide', 'cell']) {
	const r = h.run({
		editor, baseRef: BASE_REF, tag: 'imgfont-' + editor, script: (w, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var api = ${editor === 'cell' ? 'Asc.editor' : 'editor'};
var calls = 0, loading = true;
try {
	${STUB[editor]}
	api.FontLoader.isFontLoadInProgress = function () { return loading; };
	api.asyncImageEndLoadedBackground({ src: 'image.png' });
	out('loading', calls);
	calls = 0; loading = false;
	api.asyncImageEndLoadedBackground({ src: 'image.png' });
	out('loaded', calls);
} catch (e) { out('loading', 'exception: ' + e); }
builder.CloseFile();
` });
	ck.check(`${editor}: no redraw while fonts load`, r.results.get('loading') === 0, `${r.results.get('loading')} redraws`);
	ck.check(`${editor}: control, redraw once fonts are loaded`, r.results.get('loaded') === 1, `${r.results.get('loaded')} redraws`);
}
ck.finish();

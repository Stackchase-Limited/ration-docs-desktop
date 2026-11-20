/*
 * Upstream 9717a00f4f (ONLYOFFICE bug 81780, 9.4.1 hotfix) - with the notes
 * pane focused, a presentation with no slides threw in
 * CPresentation.IsFocusOnNotes (slide/Editor/Format/Presentation.js): it read
 * GetCurrentSlide().notes and the current slide is null. Many editor actions
 * ask IsFocusOnNotes, so the exception drops the editor to view-only. Fix:
 * false when there is no current slide.
 *
 * What runs: the WHOLE presentation engine headless in docbuilder (shared
 * harness ../lib/sdkjs-docbuilder.js). The new presentation's slides are all
 * removed with the builder API, FocusOnNotes is set (as clicking the notes
 * pane does) and the real IsFocusOnNotes is called; then again with one slide
 * (control).
 * NOT claimed: the UI steps of bug 81780.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const r = h.run({
	editor: 'slide', baseRef: BASE_REF, tag: 'notesfocus', script: (w, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var pres = Api.GetPresentation();
var logic = editor.WordControl.m_oLogicDocument;
function ask(tag) {
	try { logic.FocusOnNotes = true; out(tag, [logic.Slides.length, String(logic.IsFocusOnNotes())]); }
	catch (e) { out(tag, [logic.Slides.length, 'exception: ' + e]); }
}
ask('with a slide');
while (pres.GetSlidesCount() > 0) pres.GetSlideByIndex(0).Delete();
ask('no slides');
builder.CloseFile();
` });

const ck = h.checker();
const a = r.results.get('with a slide'), b = r.results.get('no slides');
ck.check('control: one slide, notes focused', !!a && a[0] >= 1 && a[1] === 'true', JSON.stringify(a));
ck.check('no slides, notes focused: false, no exception', !!b && b[0] === 0 && b[1] === 'false', JSON.stringify(b));
ck.finish(r);

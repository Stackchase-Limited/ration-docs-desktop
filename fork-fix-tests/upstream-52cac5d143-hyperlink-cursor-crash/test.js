/*
 * Upstream 52cac5d143 (ONLYOFFICE bug 81778, 9.4.1 hotfix) - correcting the
 * cursor position inside a hyperlink (or another paragraph-like container)
 * threw when the container was empty or none of its elements can hold the
 * cursor; the exception drops the document editor to view-only.
 *
 * CParagraphContentWithParagraphLikeContent.CorrectContentPos
 * (word/Editor/ParagraphContentBase.js) indexed Content[-1] for an empty
 * container and stepped past the last element when no element was cursor
 * placeable. Fix: return for an empty container, stay inside the content, and
 * fall back to position 0.
 *
 * What runs: the WHOLE document engine headless in docbuilder (shared harness
 * ../lib/sdkjs-docbuilder.js). Real ParaHyperlink objects are put into the
 * first paragraph of a new document - one empty, one holding only a comment
 * mark (not cursor placeable) - and their real CorrectContentPos is called.
 * Claimed: no exception, position 0.
 * NOT claimed: the user action of bug 81778 (not known here); the call is made
 * directly, not through a key press.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const r = h.run({
	editor: 'word', baseRef: BASE_REF, tag: 'hlpos', script: (w, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var para = editor.WordControl.m_oLogicDocument.Content[0];
function tryit(tag, fill) {
	try {
		var hl = new AscCommonWord.ParaHyperlink();
		para.AddToContent(0, hl);
		fill(hl);
		hl.State.ContentPos = 0;
		hl.CorrectContentPos();
		out(tag, 'pos ' + hl.State.ContentPos);
	} catch (e) { out(tag, 'exception: ' + e); }
}
tryit('empty hyperlink', function () {});
tryit('hyperlink holding only a comment mark', function (hl) { hl.AddToContent(0, new AscCommon.ParaComment(true, 'x')); });
builder.CloseFile();
` });

const ck = h.checker();
for (const k of ['empty hyperlink', 'hyperlink holding only a comment mark']) {
	ck.check(k, r.results.get(k) === 'pos 0', r.results.get(k));
}
ck.finish(r);

/*
 * Upstream 279413255a (ONLYOFFICE bug 82012) - a docx with two
 * commentRangeStart (or commentRangeEnd) marks for one comment id opened with
 * the comment on the wrong text and a stray orphan mark.
 *
 * Binary_DocumentTableReader.ReadParagraphContent (word/Editor/Serialize2.js)
 * let the second mark overwrite the first anchor; the first mark stayed in the
 * paragraph with the file's id. Fix: the first start and first end are kept,
 * later duplicates skipped.
 * ADAPTED here: upstream skips with a bare "return;", which Read1 takes as a
 * read error, so all text after the duplicate mark was dropped ("Gamma Delta
 * Epsilon" vanished). Our commit returns res; the "all text kept" checks below
 * fail with upstream's version as well as with the old code.
 *
 * What runs: the WHOLE document engine headless in docbuilder (shared harness
 * ../lib/sdkjs-docbuilder.js) with the main tree's x2t. duplicate-marks.docx
 * (../upstream-4f4e0fb256-compare-comments-merged-paras/make-fixtures.py):
 *   Alpha <S0> Beta <S0> Gamma <E0> Delta <E0> Epsilon
 * is opened, saved to docx and reopened.
 *
 * Claimed: on open and after save/reopen, the text is complete, the comment
 * spans "Beta Gamma" (first start to first end) and no mark is orphaned.
 * NOT claimed: what Word does with such a file (it is invalid OOXML that
 * some producers write).
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const DUMP = `function dump(tag) {
	var doc = editor.WordControl.m_oLogicDocument, res = [];
	for (var i = 0; i < doc.Content.length; i++) {
		var p = doc.Content[i], s = '';
		for (var j = 0; j < p.Content.length; j++) {
			var el = p.Content[j];
			if (el.IsCommentStart && el.GetCommentId) {
				var c = doc.Comments.Get_ById(el.GetCommentId());
				s += '[' + (el.IsCommentStart() ? 'S:' : 'E:') + (c ? c.GetData().GetText() : 'orphan') + ']';
			} else if (el.GetText) s += el.GetText();
		}
		res.push(s.replace(/\\r\\n$/, ''));
	}
	out(tag, res.join('|'));
}`;
const r = h.run({
	editor: 'word', baseRef: BASE_REF, tag: 'dupcm',
	files: { 'in.docx': fs.readFileSync(path.join(__dirname, 'duplicate-marks.docx')) },
	script: (w) => `builder.OpenFile(${JSON.stringify(w + '/in.docx')});
${DUMP}
dump('open');
builder.SaveFile('docx', ${JSON.stringify(w + '/saved.docx')});
builder.CloseFile();
builder.OpenFile(${JSON.stringify(w + '/saved.docx')});
${h.OUT}
${DUMP}
dump('reopen');
builder.CloseFile();
` });

const WANT = 'Alpha [S:c-dup]Beta Gamma[E:c-dup] Delta Epsilon';
const ck = h.checker();
for (const tag of ['open', 'reopen']) {
	const got = r.results.get(tag);
	const text = got === undefined ? '' : got.replace(/\[[^\]]*\]/g, '');
	ck.check(`${tag}: all text kept`, text === 'Alpha Beta Gamma Delta Epsilon', JSON.stringify(text));
	ck.check(`${tag}: comment on "Beta Gamma", no orphan mark`, got === WANT, JSON.stringify(got) + (got === WANT ? '' : ' want ' + JSON.stringify(WANT)));
}
ck.finish(r);

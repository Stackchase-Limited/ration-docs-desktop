/*
 * Upstream 4f4e0fb256 (ONLYOFFICE bug 81782, 9.4.1 hotfix) - Compare Documents
 * lost the comments of the other document when it has tracked paragraph-mark
 * deletions.
 *
 * CompareBinary (word/Editor/Comparison.js) reads the other document with
 * openParams.disableRevisions. DocReadResult.checkDocumentContentReviewType
 * then accepts a deleted paragraph mark by joining the paragraph with the next
 * (Concat), but oCommentsPlaces still pointed at the removed paragraphs, so the
 * comment marks of the joined paragraphs kept the file's ids, matched no
 * comment, and the comments were dropped from the comparison. Fix: after the
 * join, the joined paragraph's comment marks are re-registered.
 *
 * What runs: the WHOLE document engine headless in docbuilder (shared harness
 * ../lib/sdkjs-docbuilder.js) with the main tree's x2t. merged-paras.docx
 * (make-fixtures.py): P1 and P2 have tracked-deleted paragraph marks, comments
 * c-one (P1), c-two (P2), c-three (P3) and c-across (P2..P3).
 *  1. The document's binary is read back exactly as CompareBinary reads the
 *     other document; every comment mark must belong to a comment, in place.
 *  2. End to end: the open document is emptied to "Delta" and
 *     AscCommonWord.CompareBinary(binary of merged-paras.docx) runs; the result
 *     must carry all four comments.
 * NOT claimed: a normal open (does not take this path), the compare UI.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const DUMP = `function dump(doc) {
	var res = [];
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
	return res;
}`;
const r = h.run({
	editor: 'word', baseRef: BASE_REF, tag: 'cmpcm',
	files: { 'in.docx': fs.readFileSync(path.join(__dirname, 'merged-paras.docx')) },
	script: (w) => `builder.OpenFile(${JSON.stringify(w + '/in.docx')});
${DUMP}
var doc1 = editor.WordControl.m_oLogicDocument;
var bin = new AscCommonWord.BinaryFileWriter(doc1).Write();
try {
	var tmp = AscFormat.ExecuteNoHistory(function () {
		var d = new AscWord.CDocument(editor.WordControl.m_oDrawingDocument, false);
		var rd = new AscCommonWord.BinaryFileReader(d, {disableRevisions: true, noSendComments: true, noGenerateSmartArts: true});
		return rd.Read(bin) ? d : null;
	}, this, []);
	out('read', tmp ? dump(tmp) : 'read failed');
} catch (e) { out('read', 'exception: ' + e); }
try {
	var ids = Object.keys(doc1.Comments.m_arrCommentsById);
	ids.forEach(function (id) { doc1.RemoveComment(id, true, false); });
	var d = Api.GetDocument();
	d.RemoveAllElements();
	var p = Api.CreateParagraph(); p.AddText('Delta'); d.Push(p);
	AscCommonWord.CompareBinary(bin, null, true);
	out('compare', Object.keys(doc1.Comments.m_arrCommentsById).map(function (id) {
		return doc1.Comments.m_arrCommentsById[id].GetData().GetText(); }).sort());
} catch (e) { out('compare', 'exception: ' + e); }
builder.CloseFile();
` });

const WANT_READ = ['Alpha [S:c-one]one[E:c-one]Beta [S:c-two]two[E:c-two] x[S:c-across]yGamma [S:c-three]three[E:c-three] z[E:c-across]', 'Delta'];
const WANT_CMP = ['c-across', 'c-one', 'c-three', 'c-two'];
const ck = h.checker();
const read = r.results.get('read');
ck.check('read as Compare reads it: paragraphs joined, every comment mark anchored', JSON.stringify(read) === JSON.stringify(WANT_READ),
	JSON.stringify(read));
const cmp = r.results.get('compare');
ck.check('Compare Documents result keeps all four comments', JSON.stringify(cmp) === JSON.stringify(WANT_CMP),
	JSON.stringify(cmp) + ' want ' + JSON.stringify(WANT_CMP));
ck.finish(r);

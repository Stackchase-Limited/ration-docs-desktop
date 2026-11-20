/*
 * Upstream 3d96c24b12 (ONLYOFFICE bug 83825) - pasting a copy of several
 * ranges (Ctrl+select A1 and A3, copy, paste) pasted wrong numbers.
 *
 * PasteProcessorExcel._readExcelBinary (cell/model/clipboard.js) reads the
 * copied fragment into a temporary workbook and removes the rows/columns
 * between the ranges. Removing them recalculated the formulas there, where
 * every cell outside the copied ones is empty, and the wrong results replaced
 * the cached values; a multi-range paste pastes those values. Fix: recalculation
 * is locked while the rows/columns are removed.
 *
 * What runs: the WHOLE spreadsheet engine headless in docbuilder (shared
 * harness ../lib/sdkjs-docbuilder.js). B1:B5 = 1..5, A1 = SUM(B1:B5) (15),
 * A2 = text, A3 = B3*10 (30). A1 and A3 are selected as two ranges and copied
 * with the real copyProcessor.getBinaryForCopy; then
 *  1. the copy is read with pasteProcessor._readExcelBinary: the temporary
 *     workbook must hold 15 and 30;
 *  2. it is pasted with g_clipboardExcel.pasteData (Internal format) at D1:
 *     D1:D2 must be 15 and 30.
 * NOT claimed: the system clipboard / HTML path, column-wise multi-ranges.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const r = h.run({
	editor: 'cell', baseRef: BASE_REF, tag: 'mrpaste', script: (w, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var sh = Api.GetActiveSheet();
for (var i = 1; i <= 5; i++) sh.GetRange('B' + i).SetValue(String(i));
sh.GetRange('A1').SetValue('=SUM(B1:B5)');
sh.GetRange('A2').SetValue('x');
sh.GetRange('A3').SetValue('=B3*10');
out('source', [String(sh.GetRange('A1').GetValue()), String(sh.GetRange('A3').GetValue())]);
try {
	var wsModel = Asc.editor.wbModel.getActiveWs();
	wsModel.selectionRange.ranges = [new Asc.Range(0, 0, 0, 0), new Asc.Range(0, 2, 0, 2)];
	var base64 = AscCommonExcel.g_clipboardExcel.copyProcessor.getBinaryForCopy(wsModel, null);
	var pp = AscCommonExcel.g_clipboardExcel.pasteProcessor;
	var tempWorkbook = new AscCommonExcel.Workbook(undefined, undefined, false);
	tempWorkbook.DrawingDocument = Asc.editor.wbModel.DrawingDocument;
	pp._readExcelBinary(base64.split('xslData;')[1], tempWorkbook);
	var tws = tempWorkbook.aWorksheets[0];
	out('temp', [tws.getCell3(0, 0).getValueWithoutFormat(), tws.getCell3(1, 0).getValueWithoutFormat()]);

	wsModel.selectionRange.ranges = [new Asc.Range(3, 0, 3, 0)];
	wsModel.selectionRange.activeCell = new AscCommon.CellBase(0, 3);
	AscCommonExcel.g_clipboardExcel.pasteData(Asc.editor.wb.getWorksheet(), AscCommon.c_oAscClipboardDataFormat.Internal, base64);
	out('pasted', [String(sh.GetRange('D1').GetValue()), String(sh.GetRange('D2').GetValue())]);
} catch (e) { out('error', String(e)); }
builder.CloseFile();
` });

const ck = h.checker();
const j = (k) => JSON.stringify(r.results.get(k));
ck.check('source values', j('source') === '["15","30"]', j('source'));
ck.check('temporary paste workbook keeps the cached results', j('temp') === '["15","30"]', j('temp') + ' want ["15","30"]');
ck.check('pasted D1:D2', j('pasted') === '["15","30"]', j('pasted') + ' want ["15","30"]');
if (r.results.has('error')) ck.check('no exception', false, r.results.get('error'));
ck.finish(r);

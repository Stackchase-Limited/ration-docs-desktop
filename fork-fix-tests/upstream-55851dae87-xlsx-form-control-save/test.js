/*
 * Upstream 55851dae87 (ONLYOFFICE bug 81832, 9.4.1 hotfix) - a spreadsheet with
 * a form control (checkbox, button, ...) could not be saved to xlsx.
 *
 * BinaryWorksheetsTableWriter.WriteControl (cell/model/Serialize.js) wrapped the
 * control's shape in an extra c_oSer_DrawingType.pptxDrawing item inside
 * c_oSerControlTypes.Shape. x2t (BinaryReaderS.cpp ReadControls) and the JS
 * reader expect the drawing record directly there, so x2t could not convert
 * the editor's binary: saving failed ("save file error (80)" in docbuilder).
 * Fix: the shape is written directly.
 *
 * What runs: the WHOLE spreadsheet engine headless in docbuilder (shared
 * harness ../lib/sdkjs-docbuilder.js) with the main tree's x2t. checkbox.xlsx
 * (written by make-fixture.py: a checked "Check Box 1" linked to $A$1, as
 * Excel saves it) is opened, saved to xlsx and reopened.
 *
 * Claimed: the control is read on open; the save succeeds and writes the
 * control's ctrlProp part and VML shape; on reopen the control is there with
 * its name, type, checked state and cell link.
 * NOT claimed: drawing the control, other control types, Excel opening the
 * result (not available here).
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

const FN = `function controls(tag) {
	var ws = Asc.editor.wbModel.getActiveWs(), res = [];
	for (var i = 0; i < ws.Drawings.length; i++) {
		var g = ws.Drawings[i].graphicObject;
		if (g && g.isControl && g.isControl())
			res.push([g.name, g.formControlPr.objectType, g.formControlPr.checked, g.formControlPr.fmlaLink, !!g.spPr]);
	}
	out(tag, res);
}`;
let savedParts = null;
const r = h.run({
	editor: 'cell', baseRef: BASE_REF, tag: 'ctrl',
	files: { 'in.xlsx': fs.readFileSync(path.join(__dirname, 'checkbox.xlsx')) },
	script: (w) => `builder.OpenFile(${JSON.stringify(w + '/in.xlsx')});
${FN}
controls('open');
builder.SaveFile('xlsx', ${JSON.stringify(w + '/saved.xlsx')});
builder.CloseFile();
${h.OUT}
${FN}
builder.OpenFile(${JSON.stringify(w + '/saved.xlsx')});
${h.OUT}
${FN}
controls('reopen');
builder.CloseFile();
`,
	after: (w) => {
		const f = path.join(w, 'saved.xlsx');
		if (fs.existsSync(f)) savedParts = spawnSync('unzip', ['-l', f], { encoding: 'utf8' }).stdout;
	},
});

// [name, objectType (1 = checkbox), checked (1 = checked), link, has shape]
const WANT = JSON.stringify([['Check Box 1', 1, 1, '$A$1', true]]);
const ck = h.checker();
ck.check('control read on open', JSON.stringify(r.results.get('open')) === WANT, JSON.stringify(r.results.get('open')));
ck.check('xlsx save succeeds', savedParts !== null, savedParts === null ? 'no saved.xlsx; ' + ((r.stdout + r.stderr).match(/save file error[^\n]*/) || [''])[0] : 'saved');
ck.check('saved xlsx has the control parts', !!savedParts && /ctrlProps\/ctrlProp1\.xml/.test(savedParts) && /vmlDrawing\d*\.vml/.test(savedParts),
	savedParts ? savedParts.split('\n').filter((l) => /ctrlProp|vml/.test(l)).map((l) => l.trim().split(/\s+/).pop()).join(', ') : '-');
ck.check('control intact after reopen', JSON.stringify(r.results.get('reopen')) === WANT, JSON.stringify(r.results.get('reopen')) + ' want ' + WANT);
ck.finish(r);

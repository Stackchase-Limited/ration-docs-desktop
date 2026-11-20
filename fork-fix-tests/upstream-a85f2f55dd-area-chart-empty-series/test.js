/*
 * Upstream a85f2f55dd (ONLYOFFICE bug 81639, 9.4.1 hotfix; master duplicate
 * f6bbebbc7d) - drawing a 3D area chart with a series that has no values threw,
 * so the sheet could not be drawn, printed or exported to PDF.
 *
 * drawAreaChart._standardDraw (common/Charts/ChartsDrawer.js) read
 * numCache.pts[0].pen / .brush without checking that the series has a point.
 * Upstream adds the check (and one for a missing point in drawStockChart's
 * data-label placement).
 * ADAPTED here: with only upstream's check the same chart then throws in
 * _drawBar3D ("brush.isNoFill" of undefined), because a series without points
 * has no compiled brush either (upstream master is the same). Our commit also
 * skips drawing such a series. Checked with upstream's change alone: this test
 * still fails (save file error 88).
 *
 * What runs: the WHOLE spreadsheet engine headless in docbuilder (shared
 * harness ../lib/sdkjs-docbuilder.js) with the main tree's x2t. An area chart
 * over A1:C5 (series by rows; row 5 "d" has no values) is made 3D (view3D,
 * right-angle axes) and the sheet is saved as PDF, which draws the chart with
 * the real chart drawer.
 * Claimed: the PDF is written; the same chart without the empty series is
 * also written (control).
 * NOT claimed: the stock-chart data-label hunk (not driven here); how the PDF
 * looks.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF (default cdbb399929 = v2026.3.0), where it must fail.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const h = require('../lib/sdkjs-docbuilder');
const BASE_REF = process.env.BASE_REF || 'cdbb399929';

function pdfOf(range) {
	let size = null;
	const r = h.run({
		editor: 'cell', baseRef: BASE_REF, tag: 'area3d', script: (w, tpl) => `builder.OpenFile(${JSON.stringify(tpl)});
var sh = Api.GetActiveSheet();
['a', 'b', 'c', 'd'].forEach(function (v, i) { sh.GetRange('A' + (i + 2)).SetValue(v); });
sh.GetRange('B1').SetValue('S1'); sh.GetRange('C1').SetValue('S2');
sh.GetRange('C2').SetValue('1'); sh.GetRange('C3').SetValue('2'); sh.GetRange('C4').SetValue('3');
var ch = sh.AddChart("'Sheet1'!${range}", true, 'area', 2, 100 * 36000, 70 * 36000, 4, 0, 6, 0);
var v = new AscFormat.CView3d(); v.setRotX(15); v.setRotY(20); v.setRAngAx(true);
ch.Chart.chart.setView3D(v);
var sers = ch.Chart.chart.plotArea.charts[0].series;
out('series', sers.map(function (s) { var nc = s.val.numRef && s.val.numRef.numCache; return nc ? nc.pts.length : -1; }));
builder.SaveFile('pdf', ${JSON.stringify(w + '/out.pdf')});
builder.CloseFile();
`,
		after: (w) => { const f = path.join(w, 'out.pdf'); size = fs.existsSync(f) ? fs.statSync(f).size : null; },
	});
	const err = ((r.stdout + r.stderr).match(/TypeError[^\n]*|save file error[^\n]*/g) || []).slice(0, 2).join('; ');
	return { r, size, series: r.results.get('series'), err };
}

const ck = h.checker();
const ctl = pdfOf('$A$1:$C$4');
ck.check('control: 3D area chart, all series with values -> PDF', ctl.size > 0, `series points ${JSON.stringify(ctl.series)}, pdf ${ctl.size} bytes ${ctl.err}`);
const t = pdfOf('$A$1:$C$5');
ck.check('3D area chart with an empty series -> PDF', t.size > 0 && JSON.stringify(t.series) === '[1,1,1,0]',
	`series points ${JSON.stringify(t.series)}, pdf ${t.size} bytes ${t.err}`);
ck.finish();

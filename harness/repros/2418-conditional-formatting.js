/*
 * Repro for upstream ONLYOFFICE/DesktopEditors#2418:
 *   "Crash when editing a cell after creating a formula-based conditional
 *    formatting rule"
 *
 * Run against an open, editable spreadsheet:
 *   harness/bin/run-editor.sh
 *   node --experimental-websocket harness/bin/editor-eval.js \
 *        --file harness/repros/2418-conditional-formatting.js --watch 10
 *
 * Reproduces the issue's steps (A2=10, B2=20, rule =OR(C2<A2,C2>B2) on C2,
 * then type a value into C2) and then probes the conditional formatting
 * evaluation path directly, so the throw is reported with a stack instead of
 * only surfacing as "An error occurred during the work with the document".
 */
var out = {steps: [], errors: [], ok: false};

// The result travels back over CDP by value, so a step must never record a live
// sdkjs model object: those are deeply cyclic and CDP answers "Object reference
// chain is too long" instead of returning anything at all. Record only what
// survives a JSON round-trip.
function reportable(v) {
	if (v === undefined || v === null) return null;
	if (typeof v !== 'object') return v;
	try {
		return JSON.parse(JSON.stringify(v));
	} catch (e) {
		return '[not serialisable: ' + (v.constructor && v.constructor.name || typeof v) + ']';
	}
}

function step(name, fn) {
	try {
		var v = fn();
		out.steps.push({step: name, ok: true, value: reportable(v)});
		return v;
	} catch (e) {
		out.steps.push({step: name, ok: false});
		out.errors.push({step: name, error: String(e && e.stack || e)});
		return undefined;
	}
}

var api = (window.Asc && Asc.editor) || null;
if (!api) { out.errors.push({step: 'find api', error: 'Asc.editor missing - is an editor page open?'}); return out; }
if (api.editorId !== AscCommon.c_oEditorId.Spreadsheet) {
	out.errors.push({step: 'check editor', error: 'not the spreadsheet editor (editorId=' + api.editorId + ') - open a .xlsx'});
	return out;
}
if (!api.canEdit || !api.canEdit()) {
	out.errors.push({step: 'check editable', error: 'document is not editable (already in view mode?)'});
	return out;
}

step('get active worksheet', function () { return api.wbModel.getActiveWs().sName; });
var wsModel = api.wbModel.getActiveWs();

function setCell(ref, value) {
	AscCommon.History.Create_NewPoint();
	wsModel.getRange2(ref).setValue(String(value));
}

step('A2 = 10', function () { setCell('A2', 10); });
step('B2 = 20', function () { setCell('B2', 20); });

// Step 4-8 of the report: a formula-based rule on C2.
step('add rule =OR(C2<A2,C2>B2) on C2', function () {
	var rule = new AscCommonExcel.CConditionalFormattingRule();
	rule.type = Asc.ECfType.expression;
	rule.priority = 1;
	rule.ranges = [AscCommonExcel.g_oRangeCache.getAscRange('C2').clone()];

	var formula = new AscCommonExcel.CFormulaCF();
	formula.Text = 'OR(C2<A2,C2>B2)';
	rule.aRuleElements = [formula];

	// The dxf is NOT cosmetic. _updateConditionalFormatting bails out with
	// `if (!oRule.dxf) { continue; }` before it ever reaches doExpression, so a
	// rule without one is never evaluated and the bug cannot appear. Build it
	// the way FormatRulesEditDlg.onFormatsSelect does - an asc_CellXfs with the
	// report's red fill.
	var xfs = new Asc.asc_CellXfs();
	xfs.asc_setFillColor(new Asc.asc_CColor(255, 199, 206));
	rule.asc_setDxf(xfs);

	// Exactly two arguments. WorksheetView.setCF branches on
	// `presetId !== undefined`, so passing an explicit null third argument sends
	// the call down the preset path (generateCFRuleFromPreset(null)) and our rule
	// is silently dropped - the rule list stays empty and nothing evaluates.
	api.asc_setCF([rule], null);

	// aConditionalFormattingRules is a map keyed by rule id, not an array.
	var installed = [];
	if (wsModel.isConditionalFormattingRules()) {
		wsModel.forEachConditionalFormattingRules(function (r) {
			installed.push({id: r.id, type: r.type, priority: r.priority,
			                text: r.aRuleElements && r.aRuleElements[0] && r.aRuleElements[0].Text,
			                ranges: (r.ranges || []).map(function (x) { return x.getName ? x.getName() : String(x); })});
		});
	}
	return {installedRules: installed, dxf: !!rule.dxf};
});

// Step 9: enter a value in the referenced cell.
step('C2 = 15 (the step that triggers the report)', function () { setCell('C2', 15); });

step('recalculate dependency tree', function () {
	wsModel.workbook.dependencyFormulas.calcTree();
});

// Now drive the exact path that raises the error: rebuilding the rules and then
// asking for the style of C2 runs compareFunction, which in 9.4.0 throws out of
// the render loop.
step('rebuild conditional formatting', function () { wsModel._updateConditionalFormatting(); });

step('evaluate rule for C2 via sheetMergedStyles.getStyle', function () {
	// C2 is row 1, col 2 (zero-based)
	var style = wsModel.sheetMergedStyles.getStyle(null, 1, 2, wsModel);
	return {conditionalStyles: style && style.conditional ? style.conditional.length : 0};
});

step('evaluate the whole rule range', function () {
	var hits = 0;
	for (var row = 0; row <= 3; row++) {
		for (var col = 0; col <= 3; col++) {
			var s = wsModel.sheetMergedStyles.getStyle(null, row, col, wsModel);
			if (s && s.conditional && s.conditional.length) hits++;
		}
	}
	return {cellsWithConditionalStyle: hits};
});

step('force a redraw', function () {
	var wsView = api.wb && api.wb.getWorksheet && api.wb.getWorksheet();
	if (wsView && wsView.draw) wsView.draw();
	else if (api.asc_Resize) api.asc_Resize();
});

// The report's step 9 in its true order. Only now has the rule's formula been
// parsed and registered in the dependency graph (CFormulaCF.init ->
// buildDependencies, reached from doExpression's compareFunction). Editing a
// cell the formula refers to is therefore the first thing that can make the
// dependency graph call back into the rule's formula parent.
step('edit C2 again, now that the rule has been evaluated (report step 9)', function () {
	setCell('C2', 25);
	wsModel.workbook.dependencyFormulas.calcTree();
	var style = wsModel.sheetMergedStyles.getStyle(null, 1, 2, wsModel);
	return {conditionalStyles: style && style.conditional ? style.conditional.length : 0};
});

step('edit A2, a cell the rule formula references', function () {
	setCell('A2', 30);
	wsModel.workbook.dependencyFormulas.calcTree();
	var style = wsModel.sheetMergedStyles.getStyle(null, 1, 2, wsModel);
	return {conditionalStyles: style && style.conditional ? style.conditional.length : 0};
});

out.ok = out.errors.length === 0;
out.summary = out.ok
	? 'No exception. Either the rule evaluated cleanly, or the containment in Workbook.js absorbed it - check for a "conditional formatting rule evaluation failed" console line above.'
	: out.errors.length + ' failing step(s) - stacks above are the root cause of #2418.';
return out;

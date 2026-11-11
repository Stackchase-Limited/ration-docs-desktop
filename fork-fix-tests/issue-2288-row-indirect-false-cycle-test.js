/*
 * #2288 - =SUMPRODUCT(--(MOD(F5,ROW(INDIRECT("2:"&INT(SQRT(F5)))))=0))=0 in G5
 * was reported as a circular reference (cell shows 0) whenever the formula's own
 * row fell inside the rows INDIRECT named (2:8 here), although ROW only reads
 * row numbers. Excel calculates it.
 *
 * Cause: INDIRECT and OFFSET results are invisible to the dependency graph, so
 * they are saved (CalcRecursion.saveFunctionResult) and Cell.recheckCellForCycle
 * calls the formula circular if its own cell lies inside any of them, whatever
 * consumed the reference. The store also had one slot per function name, so a
 * second INDIRECT in a formula hid the first.
 * Fix: the store keeps every result of the formula, and ROW/ROWS/COLUMN/COLUMNS
 * discard (by identity) the one reference they consumed. Anything else that got
 * the reference is still checked; a missed match leaves the old behaviour.
 *
 * This runs the WHOLE spreadsheet engine headless in docbuilder: the cell bundle
 * is concatenated from RD_REPO (or BASE_REF with BASELINE=1) exactly as
 * build/build.py does from configs/cell.json, and docbuilder/x2t/frameworks come
 * from the main tree's core build. Cycles are observed by wrapping
 * g_cCalcRecursion.addCycleCell (the engine's own report path).
 *
 * Claimed: positional uses (ROW, ROWS, COLUMN, COLUMNS over INDIRECT or OFFSET,
 * the reporter's layout) calculate and are not flagged; genuine dynamic cycles
 * (SUM over INDIRECT/OFFSET covering the cell, the same next to a ROW(INDIRECT()),
 * INDIRECT of the cell beside ROW of it, a cycle through another cell, ROW of an
 * INDIRECT built from the cell's own value) are still flagged, and the run ends
 * (no runaway recursion; docbuilder has a timeout).
 * NOT claimed: the GUI warning dialog; iterative-calculation mode; the
 * reporter's remark that the error survived retyping and reopening (their saved
 * file has the formula outside the row range, D11, and opens clean before and
 * after the fix).
 *
 * RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 * BASE_REF with git, where it must fail. RD_CORE_BIN / RD_CORE_LIB override the
 * core build dirs. Exits 2 (CANNOT RUN) when the core build is missing.
 */
'use strict';
const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const BASE_REF = process.env.BASE_REF || 'c996b1857c^';
const CORE_BIN = process.env.RD_CORE_BIN || path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64');
const CORE_LIB = process.env.RD_CORE_LIB || path.join(ROOT, 'core', 'build', 'lib', 'mac_arm64');
const TEMPLATE = path.join(ROOT, 'document-templates', 'new', 'en-US', 'new.xlsx');
const XREGEXP = path.join(ROOT, 'web-apps', 'vendor', 'xregexp', 'xregexp-all-min.js');
const FONTS = path.join(ROOT, 'core-fonts');

for (const p of [path.join(CORE_BIN, 'docbuilder'), path.join(CORE_BIN, 'x2t'), path.join(CORE_BIN, 'allfontsgen'),
	path.join(CORE_LIB, 'doctrenderer.framework'), TEMPLATE, XREGEXP, FONTS]) {
	if (!fs.existsSync(p)) {
		console.log('CANNOT RUN: missing ' + p);
		process.exit(2);
	}
}

/* --- sources, from the working tree or from BASE_REF --- */
function readMany(rels) {
	if (!process.env.BASELINE) {
		return rels.map((r) => fs.readFileSync(path.join(SDKJS, r)));
	}
	const out = spawnSync('git', ['-C', SDKJS, 'cat-file', '--batch'],
		{ input: rels.map((r) => `${BASE_REF}:${r}\n`).join(''), maxBuffer: 1 << 30 });
	if (out.status !== 0) throw new Error('git cat-file failed: ' + out.stderr);
	const buf = out.stdout, res = [];
	let pos = 0;
	for (const r of rels) {
		const nl = buf.indexOf(10, pos);
		const header = buf.slice(pos, nl).toString();
		const m = /^\S+ blob (\d+)$/.exec(header);
		if (!m) throw new Error(`${BASE_REF}:${r}: ${header}`);
		const size = Number(m[1]);
		res.push(buf.slice(nl + 1, nl + 1 + size));
		pos = nl + 1 + size + 1;
	}
	return res;
}
const cellConfig = JSON.parse(readMany(['configs/cell.json'])[0].toString()).sdk;
// build/build.py get_files(desktop=True): min + desktop.min, common + desktop.common
const minFiles = cellConfig.min.concat((cellConfig.desktop && cellConfig.desktop.min) || []);
const commonFiles = cellConfig.common.concat((cellConfig.desktop && cellConfig.desktop.common) || []);
const join = (bufs) => bufs.map((b) => b.toString('utf8') + '\n').join('');

/* --- a throwaway docbuilder install --- */
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'rd-2288-'));
const mk = (p) => fs.mkdirSync(path.join(work, p), { recursive: true });
['bin', 'fonts', 'editors/sdkjs/cell', 'editors/sdkjs/common/Native', 'editors/sdkjs/common/libfont',
	'editors/web-apps/vendor/xregexp'].forEach(mk);
fs.symlinkSync(CORE_LIB, path.join(work, 'Frameworks'));
for (const b of ['docbuilder', 'x2t', 'allfontsgen']) {
	fs.copyFileSync(path.join(CORE_BIN, b), path.join(work, 'bin', b), fs.constants.COPYFILE_FICLONE);
	fs.chmodSync(path.join(work, 'bin', b), 0o755);
}
fs.writeFileSync(path.join(work, 'editors/sdkjs/cell/sdk-all-min.js'), join(readMany(minFiles)));
fs.writeFileSync(path.join(work, 'editors/sdkjs/cell/sdk-all.js'),
	'(function(window, undefined) {\n' + join(readMany(commonFiles)) + '})(window);\n');
for (const f of ['native.js', 'jquery_native.js']) {
	fs.copyFileSync(path.join(SDKJS, 'common/Native', f), path.join(work, 'editors/sdkjs/common/Native', f));
}
fs.cpSync(path.join(SDKJS, 'common/libfont/engine'), path.join(work, 'editors/sdkjs/common/libfont/engine'), { recursive: true });
fs.copyFileSync(XREGEXP, path.join(work, 'editors/web-apps/vendor/xregexp/xregexp-all-min.js'));
fs.copyFileSync(TEMPLATE, path.join(work, 'new.xlsx'));
fs.writeFileSync(path.join(work, 'bin/DoctRenderer.config'), `<Settings>
<file>../editors/sdkjs/common/Native/native.js</file>
<file>../editors/sdkjs/common/Native/jquery_native.js</file>
<file>../editors/web-apps/vendor/xregexp/xregexp-all-min.js</file>
<allfonts>../fonts/AllFonts.js</allfonts>
<sdkjs>../editors/sdkjs</sdkjs>
</Settings>
`);
execFileSync(path.join(work, 'bin/allfontsgen'), ['--input=' + FONTS, '--allfonts=' + path.join(work, 'fonts/AllFonts.js'),
	'--selection=' + path.join(work, 'fonts/font_selection.bin'), '--use-system=false'], { stdio: 'ignore' });

/* --- the cases: [name, expect cycle, probe cell, expected value, cells] --- */
const q = (s) => s.replace(/'/g, '"');
const CASES = [
	['reporter layout, ROW(INDIRECT("2:8")) in row 5', false, 'G5', 'true', [['C5', '7'], ['D5', '=C5*C5'], ['E5', '11'],
		['F5', '=C5+D5+E5'], ['G5', q("=SUMPRODUCT(--(MOD(F5,ROW(INDIRECT('2:'&INT(SQRT(F5)))))=0))=0")]]],
	['ROWS(INDIRECT) over own cell', false, 'B7', '10', [['B7', q("=ROWS(INDIRECT('B1:B10'))")]]],
	['SUM(COLUMN(INDIRECT)) over own cell', false, 'C3', '21', [['C3', q("=SUM(COLUMN(INDIRECT('A3:F3')))")]]],
	['COLUMNS(INDIRECT) over own cell', false, 'C3', '6', [['C3', q("=COLUMNS(INDIRECT('A3:F3'))")]]],
	['ROW(OFFSET) of own cell', false, 'E4', '4', [['E4', '=ROW(OFFSET(E1,3,0))']]],
	['real: SUM(INDIRECT) over own cell', true, 'A10', '0', [['A1', '1'], ['A10', q("=SUM(INDIRECT('A1:A12'))")]]],
	['real: SUM(INDIRECT) beside ROW(INDIRECT)', true, 'A11', '0', [['A1', '1'],
		['A11', q("=SUM(INDIRECT('A1:A12'))*ROW(INDIRECT('11:11'))")]]],
	['real: ROW(INDIRECT(self)) + INDIRECT(self)', true, 'A12', '0', [['A12', q("=ROW(INDIRECT('A12'))+INDIRECT('A12')")]]],
	['real: cycle through another cell', true, 'F2', null, [['G1', '1'], ['F2', q("=SUM(INDIRECT('G1:G5'))")], ['G2', '=F2']]],
	['real: SUM(OFFSET) over own cell', true, 'H3', '0', [['H1', '1'], ['H3', '=SUM(OFFSET(H1,0,0,5,1))']]],
	['real: ROW(INDIRECT) of own value', true, 'A5', '0', [['A5', q("=ROW(INDIRECT('A'&A5))")]]],
];
const script = `builder.OpenFile(${JSON.stringify(path.join(work, 'new.xlsx'))});
var R = AscCommonExcel.g_cCalcRecursion, flagged = [], orig = R.addCycleCell;
R.addCycleCell = function (c) { flagged.push(c.nRow + ',' + c.nCol); return orig.apply(this, arguments); };
var CASES = ${JSON.stringify(CASES)};
for (var i = 0; i < CASES.length; i++) {
	Api.AddSheet('T' + i);
	var ws = Api.GetActiveSheet();
	flagged = [];
	for (var j = 0; j < CASES[i][4].length; j++) ws.GetRange(CASES[i][4][j][0]).SetValue(CASES[i][4][j][1]);
	console.log('RESULT ' + JSON.stringify([i, String(ws.GetRange(CASES[i][2]).GetValue()), flagged.length > 0]));
}
builder.CloseFile();
`;
fs.writeFileSync(path.join(work, 'run.js'), script);
const run = spawnSync(path.join(work, 'bin/docbuilder'), [path.join(work, 'run.js')],
	{ cwd: path.join(work, 'bin'), encoding: 'utf8', timeout: 120000 });
fs.rmSync(work, { recursive: true, force: true });
if (run.error) {
	console.log('FAIL: docbuilder did not finish: ' + run.error.message);
	process.exit(1);
}
const results = new Map();
for (const line of (run.stdout || '').split('\n')) {
	const m = /^RESULT (.*)$/.exec(line);
	if (m) { const r = JSON.parse(m[1]); results.set(r[0], r); }
}
let failed = 0;
CASES.forEach((c, i) => {
	const r = results.get(i);
	let ok = !!r && r[2] === c[1] && (c[3] === null || r[1] === c[3]);
	if (!ok) failed++;
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${c[0]}: ${c[2]}=${r ? r[1] : '?'} cycle=${r ? r[2] : '?'}` +
		` (want ${c[3] === null ? '' : c[3] + ' '}cycle=${c[1]})`);
});
if (results.size !== CASES.length) {
	console.log((run.stdout || '').slice(-2000) + (run.stderr || '').slice(-2000));
}
console.log(failed ? `FAIL: ${failed} of ${CASES.length} cases` : `PASS: ${CASES.length} cases`);
process.exit(failed ? 1 : 0);

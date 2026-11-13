/*
 * #2045 - duplicate tab.
 *
 * Before: there was no way to open a second tab of the document being edited (to look
 * at another part of it, or to try changes on a copy).
 *
 * Now (desktop, local files): File > Duplicate (the cloud-only item, now also shown in the
 * desktop app for local files in the document, spreadsheet and presentation editors) calls sdkjs api.asc_DuplicateDocument
 * (common/apiBase.js). The editor writes the document AS IT IS NOW - unsaved edits
 * included - as its own binary (getDocumentBinaryForDuplicate in word/, slide/, cell/
 * api.js, the Editor.bin format) and hands it to the existing host call
 * AscDesktopEditor.OpenBinaryAsNewFile, which "copy sheet to a new workbook" already
 * uses: the host writes it as EditorForAsLocal.bin and opens a new tab through
 * desktop-sdk OpenCopyAsRecoverFile, which copies the recovery folder (pictures), puts
 * the binary in place of Editor.bin and, since RD-0031, drops the copied changes. So the
 * source needs no save or autosave flush first and its edits are not replayed twice.
 * The copy opens unsaved under the source's name. Not offered for PDF (its recovery
 * folder is laid out differently).
 *
 * This runs the WHOLE engines headless in docbuilder (bundles concatenated from RD_REPO,
 * or BASE_REF with BASELINE=1, as issue-1203-move-paragraph-test.js): for a document, a
 * workbook and a presentation, text is added (not saved), asc_DuplicateDocument is called
 * with a stub host recording what OpenBinaryAsNewFile receives; that binary is written as
 * Editor.bin, converted by the real x2t to DOCX/XLSX/PPTX exactly as the desktop save
 * does, and reopened: the added text must be there. Also: without the host call nothing
 * happens, and a host refusing it gives false.
 *
 * NOT claimed: the new tab as opened by the app (OpenCopyAsRecoverFile is native; its
 * changes-folder handling is tested by rd-0031-copy-sheet-new-workbook); the menu item
 * as drawn - GUI check.
 *
 * RD_REPO=<sdkjs> (default ../sdkjs), RD_WEBAPPS=<web-apps> (default ../web-apps).
 * BASELINE=1 reads sources at BASE_REF / WEBAPPS_BASE_REF, where it must fail.
 * RD_CORE_BIN / RD_CORE_LIB override the core build dirs (exit 2 when missing).
 */
'use strict';
const { spawnSync, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
const WEBAPPS = process.env.RD_WEBAPPS || path.join(ROOT, 'web-apps');
// Pinned to the parents of the commits that landed this feature, never HEAD.
const BASE_REF = process.env.BASE_REF || 'fd08e90c1c^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '37c2ce2b87^';
const CORE_BIN = process.env.RD_CORE_BIN || path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64');
const CORE_LIB = process.env.RD_CORE_LIB || path.join(ROOT, 'core', 'build', 'lib', 'mac_arm64');
const TEMPLATES = path.join(ROOT, 'document-templates', 'new', 'en-US');
const XREGEXP = path.join(ROOT, 'web-apps', 'vendor', 'xregexp', 'xregexp-all-min.js');
const FONTS = path.join(ROOT, 'core-fonts');

for (const p of [path.join(CORE_BIN, 'docbuilder'), path.join(CORE_BIN, 'x2t'), path.join(CORE_BIN, 'allfontsgen'),
	path.join(CORE_LIB, 'doctrenderer.framework'), TEMPLATES, XREGEXP, FONTS]) {
	if (!fs.existsSync(p)) {
		console.log('CANNOT RUN: missing ' + p);
		process.exit(2);
	}
}

const CHECKS = [];
const check = (name, ok, got) => CHECKS.push([name, !!ok, got]);

function readMany(repo, ref, rels) {
	if (!process.env.BASELINE)
		return rels.map((r) => fs.readFileSync(path.join(repo, r)));
	const out = spawnSync('git', ['-C', repo, 'cat-file', '--batch'],
		{ input: rels.map((r) => `${ref}:${r}\n`).join(''), maxBuffer: 1 << 30 });
	if (out.status !== 0) throw new Error('git cat-file failed: ' + out.stderr);
	const buf = out.stdout, res = [];
	let pos = 0;
	for (const r of rels) {
		const nl = buf.indexOf(10, pos);
		const header = buf.slice(pos, nl).toString();
		const m = /^\S+ blob (\d+)$/.exec(header);
		if (!m) throw new Error(`${ref}:${r}: ${header}`);
		const size = Number(m[1]);
		res.push(buf.slice(nl + 1, nl + 1 + size));
		pos = nl + 1 + size + 1;
	}
	return res;
}
const join = (bufs) => bufs.map((b) => b.toString('utf8') + '\n').join('');

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'rd-2045-'));
const mk = (p) => fs.mkdirSync(path.join(work, p), { recursive: true });
['bin', 'fonts', 'editors/sdkjs/common/Native', 'editors/sdkjs/common/libfont', 'editors/web-apps/vendor/xregexp'].forEach(mk);
fs.symlinkSync(CORE_LIB, path.join(work, 'Frameworks'));
for (const b of ['docbuilder', 'x2t', 'allfontsgen']) {
	fs.copyFileSync(path.join(CORE_BIN, b), path.join(work, 'bin', b), fs.constants.COPYFILE_FICLONE);
	fs.chmodSync(path.join(work, 'bin', b), 0o755);
}
for (const product of ['word', 'cell', 'slide']) {
	const config = JSON.parse(readMany(SDKJS, BASE_REF, [`configs/${product}.json`])[0].toString()).sdk;
	const minFiles = config.min.concat((config.desktop && config.desktop.min) || []);
	const commonFiles = config.common.concat((config.desktop && config.desktop.common) || []);
	mk('editors/sdkjs/' + product);
	fs.writeFileSync(path.join(work, `editors/sdkjs/${product}/sdk-all-min.js`), join(readMany(SDKJS, BASE_REF, minFiles)));
	fs.writeFileSync(path.join(work, `editors/sdkjs/${product}/sdk-all.js`),
		'(function(window, undefined) {\n' + join(readMany(SDKJS, BASE_REF, commonFiles)) + '})(window);\n');
}
if (fs.existsSync(path.join(SDKJS, 'slide/themes')))
	fs.cpSync(path.join(SDKJS, 'slide/themes'), path.join(work, 'editors/sdkjs/slide/themes'), { recursive: true });
for (const f of ['native.js', 'jquery_native.js'])
	fs.copyFileSync(path.join(SDKJS, 'common/Native', f), path.join(work, 'editors/sdkjs/common/Native', f));
fs.cpSync(path.join(SDKJS, 'common/libfont/engine'), path.join(work, 'editors/sdkjs/common/libfont/engine'), { recursive: true });
fs.copyFileSync(XREGEXP, path.join(work, 'editors/web-apps/vendor/xregexp/xregexp-all-min.js'));
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

function docbuilder(script) {
	fs.writeFileSync(path.join(work, 'run.js'), script);
	const run = spawnSync(path.join(work, 'bin/docbuilder'), [path.join(work, 'run.js')],
		{ cwd: path.join(work, 'bin'), encoding: 'utf8', timeout: 180000, maxBuffer: 1 << 28 });
	const R = {};
	for (const line of (run.stdout || '').split('\n')) {
		const m = /^RESULT (.*)$/.exec(line);
		if (m) { const r = JSON.parse(m[1]); R[r[0]] = r[1]; }
	}
	R._out = (run.stdout || '').slice(-1500) + (run.stderr || '').slice(-1500);
	return R;
}
const MARK = 'Unsaved edit 2045';
const KINDS = {
	docx: { format: 65,
		edit: `Api.GetDocument().GetElement(0).AddText(${JSON.stringify(MARK)});`,
		read: 'Api.GetDocument().GetElement(0).GetText().trim()' },
	xlsx: { format: 257,
		edit: `Api.GetActiveSheet().GetRange('B2').SetValue(${JSON.stringify(MARK)});`,
		read: "String(Api.GetActiveSheet().GetRange('B2').GetValue())" },
	pptx: { format: 129,
		edit: `var shape = Api.CreateShape('rect', 3000000, 1000000, Api.CreateNoFill(), Api.CreateStroke(0, Api.CreateNoFill()));
			shape.GetDocContent().GetElement(0).AddText(${JSON.stringify(MARK)});
			Api.GetPresentation().GetSlideByIndex(0).AddObject(shape);`,
		read: `(function() { var t = []; var s = Api.GetPresentation().GetSlideByIndex(0).GetAllShapes();
			for (var i = 0; i < s.length; i++) { var c = s[i].GetDocContent(); c && t.push(c.GetElement(0).GetText().trim()); }
			return t.filter(Boolean).join('|'); })()` },
};
function out(name) { return `console.log('RESULT ' + JSON.stringify([${JSON.stringify(name)}, ${name}]));`; }
for (const ext of Object.keys(KINDS)) {
	const K = KINDS[ext];
	fs.copyFileSync(path.join(TEMPLATES, 'new.' + ext), path.join(work, 'new.' + ext));
	const R = docbuilder(`builder.OpenFile(${JSON.stringify(path.join(work, 'new.' + ext))});
var sent = [], refused = null, noHost = null, can = null, ok = null, err = null;
// the spreadsheet engine has no global "editor" in docbuilder
var api = (typeof editor !== 'undefined' && editor) || Asc.editor;
try {
	${K.edit}
	window["AscDesktopEditor"] = undefined;
	noHost = api.asc_DuplicateDocument();
	window["AscDesktopEditor"] = { "OpenBinaryAsNewFile": function(b64) { sent.push(b64); return false; } };
	refused = api.asc_DuplicateDocument();
	window["AscDesktopEditor"] = { "OpenBinaryAsNewFile": function(b64) { sent.push(b64); return true; } };
	can = api.asc_CanDuplicateDocument();
	ok = api.asc_DuplicateDocument();
} catch (e) { err = String(e && e.message || e); }
var lastSent = sent.length ? sent[sent.length - 1] : null;
var sentCount = sent.length;
${out('err')} ${out('noHost')} ${out('refused')} ${out('can')} ${out('ok')} ${out('sentCount')} ${out('lastSent')}
builder.CloseFile();
`);
	check(`${ext}: asc_DuplicateDocument runs`, R.err === null && 'ok' in R, R.err || R._out);
	check(`${ext}: without the host call nothing is sent (false)`, R.noHost === false, R.noHost);
	check(`${ext}: a host that does not take it gives false`, R.refused === false, R.refused);
	check(`${ext}: with the host, asc_CanDuplicateDocument and asc_DuplicateDocument are true, one binary per call`,
		R.can === true && R.ok === true && R.sentCount === 2, JSON.stringify([R.can, R.ok, R.sentCount]));
	if (!R.lastSent) continue;
	const bin = Buffer.from(R.lastSent, 'base64');
	check(`${ext}: the binary is in the Editor.bin format`, /^(DOCY|XLSY|PPTY);v\d+;/.test(bin.slice(0, 16).toString('latin1')), bin.slice(0, 16).toString('latin1'));
	const dir = path.join(work, 'dup-' + ext);
	fs.mkdirSync(dir);
	fs.writeFileSync(path.join(dir, 'Editor.bin'), bin);
	const outFile = path.join(work, 'copy.' + ext);
	fs.writeFileSync(path.join(work, 'x2t.xml'), `<?xml version="1.0" encoding="utf-8"?>
<TaskQueueDataConvert xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
<m_sFileFrom>${path.join(dir, 'Editor.bin')}</m_sFileFrom>
<m_sFileTo>${outFile}</m_sFileTo>
<m_nFormatTo>${K.format}</m_nFormatTo>
<m_sFontDir>${path.join(work, 'fonts')}</m_sFontDir>
<m_sAllFontsPath>${path.join(work, 'fonts/AllFonts.js')}</m_sAllFontsPath>
<m_bIsNoBase64>true</m_bIsNoBase64>
</TaskQueueDataConvert>
`);
	const conv = spawnSync(path.join(work, 'bin/x2t'), [path.join(work, 'x2t.xml')], { cwd: path.join(work, 'bin'), encoding: 'utf8', timeout: 120000 });
	check(`${ext}: x2t converts it as the desktop save does`, conv.status === 0 && fs.existsSync(outFile), 'x2t exit ' + conv.status + ' ' + (conv.stderr || '').slice(-300));
	if (!fs.existsSync(outFile)) continue;
	const R2 = docbuilder(`builder.OpenFile(${JSON.stringify(outFile)});
var text = null; try { text = ${K.read}; } catch (e) { text = 'error ' + e.message; }
${out('text')}
builder.CloseFile();
`);
	check(`${ext}: the duplicate holds the unsaved edit`, typeof R2.text === 'string' && R2.text.indexOf(MARK) !== -1, R2.text);
}
fs.rmSync(work, { recursive: true, force: true });

// PDF is not offered
const pdfApi = readMany(SDKJS, BASE_REF, ['pdf/api.js'])[0].toString();
check('pdf: the PDF editor keeps the base (null) binary, so asc_CanDuplicateDocument is false there',
	/PDFEditorApi\.prototype\.getDocumentBinaryForDuplicate = AscCommon\.baseEditorsApi\.prototype\.getDocumentBinaryForDuplicate;/.test(pdfApi), '');

// web-apps: the File menu item in the three editors
function readWeb(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${WEBAPPS_BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
}
for (const [app, prefix] of [['documenteditor', 'DE'], ['spreadsheeteditor', 'SSE'], ['presentationeditor', 'PE']]) {
	const view = readWeb(`apps/${app}/main/app/view/FileMenu.js`);
	const ctrl = readWeb(`apps/${app}/main/app/controller/LeftMenu.js`);
	const en = JSON.parse(readWeb(`apps/${app}/main/locale/en.json`));
	check(`web-apps ${app}: File > Duplicate is shown for local desktop files when the api can, and runs asc_DuplicateDocument there`,
		/action\s*:\s*'duplicate'/.test(view) && /this\.api\.asc_CanDuplicateDocument && this\.api\.asc_CanDuplicateDocument\(\)/.test(view) &&
		/this\.miDuplicate\[\(this\.mode\.canRequestDuplicate && !this\.mode\.isDesktopApp \|\| canDuplicateLocal\)/.test(view) &&
		/case 'duplicate':[\s\S]{0,300}this\.mode\.isDesktopApp && this\.mode\.isOffline\) this\.api\.asc_DuplicateDocument\(\)/.test(ctrl) &&
		en[`${prefix}.Views.FileMenu.btnDuplicateCaption`], '');
}

let failed = 0;
for (const [name, ok, got] of CHECKS) {
	if (!ok) failed++;
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : ': got ' + String(got).slice(0, 500)}`);
}
console.log(failed ? `FAIL: ${failed} of ${CHECKS.length} checks` : `PASS: ${CHECKS.length} checks`);
process.exit(failed ? 1 : 0);

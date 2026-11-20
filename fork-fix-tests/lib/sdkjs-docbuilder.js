/*
 * Shared harness for the upstream-* backport tests: runs the WHOLE sdkjs
 * editor engine (cell, word or slide) headless in docbuilder, as
 * issue-2288-row-indirect-false-cycle-test.js does.
 *
 * The editor bundle is concatenated from RD_REPO (or from BASE_REF with git
 * when BASELINE=1) as build/build.py does from configs/<editor>.json
 * (desktop), into a throwaway docbuilder install in the OS temp dir with its
 * own AllFonts.js (generated from core-fonts, never the app's font dir).
 * docbuilder/x2t/frameworks come from the main tree's core build.
 *
 *   RD_REPO=<sdkjs checkout> (default ../sdkjs). BASELINE=1 reads sources at
 *   BASE_REF. RD_CORE_BIN / RD_CORE_LIB override the core build dirs.
 *   Exits 2 (CANNOT RUN) when the core build is missing.
 *
 * The script passed to run() is docbuilder JS; it prints results as
 * "RESULT <json [name, value]>" lines, collected into a Map.
 */
'use strict';
const { spawnSync, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const SDKJS = process.env.RD_REPO || path.join(ROOT, 'sdkjs');
const CORE_BIN = process.env.RD_CORE_BIN || path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64');
const CORE_LIB = process.env.RD_CORE_LIB || path.join(ROOT, 'core', 'build', 'lib', 'mac_arm64');
const XREGEXP = path.join(ROOT, 'web-apps', 'vendor', 'xregexp', 'xregexp-all-min.js');
const FONTS = path.join(ROOT, 'core-fonts');
const TEMPLATES = { cell: 'new.xlsx', word: 'new.docx', slide: 'new.pptx' };

/* out(name, value) prints a RESULT line. Every builder.OpenFile starts a fresh JS
 * context, so a script that opens a second file must repeat OUT after it. */
const OUT = 'function out(name, value) { console.log("RESULT " + JSON.stringify([name, value])); }';

function readMany(rels, baseRef) {
	if (!process.env.BASELINE) {
		return rels.map((r) => fs.readFileSync(path.join(SDKJS, r)));
	}
	const out = spawnSync('git', ['-C', SDKJS, 'cat-file', '--batch'],
		{ input: rels.map((r) => `${baseRef}:${r}\n`).join(''), maxBuffer: 1 << 30 });
	if (out.status !== 0) throw new Error('git cat-file failed: ' + out.stderr);
	const buf = out.stdout, res = [];
	let pos = 0;
	for (const r of rels) {
		const nl = buf.indexOf(10, pos);
		const header = buf.slice(pos, nl).toString();
		const m = /^\S+ blob (\d+)$/.exec(header);
		if (!m) throw new Error(`${baseRef}:${r}: ${header}`);
		const size = Number(m[1]);
		res.push(buf.slice(nl + 1, nl + 1 + size));
		pos = nl + 1 + size + 1;
	}
	return res;
}

/* Reads one sdkjs source file from RD_REPO, or from baseRef with BASELINE=1. */
function readSource(rel, baseRef) {
	return readMany([rel], baseRef)[0].toString('utf8');
}

/*
 * run({ editor: 'cell'|'word'|'slide', baseRef, tag, script(work) -> string,
 *       files: { name: Buffer|string } copied into the work dir,
 *       after(work): called before the work dir is removed, to inspect output files })
 * -> { results: Map, stdout, stderr, status }
 */
function run(opts) {
	const editor = opts.editor;
	const template = path.join(ROOT, 'document-templates', 'new', 'en-US', TEMPLATES[editor]);
	for (const p of [path.join(CORE_BIN, 'docbuilder'), path.join(CORE_BIN, 'x2t'), path.join(CORE_BIN, 'allfontsgen'),
		path.join(CORE_LIB, 'doctrenderer.framework'), template, XREGEXP, FONTS]) {
		if (!fs.existsSync(p)) {
			console.log('CANNOT RUN: missing ' + p);
			process.exit(2);
		}
	}
	const config = JSON.parse(readMany([`configs/${editor}.json`], opts.baseRef)[0].toString()).sdk;
	// build/build.py get_files(desktop=True): min + desktop.min, common + desktop.common
	const minFiles = config.min.concat((config.desktop && config.desktop.min) || []);
	const commonFiles = config.common.concat((config.desktop && config.desktop.common) || []);
	const join = (bufs) => bufs.map((b) => b.toString('utf8') + '\n').join('');

	const work = fs.mkdtempSync(path.join(os.tmpdir(), 'rd-' + (opts.tag || 'up') + '-'));
	try {
		const mk = (p) => fs.mkdirSync(path.join(work, p), { recursive: true });
		['bin', 'fonts', `editors/sdkjs/${editor}`, 'editors/sdkjs/common/Native', 'editors/sdkjs/common/libfont',
			'editors/web-apps/vendor/xregexp'].forEach(mk);
		fs.symlinkSync(CORE_LIB, path.join(work, 'Frameworks'));
		for (const b of ['docbuilder', 'x2t', 'allfontsgen']) {
			fs.copyFileSync(path.join(CORE_BIN, b), path.join(work, 'bin', b), fs.constants.COPYFILE_FICLONE);
			fs.chmodSync(path.join(work, 'bin', b), 0o755);
		}
		fs.writeFileSync(path.join(work, `editors/sdkjs/${editor}/sdk-all-min.js`), join(readMany(minFiles, opts.baseRef)));
		fs.writeFileSync(path.join(work, `editors/sdkjs/${editor}/sdk-all.js`),
			'(function(window, undefined) {\n' + join(readMany(commonFiles, opts.baseRef)) + '})(window);\n');
		for (const f of ['native.js', 'jquery_native.js']) {
			fs.copyFileSync(path.join(SDKJS, 'common/Native', f), path.join(work, 'editors/sdkjs/common/Native', f));
		}
		fs.cpSync(path.join(SDKJS, 'common/libfont/engine'), path.join(work, 'editors/sdkjs/common/libfont/engine'), { recursive: true });
		fs.copyFileSync(XREGEXP, path.join(work, 'editors/web-apps/vendor/xregexp/xregexp-all-min.js'));
		fs.copyFileSync(template, path.join(work, TEMPLATES[editor]));
		for (const [name, data] of Object.entries(opts.files || {})) fs.writeFileSync(path.join(work, name), data);
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

		const script = OUT + '\n' +
			opts.script(work, path.join(work, TEMPLATES[editor]));
		fs.writeFileSync(path.join(work, 'run.js'), script);
		const r = spawnSync(path.join(work, 'bin/docbuilder'), [path.join(work, 'run.js')],
			{ cwd: path.join(work, 'bin'), encoding: 'utf8', timeout: opts.timeout || 180000 });
		const results = new Map();
		for (const line of (r.stdout || '').split('\n')) {
			const m = /^RESULT (.*)$/.exec(line);
			if (m) { const v = JSON.parse(m[1]); results.set(v[0], v[1]); }
		}
		if (r.error) results.set('__error', r.error.message);
		if (opts.after) opts.after(work);
		return { results, stdout: r.stdout || '', stderr: r.stderr || '', status: r.status };
	} finally {
		if (!process.env.KEEP_WORK) fs.rmSync(work, { recursive: true, force: true });
		else console.log('work dir kept: ' + work);
	}
}

/* check(name, ok, detail) bookkeeping, then finish() exits 0/1. */
function checker() {
	let failed = 0, total = 0;
	return {
		check(name, ok, detail) {
			total++;
			if (!ok) failed++;
			console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail !== undefined ? ': ' + detail : ''}`);
		},
		finish(r) {
			if (failed && r) console.log(r.stdout.slice(-3000) + r.stderr.slice(-3000));
			console.log(failed ? `FAIL: ${failed} of ${total} checks` : `PASS: ${total} checks`);
			process.exit(failed ? 1 : 0);
		},
	};
}

module.exports = { OUT, run, readSource, checker, SDKJS, ROOT };

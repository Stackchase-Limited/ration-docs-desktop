#!/usr/bin/env node
'use strict';
/*
 * Run JavaScript inside the live editor and report what broke.
 *
 *   node --experimental-websocket harness/bin/editor-eval.js --expr 'Asc.editor.editorId'
 *   node --experimental-websocket harness/bin/editor-eval.js --file harness/repros/2418-conditional-formatting.js
 *   node --experimental-websocket harness/bin/editor-eval.js --file <script> --watch 10
 *
 * --watch N keeps listening for N seconds after the script returns. That matters
 * for bugs that surface during a later render rather than in the call itself:
 * an uncaught exception there is exactly what sdkjs turns into EditingError.
 *
 * The CDP page target is web-apps' *wrapper* page
 * (apps/api/documents/index.html); the editor itself - and therefore Asc,
 * AscCommon, AscCommonExcel and Asc.editor - lives in a child iframe
 * (apps/spreadsheeteditor/main/index.html and friends), which CEF does not
 * expose as a target of its own. So code is run through that iframe's own
 * `eval`, which puts it in the editor's global scope where those names
 * actually resolve. Both pages are file:// and same-origin, so reaching in is
 * allowed. `--top` opts out and evaluates in the wrapper page instead.
 */
const fs = require('fs');
const path = require('path');
const {CDP, waitForPage} = require(path.join(__dirname, '..', 'lib', 'cdp.js'));

function arg(name, fallback) {
	const i = process.argv.indexOf('--' + name);
	return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

function flag(name) {
	return process.argv.indexOf('--' + name) !== -1;
}

// Find the window that actually holds the editor and run `body` (source text of
// a function body) in its global scope. Reported as data, never as a throw, so
// a failure in the script does not look like a transport failure.
function inEditorWindow(body) {
	return '(function(){\n' +
		'  var w = null;\n' +
		'  if (window.Asc && window.Asc.editor) { w = window; }\n' +
		'  if (!w) {\n' +
		'    var ifs = document.querySelectorAll("iframe");\n' +
		'    for (var i = 0; i < ifs.length; i++) {\n' +
		'      try { if (ifs[i].contentWindow && ifs[i].contentWindow.Asc && ifs[i].contentWindow.Asc.editor) { w = ifs[i].contentWindow; break; } } catch (e) {}\n' +
		'    }\n' +
		'  }\n' +
		'  if (!w) { return {harnessError: "no editor window: neither this page nor any iframe has Asc.editor - is a document open?"}; }\n' +
		'  try { return w.eval(' + JSON.stringify('(function(){\n' + body + '\n})()') + '); }\n' +
		'  catch (e) { return {harnessError: String(e && e.stack || e)}; }\n' +
		'})()';
}

(async function main() {
	const port = parseInt(arg('port', process.env.RD_PORT || '8080'), 10);
	const match = arg('target', null);
	const watchSec = parseFloat(arg('watch', '0'));
	const file = arg('file', null);
	const top = flag('top');
	const exprArg = arg('expr', null);
	let expression = null;

	// A script file can `return` a value; an --expr is an expression.
	const body = file ? fs.readFileSync(file, 'utf8') : (exprArg !== null ? 'return (' + exprArg + ');' : null);
	if (body !== null) {
		expression = top
			// Wrap so the script can `return` and so failures come back as data
			// rather than killing the evaluation.
			? '(function(){ try { return (function(){\n' + body + '\n})(); }' +
				' catch (e) { return {harnessError: String(e && e.stack || e)}; } })()'
			: inEditorWindow(body);
	}
	if (!expression) {
		console.error('usage: editor-eval.js (--expr <js> | --file <path>) [--watch secs] [--target substr] [--port n] [--top]');
		process.exit(2);
	}

	const target = await waitForPage(port, match, 30000);
	console.log('attached to: ' + target.url);
	const cdp = await CDP.connect(target);

	const failures = [];
	await cdp.watchFailures((f) => {
		failures.push(f);
		const where = f.url ? ' (' + f.url + (f.line !== undefined ? ':' + f.line : '') + ')' : '';
		console.log('  [' + f.kind + '] ' + f.text + where);
	});

	let result;
	try {
		result = await cdp.evaluate(expression);
	} catch (e) {
		console.error('evaluation failed: ' + e.message);
		cdp.close();
		process.exit(1);
	}

	console.log('\nresult:');
	console.log(typeof result === 'string' ? result : JSON.stringify(result, null, 2));

	if (watchSec > 0) {
		console.log('\nwatching for ' + watchSec + 's of async failures...');
		await new Promise((r) => setTimeout(r, watchSec * 1000));
	}

	const uncaught = failures.filter((f) => f.kind === 'uncaught');
	console.log('\n' + failures.length + ' reported issue(s), ' + uncaught.length + ' uncaught exception(s)');
	if (uncaught.length) {
		console.log('\nAn uncaught exception here is what sdkjs reports as EditingError,');
		console.log('which forces view mode. Stack above is the root cause.');
	}
	cdp.close();
	process.exit(uncaught.length ? 1 : 0);
})().catch((e) => { console.error(String(e && e.stack || e)); process.exit(1); });

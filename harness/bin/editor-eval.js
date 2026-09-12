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
 */
const fs = require('fs');
const path = require('path');
const {CDP, waitForPage} = require(path.join(__dirname, '..', 'lib', 'cdp.js'));

function arg(name, fallback) {
	const i = process.argv.indexOf('--' + name);
	return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

(async function main() {
	const port = parseInt(arg('port', process.env.RD_PORT || '8080'), 10);
	const match = arg('target', null);
	const watchSec = parseFloat(arg('watch', '0'));
	const file = arg('file', null);
	let expression = arg('expr', null);

	if (file) {
		const src = fs.readFileSync(file, 'utf8');
		// Wrap so the script can `return` and so failures come back as data
		// rather than killing the evaluation.
		expression = '(function(){ try { return (function(){\n' + src + '\n})(); }' +
			' catch (e) { return {harnessError: String(e && e.stack || e)}; } })()';
	}
	if (!expression) {
		console.error('usage: editor-eval.js (--expr <js> | --file <path>) [--watch secs] [--target substr] [--port n]');
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

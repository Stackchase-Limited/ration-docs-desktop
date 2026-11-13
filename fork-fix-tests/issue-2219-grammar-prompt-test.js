/**
 * #2219 - a custom prompt for the AI grammar check.
 *
 * The AI plugin's Grammar & Spelling check (onlyoffice.github.io sdkjs-plugins/content/ai,
 * GrammarChecker.annotateParagraph in scripts/text-annotations/grammar.js) sent a fixed prompt built
 * inline; nothing let a user change it (other language, other rules). Feature (option, default
 * unchanged): the prompt moved to scripts/text-annotations/grammar-prompt.js as GRAMMAR_PROMPT_DEFAULT
 * ("{language}" for the interface language) and a prompt kept in localStorage
 * "onlyoffice_ai_plugin_grammar_prompt" replaces it; the toolbar's Grammar & Spelling > Settings opens
 * grammarsettings.html to edit it (prefilled, Reset to default; OK stores it, an unchanged or empty one
 * is removed so the default is followed again).
 *
 * What this runs (REAL plugin source, cut out by brace matching or loaded whole, against stubs):
 *   1. GrammarChecker.annotateParagraph (grammar.js + grammar-prompt.js) with a stub chatRequest that
 *      records the request: with nothing stored, the request equals the one the code before the change
 *      sends (BASE_REF's grammar.js run the same way) - byte for byte; with a stored prompt
 *      "Check this in {language} only:" and interface language de, the request is that prompt with
 *      "German" + the paragraph; a blank stored prompt falls back to the default.
 *   2. grammarsettings.html's inline script: keepPrompt stores an edited prompt, removes an unchanged
 *      or emptied one; the text box is prefilled with the stored prompt.
 *   3. code.js: onGrammarSettingsModal opens grammarsettings.html; the plugin's button handler sends
 *      onKeepPrompt to that window on OK only and closes it.
 *   4. register.js: the Grammar & Spelling toolbar menu has the Settings item calling
 *      onGrammarSettingsModal (source check of the menu literal - it is built inside the plugin's
 *      async registration, not runnable alone).
 * NOT claimed: the window in the app (GUI), any AI model's answer to a custom prompt; the "Fix spelling
 * & grammar" context-menu action and the spelling check keep their own prompts.
 *
 * RD_REPO=<onlyoffice.github.io checkout> (default ../onlyoffice.github.io). BASELINE=1 reads every
 * source at BASE_REF (the parent of the change) with git show and MUST FAIL.
 */
'use strict';
const path = require('path');
const fs = require('fs');
const vm = require('vm');
const { execFileSync } = require('child_process');

const REPO = process.env.RD_REPO || path.resolve(__dirname, '..', 'onlyoffice.github.io');
const BASELINE = !!process.env.BASELINE;
const BASE_REF = process.env.BASE_REF || '3a3a6961^';
const AI = 'sdkjs-plugins/content/ai/';

function gitShow(ref, rel) {
	try {
		return execFileSync('git', ['-C', REPO, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26, stdio: ['ignore', 'pipe', 'ignore'] });
	} catch (e) {
		return null;
	}
}
function read(rel) {
	if (BASELINE) return gitShow(BASE_REF, rel);
	const p = path.join(REPO, rel);
	return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
}

let failures = 0;
function check(cond, what) {
	console.log((cond ? 'ok   ' : 'FAIL ') + what);
	if (!cond) failures++;
}

// the body of `<head>function name(args) {` or `<head>= async function(args) {` by brace matching (strings/templates skipped)
function cut(src, head) {
	const i = src.indexOf(head);
	if (i < 0) return null;
	let j = src.indexOf('{', i + head.length - 1);
	let depth = 0, k = j, q = null;
	for (; k < src.length; k++) {
		const c = src[k];
		if (q) {
			if (c === '\\') { k++; continue; }
			if (c === q) q = null;
			continue;
		}
		if (c === '"' || c === "'" || c === '`') { q = c; continue; }
		if (c === '{') depth++;
		else if (c === '}' && --depth === 0) break;
	}
	return src.slice(i, k + 1);
}

function makeStorage(init) {
	const m = new Map(Object.entries(init || {}));
	return {
		getItem: k => (m.has(k) ? m.get(k) : null),
		setItem: (k, v) => m.set(k, String(v)),
		removeItem: k => m.delete(k),
		has: k => m.has(k),
		get: k => m.get(k),
	};
}

// runs GrammarChecker.annotateParagraph of the given sources; returns the request it sends
async function grammarRequest(sources, storage, lang, text) {
	const sent = [];
	const ctx = {
		console, Intl,
		window: { localStorage: storage, Asc: { plugin: { info: { lang } } } },
		Asc: { Editor: { callMethod: async () => {} } },
		TextAnnotator: function () { this.paragraphs = {}; },
	};
	ctx.window.window = ctx.window;
	ctx.TextAnnotator.prototype = {};
	vm.createContext(ctx);
	for (const s of sources) vm.runInContext(s, ctx);
	vm.runInContext('this.__G = GrammarChecker;', ctx);
	const g = new ctx.__G(null);
	g.chatRequest = async p => { sent.push(p); return '[]'; };
	await g.annotateParagraph('p1', 1, text);
	return sent[0];
}

(async () => {
	console.log(BASELINE ? `BASELINE (${BASE_REF})` : `tree ${REPO}`);
	const grammarJs = read(AI + 'scripts/text-annotations/grammar.js');
	const promptJs = read(AI + 'scripts/text-annotations/grammar-prompt.js');
	const sources = promptJs ? [promptJs, grammarJs] : [grammarJs];
	const before = gitShow(BASE_REF, AI + 'scripts/text-annotations/grammar.js');
	const TEXT = 'She dont like apples Me and him goes to school.';

	// 1. the request
	const ref = await grammarRequest([before], makeStorage(), 'de-DE', TEXT);
	const dflt = await grammarRequest(sources, makeStorage(), 'de-DE', TEXT);
	check(typeof ref === 'string' && ref.endsWith('Text to check:' + TEXT) && ref.includes('strictly in the German language'),
		'reference: the code before the change asks in German and ends with the paragraph');
	check(dflt === ref, 'nothing stored: the request is byte for byte the one sent before (' + (dflt || '').length + ' chars)');
	const custom = await grammarRequest(sources, makeStorage({ onlyoffice_ai_plugin_grammar_prompt: 'Check this in {language} only, answer as JSON []:\n' }), 'de-DE', TEXT);
	console.log('     custom request: ' + JSON.stringify((custom || '').slice(0, 100)));
	check(custom === 'Check this in German only, answer as JSON []:\n' + TEXT, 'a stored prompt replaces the default, {language} filled in, the paragraph after it');
	const blank = await grammarRequest(sources, makeStorage({ onlyoffice_ai_plugin_grammar_prompt: '  \n ' }), 'de-DE', TEXT);
	check(blank === ref, 'a blank stored prompt falls back to the default');

	// 2. the settings window
	const html = read(AI + 'grammarsettings.html');
	check(!!html && html.includes('scripts/text-annotations/grammar-prompt.js'), 'grammarsettings.html exists and loads grammar-prompt.js');
	if (html && promptJs) {
		const inline = html.match(/<script>([\s\S]*?)<\/script>/g).map(s => s.replace(/^<script>|<\/script>$/g, '')).join('\n');
		const keepSrc = cut(inline, 'function keepPrompt(');
		const run = (storage, value) => {
			const ctx = { window: { localStorage: storage } };
			vm.createContext(ctx);
			vm.runInContext(promptJs, ctx);
			vm.runInContext(keepSrc + '\nkeepPrompt(' + JSON.stringify(value) + ');', ctx);
			return vm.runInContext('GRAMMAR_PROMPT_DEFAULT', ctx);
		};
		let st = makeStorage();
		run(st, 'Prüfe auf {language}:');
		check(st.get('onlyoffice_ai_plugin_grammar_prompt') === 'Prüfe auf {language}:', 'OK with an edited prompt stores it');
		const def = run(st = makeStorage({ onlyoffice_ai_plugin_grammar_prompt: 'old' }), '');
		check(!st.has('onlyoffice_ai_plugin_grammar_prompt'), 'OK with an emptied prompt removes the stored one');
		run(st = makeStorage({ onlyoffice_ai_plugin_grammar_prompt: 'old' }), def + '\n');
		check(!st.has('onlyoffice_ai_plugin_grammar_prompt'), 'OK with the default prompt (Reset to default) removes the stored one');
		check(/getElementById\("idx-prompt"\)\.value = getGrammarPromptTemplate\(\)/.test(inline), 'the text box is prefilled with the prompt in use');
	} else {
		check(false, 'keepPrompt runs');
	}

	// 3. code.js: the window and its buttons
	const code = read(AI + 'scripts/code.js');
	const openSrc = cut(code, 'function onGrammarSettingsModal(');
	const buttonSrc = cut(code, 'window.Asc.plugin.button = async function(id, windowId) {');
	if (openSrc && buttonSrc) {
		const log = [];
		const ctx = {
			log,
			window: { Asc: { plugin: { tr: s => s } } },
			grammarSettingsWindow: null, textAnnotatorPopup: null, customAnnotationPopup: null, settingsWindow: null,
			aiModelsListWindow: null, translateSettingsWindow: null, aiModelEditWindow: null, customProvidersWindow: null,
		};
		ctx.window.Asc.PluginWindow = function () {
			this.id = 'w-grammar';
			this.show = v => log.push(['show', v.url, v.isModal, (v.buttons || []).length]);
			this.command = c => log.push(['command', c]);
			this.close = () => log.push(['close']);
		};
		ctx.window.Asc.plugin.executeMethod = (m, a) => log.push([m, a]);
		vm.createContext(ctx);
		// the context's properties are the globals the plugin code refers to
		vm.runInContext(openSrc + '\n' + buttonSrc, ctx);
		vm.runInContext('onGrammarSettingsModal()', ctx);
		await vm.runInContext('window.Asc.plugin.button(0, "w-grammar")', ctx);
		check(JSON.stringify(log) === JSON.stringify([['show', 'grammarsettings.html', true, 2], ['command', 'onKeepPrompt'], ['close']]),
			'Settings opens grammarsettings.html (modal, OK/Cancel); OK sends onKeepPrompt and closes: ' + JSON.stringify(log));
		log.length = 0;
		vm.runInContext('onGrammarSettingsModal()', ctx);
		await vm.runInContext('window.Asc.plugin.button(1, "w-grammar")', ctx);
		check(JSON.stringify(log.slice(1)) === JSON.stringify([['close']]), 'Cancel closes without keeping: ' + JSON.stringify(log.slice(1)));
	} else {
		check(false, 'code.js has onGrammarSettingsModal and its button handling');
	}

	// 4. register.js menu
	const reg = read(AI + 'scripts/engine/register.js') || '';
	const gs = reg.slice(reg.indexOf('buttonGS.menu = ['), reg.indexOf('buttonGS.attachOnClick'));
	check(/text:\s*'Settings',[\s\S]*onclick:\s*\(\)\s*=>\s*onGrammarSettingsModal\(\)/.test(gs), 'Grammar & Spelling toolbar menu: Settings -> onGrammarSettingsModal');
	const idx = read(AI + 'index.html') || '';
	check(idx.indexOf('grammar-prompt.js') > 0 && idx.indexOf('grammar-prompt.js') < idx.indexOf('text-annotations/grammar.js'), 'index.html loads grammar-prompt.js before grammar.js');

	if (failures) {
		console.log(`FAIL: ${failures} check(s) failed`);
		process.exit(1);
	}
	console.log('ALL PASS');
})().catch(e => { console.log('FAIL: ' + (e && e.stack || e)); process.exit(1); });

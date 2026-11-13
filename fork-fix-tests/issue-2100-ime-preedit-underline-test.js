/*
 * #2100 - "Support styling the preedit text (appearance) in Linux": input
 * methods (fcitx5, IBus engines such as unikey or m17n) style their own
 * preedit and let the user turn its underline off; Gedit and Kate follow
 * that, the editors always underline the text being composed.
 *
 * Cause: sdkjs word/Editor/Paragraph/draw/line-draw-state.js
 * addCompositeInputLine adds an underline under every composed character,
 * unconditionally. The input method's own styling cannot be followed in
 * CEF 109: Chromium's GTK input context (ui/gtk/input_method_context_impl_gtk.cc,
 * ExtractCompositionTextFromGtkPreedit) turns the preedit's Pango attributes
 * into ImeTextSpans for Blink's rendering of the hidden textarea; JavaScript
 * only sees the composition text (and its selection).
 * Fix (option, on by default): api.asc_setCompositeInputUnderline(false)
 * -> AscWord.setCompositeInputUnderline stops addCompositeInputLine from
 * adding the underline; web-apps DE Advanced settings checkbox
 * de-settings-ime-underline (unset = on).
 *
 * This test evaluates the REAL line-draw-state.js module (with stubs for
 * AscWord/para_Text) and the REAL asc_setCompositeInputUnderline extracted
 * from word/api.js, and checks:
 *  1. default: a composed character gets the underline (unchanged);
 *  2. a character outside the composition gets none (unchanged);
 *  3. option off: no underline under composed text (baseline: no API -> FAILS);
 *  4. option back on: underline again;
 *  5. web-apps: checkbox stored as de-settings-ime-underline, default on,
 *     passed to asc_setCompositeInputUnderline on load and on apply (only when
 *     RD_WEBAPPS is given or ../web-apps exists).
 *
 * NOT claimed: what an input method shows on screen (needs a GUI check with
 * fcitx5/IBus on Linux); the presentation and spreadsheet editors keep the
 * underline; IME span styles (thick/highlighted target segment) are not drawn.
 *
 * Env: RD_REPO     sdkjs checkout (default ../sdkjs)
 *      RD_WEBAPPS  web-apps checkout (default ../web-apps)
 *      BASELINE=1 reads sources at BASE_REF / WEBAPPS_BASE_REF; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const SDKJS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'sdkjs'));
const WEB = path.resolve(process.env.RD_WEBAPPS || path.join(__dirname, '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || 'f9156829a2^';
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || '5598f8486c^';

function src(repo, ref, rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', repo, 'show', `${ref}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(repo, rel), 'utf8');
}
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(from, i + 1);
	}
	throw new Error('unbalanced braces');
}

const para_Text = 1;
const AscWord = {};
new Function('window', 'AscWord', 'AscCommon', 'para_Text',
	src(SDKJS, BASE_REF, 'word/Editor/Paragraph/draw/line-draw-state.js'))({}, AscWord, {}, para_Text);
assert.ok(AscWord.ParagraphLineDrawState, 'line-draw-state.js did not define ParagraphLineDrawState');

const apiJs = src(SDKJS, BASE_REF, 'word/api.js');
const apiProto = {};
const marker = 'asc_docs_api.prototype.asc_setCompositeInputUnderline = function';
if (apiJs.indexOf(marker) !== -1)
	new Function('asc_docs_api', 'AscWord', block(apiJs, apiJs.indexOf(marker)) + ';')({ prototype: apiProto }, AscWord);
const api = {
	setUnderline(isOn) {
		assert.ok(apiProto.asc_setCompositeInputUnderline, 'word/api.js has no asc_setCompositeInputUnderline');
		apiProto.asc_setCompositeInputUnderline.call(this, isOn);
	},
};

// Underlines added for one composed character and one ordinary character.
function draw() {
	const st = Object.create(AscWord.ParagraphLineDrawState.prototype);
	const lines = [];
	st.X = 10; st.color = { r: 0, g: 0, b: 0 }; st.textPr = {};
	st.Underline = { Add(x0, x1) { lines.push([x0, x1]); } };
	const element = { Type: para_Text, GetWidthVisible: () => 5 };
	const run = { CompositeInput: { isInside: (pos) => pos === 0 } };
	st.addCompositeInputLine(element, run, 0);
	const inside = lines.length;
	st.addCompositeInputLine(element, run, 1);
	return { inside, outside: lines.length - inside };
}

let failed = 0;
function check(label, fn) {
	try { fn(); console.log('ok   ' + label); }
	catch (e) { failed++; console.log('FAIL ' + label + ': ' + e.message); }
}

check('default: composed text is underlined (unchanged)', () => {
	assert.strictEqual(draw().inside, 1);
});
check('text outside the composition: no composition underline (unchanged)', () => {
	assert.strictEqual(draw().outside, 0);
});
check('option off: composed text is not underlined', () => {
	api.setUnderline(false);
	const r = draw();
	api.setUnderline(true);
	assert.strictEqual(r.inside, 0, 'underline still drawn');
});
check('option back on: underlined again', () => {
	api.setUnderline(false);
	api.setUnderline(true);
	assert.strictEqual(draw().inside, 1);
});

if (fs.existsSync(path.join(WEB, 'apps/documenteditor'))) {
	check('web-apps: DE Advanced settings checkbox wired to asc_setCompositeInputUnderline, default on', () => {
		const panels = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/view/FileMenuPanels.js');
		const main = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/controller/Main.js');
		const left = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/app/controller/LeftMenu.js');
		const en = src(WEB, WEBAPPS_BASE_REF, 'apps/documenteditor/main/locale/en.json');
		assert.ok(/fms-chb-ime-underline/.test(panels) && /setBool\("de-settings-ime-underline"/.test(panels), 'no checkbox / storage');
		assert.ok(/getBool\("de-settings-ime-underline", true\)/.test(main), 'not read on load with default on');
		assert.ok(/asc_setCompositeInputUnderline\(/.test(main), 'not applied on load');
		assert.ok(/asc_setCompositeInputUnderline\(/.test(left), 'not applied on settings apply');
		assert.ok(/"DE\.Views\.FileMenuPanels\.Settings\.txtImeUnderline":/.test(en), 'no en.json string');
	});
}

if (failed) { console.log(failed + ' check(s) failed'); process.exit(1); }
console.log('PASS #2100 composition underline can be turned off (on by default)');

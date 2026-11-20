/*
 * Upstream 3f9b9168e4 "[PDFE] Fix crash caused by the right panel".
 *
 * In the PDF editor RightMenu.addNewPlugin (a plugin docked into the right
 * panel) called Viewport.applyEditorMode(true), which set a sticky
 * _forceShowRightMenu flag: from then on applyEditorMode() skipped the right
 * panel on every view/comment/edit mode switch. And if the user had hidden
 * the right panel, the plugin was docked into the hidden panel and could not
 * be seen; View > Right panel was not updated. Ours is a hand port (upstream
 * builds on 9e7297a324, 10.0's right panel in every mode, which we do not take).
 *
 * This test extracts the real Viewport.applyEditorMode, RightMenu
 * onRightMenuHide / addNewPlugin / hasPlugins and the ViewTab 'RightMenu'
 * 'view:hide' handler, and runs them against stub views:
 *  A. edit mode, right panel hidden by the user, a plugin docks: the panel is
 *     shown, the setting is saved as shown and View > Right panel is checked
 *     (baseline: panel stays hidden, no event -> FAILS);
 *  B. view mode, a plugin docks (panel rendered and shown), switch to edit
 *     and back to view: the panel stays while the plugin is docked; after the
 *     plugin is closed, switching to view hides the panel again, i.e. the
 *     panel follows the mode (baseline: stuck shown -> FAILS);
 *  C. plain edit/view switches without plugins show and hide the panel as
 *     before, and nothing throws.
 *
 * NOT claimed: the real DOM/layout, or the crash upstream saw in its 10.0
 * code (not reproduced here); the plugin panel's own behaviour.
 *
 * Env: RD_REPO   web-apps checkout (default ../../web-apps)
 *      BASELINE=1 reads web-apps from BASE_REF (default 12a95aaeda) via git show; must FAIL.
 */
'use strict';
const assert = require('assert');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const WEB = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', '..', 'web-apps'));
const BASE_REF = process.env.BASE_REF || '12a95aaeda';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEB, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(WEB, rel), 'utf8');
}

// text of the balanced {...} block that starts at the first '{' at or after `from`
function block(text, from) {
	const open = text.indexOf('{', from);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		if (text[i] === '{') depth++;
		else if (text[i] === '}' && --depth === 0) return text.slice(open, i + 1);
	}
	throw new Error('unbalanced braces');
}

// the real method `name: function(args) {...}` of a controller, as a function that sees `deps` by name
function method(text, name, deps) {
	const m = new RegExp('\\b' + name + '\\s*:\\s*function\\s*\\(([^)]*)\\)').exec(text);
	if (!m) return null;
	const body = block(text, m.index + m[0].length);
	const names = Object.keys(deps || {});
	return new Function(...names, `return function(${m[1]}) ${body};`)(...names.map(k => deps[k]));
}

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

const vpText = src('apps/pdfeditor/main/app/controller/Viewport.js');
const rmText = src('apps/pdfeditor/main/app/controller/RightMenu.js');
const vtText = src('apps/pdfeditor/main/app/controller/ViewTab.js');

function setup(mode, store) {
	const settings = {};
	const Common = {
		localStorage: {
			getBool: (k, d) => (k in store ? store[k] : !!d),
			setBool: (k, v) => { store[k] = !!v; },
		},
		Utils: { InternalSettings: { get: k => settings[k], set: (k, v) => { settings[k] = v; } } },
		NotificationCenter: { trigger() {} },
		UI: { LayoutManager: { getInitValue: () => undefined } },
	};
	const events = [];
	const view = {
		visible: false, rendered: false, buttons: [],
		render() { this.rendered = true; this.visible = true; return this; },
		show() { this.visible = true; }, hide() { this.visible = false; },
		setApi() {}, setMode() {},
		GetActivePane() {}, toggleActivePluginButton() {}, clearSelection() {},
		insertButton(b) { this.buttons.push(b); }, insertPanel() {},
		closePlugin(guid) { this.buttons = this.buttons.filter(b => b.guid !== guid); },
		fireEvent(name, args) { events.push([name, args]); },
	};
	view.$el = {
		is: s => (s === ':hidden' ? !view.visible : false),
		has: el => ({ length: view.buttons.some(b => b.cmpEl === el) ? 1 : 0 }),
	};
	const app = {};
	const rm = {
		rightmenu: view, _settings: [], api: { getSelectedElements: () => [] },
		onFocusObject() {}, setMode() {}, setApi() {}, getView: () => view, getApplication: () => app,
	};
	for (const name of ['onRightMenuHide', 'addNewPlugin', 'hasPlugins']) {
		const fn = method(rmText, name, { Common });
		if (fn) rm[name] = fn;
	}
	const vp = { viewport: {}, mode, api: {}, _initEditing: true, getApplication: () => app };
	vp.applyEditorMode = method(vpText, 'applyEditorMode', { Common });
	app.getController = n => ({ RightMenu: rm, Viewport: vp })[n];

	// View > Right panel checkbox, through the real ViewTab handler for RightMenu 'view:hide'
	const checkbox = { value: undefined, setValue(v) { this.value = v; } };
	const m = /'RightMenu'\s*:\s*\{\s*'view:hide'\s*:\s*_\.bind\(function\s*\(([^)]*)\)/.exec(vtText);
	let onViewHide = null;
	if (m) {
		const f = new Function(`return function(${m[1]}) ${block(vtText, m.index + m[0].length)};`)();
		onViewHide = (args) => f.apply({ view: { chRightMenu: checkbox } }, args);
	}
	const fire = () => { while (events.length) { const [n, a] = events.shift(); if (n === 'view:hide' && onViewHide) onViewHide(a); } };
	const plugin = guid => ({ guid, options: { type: 'plugin' }, cmpEl: { id: guid } });
	return { vp, rm, view, store, checkbox, fire, plugin, hasViewTabHandler: !!onViewHide };
}

function safe(label, f) {
	try { f(); return true; } catch (e) { check(false, `${label} throws: ${e.message}`); return false; }
}

/* ---- A. hidden right panel, plugin docks in edit mode ---- */
{
	const mode = { isPDFEdit: true };
	const s = setup(mode, { 'pdfe-hidden-rightmenu': true });
	safe('A load', () => s.vp.applyEditorMode());
	check(s.view.rendered && !s.view.visible, 'A: edit mode load keeps the panel the user hid hidden');
	s.checkbox.value = false;
	safe('A dock', () => { s.rm.addNewPlugin(s.plugin('p1'), {}, {}); s.fire(); });
	check(s.view.visible, 'A: docking a plugin shows the hidden right panel');
	check(s.store['pdfe-hidden-rightmenu'] === false, `A: the panel is remembered as shown (pdfe-hidden-rightmenu=${s.store['pdfe-hidden-rightmenu']})`);
	check(s.hasViewTabHandler && s.checkbox.value === true, `A: View > Right panel is checked (${s.checkbox.value})`);
}

/* ---- B. plugin docked in view mode, then mode switches ---- */
{
	const mode = { isPDFEdit: false };
	const s = setup(mode, {});
	safe('B load', () => s.vp.applyEditorMode());
	check(!s.view.rendered, 'B: view mode load does not render the panel');
	safe('B dock', () => { s.rm.addNewPlugin(s.plugin('p1'), {}, {}); s.fire(); });
	check(s.view.rendered && s.view.visible, 'B: docking a plugin in view mode shows the panel');
	mode.isPDFEdit = true; safe('B edit', () => { s.vp.applyEditorMode(); s.fire(); });
	check(s.view.visible, 'B: switch to edit: panel shown');
	mode.isPDFEdit = false; safe('B view', () => { s.vp.applyEditorMode(); s.fire(); });
	check(s.view.visible, 'B: back to view with the plugin docked: panel still shown');
	s.view.closePlugin('p1');
	mode.isPDFEdit = true; safe('B edit2', () => { s.vp.applyEditorMode(); s.fire(); });
	mode.isPDFEdit = false; safe('B view2', () => { s.vp.applyEditorMode(); s.fire(); });
	check(!s.view.visible, 'B: plugin closed, switch to view: panel hidden again (follows the mode)');
}

/* ---- C. no plugins: mode switches as before ---- */
{
	const mode = { isPDFEdit: true };
	const s = setup(mode, {});
	safe('C load', () => s.vp.applyEditorMode());
	check(s.view.visible, 'C: edit mode: panel shown');
	mode.isPDFEdit = false; safe('C view', () => { s.vp.applyEditorMode(); s.fire(); });
	check(!s.view.visible, 'C: view mode: panel hidden');
	mode.isPDFEdit = true; safe('C edit', () => { s.vp.applyEditorMode(); s.fire(); });
	check(s.view.visible, 'C: edit mode again: panel shown');
	check(s.store['pdfe-hidden-rightmenu'] === undefined, 'C: mode switches do not change the saved setting');
}

if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log('PASS');

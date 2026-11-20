/*
 * Upstream ed424af8e4 (bug 81827): license type 17, NotEnoughResources.
 *
 * An ONLYOFFICE 10 document server short of resources (our server
 * ration/10.0, DocsCoServer CE memory guard) puts a new connection into view
 * mode and reports license type 17. Our 9.4 editors only knew Connections,
 * UsersCount, ConnectionsOS and UsersCountOS, so for 17 onLicenseChanged
 * ignored it: editing was never disabled and co-authoring never disconnected.
 * The user kept typing while the server treated them as a viewer, and the
 * edits were lost. "Not enough resources" was also shown for the real
 * connection limit (ConnectionsOS).
 *
 * This test extracts the real onLicenseChanged + applyLicense of the document,
 * spreadsheet, presentation, PDF and diagram editors (main) and runs them
 * with the license constants of our sdkjs (common/apiCommon.js), both
 * without NotEnoughResources (sdkjs before its backport) and with
 * NotEnoughResources: 17:
 *  - type 17: editing disabled, co-authoring disconnected, the "not enough
 *    resources" message with its title (baseline: nothing happens -> FAILS);
 *  - ConnectionsOS: editing disabled, the connection-limit message
 *    warnNoLicense (baseline: the resources message -> FAILS);
 *  - UsersCountOS still shows warnNoLicenseUsers; type 17 in a viewer
 *    (editorConfig.mode 'view') changes nothing.
 * It also checks the forms editor and the mobile editors' license code
 * handles 17 (source check) and that every en.json the fix touches has
 * the warnNoLicense string.
 *
 * NOT claimed: a real v10 server sending 17; the dialog rendering.
 *
 * Env: RD_REPO   web-apps checkout (default ../../web-apps)
 *      RD_SDKJS  sdkjs checkout (default ../../sdkjs), for the constants
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

const SDKJS = path.resolve(process.env.RD_SDKJS || path.join(__dirname, '..', '..', 'sdkjs'));

let failed = 0;
function check(ok, msg) { console.log((ok ? 'ok   ' : 'FAIL ') + msg); if (!ok) failed++; }

// license constants as our sdkjs defines them
const apiCommon = fs.readFileSync(path.join(SDKJS, 'common/apiCommon.js'), 'utf8');
const lr = new Function('return ' + block(apiCommon, apiCommon.indexOf('var c_oLicenseResult')))();
assert(lr.ConnectionsOS === 9 && lr.UsersCountOS === 10, 'unexpected sdkjs license constants');
const withoutConst = Object.assign({}, lr); delete withoutConst.NotEnoughResources;
const withConst = Object.assign({}, lr, { NotEnoughResources: 17 });

const editors = ['documenteditor', 'spreadsheeteditor', 'presentationeditor', 'pdfeditor', 'visioeditor'];

function run(text, licType, consts, viewMode) {
	const shown = [];
	const calls = [];
	const Asc = { c_oLicenseResult: consts, c_oLicenseMode: { None: 0, Trial: 1, Developer: 2, Limited: 4 } };
	const Common = {
		UI: {
			info: o => shown.push({ title: o.title, msg: o.msg }),
			warning: o => shown.push({ title: o.title, msg: o.msg }),
			TooltipManager: { showTip: o => shown.push({ title: o.header, msg: o.text }) },
		},
		NotificationCenter: { trigger: e => calls.push('notify:' + e) },
		Utils: { InternalSettings: { get() {} } },
	};
	const deps = { Asc, Common, window: { open() {} }, _: { bind: (f, c) => f.bind(c) } };
	const self = {
		appOptions: { canEdit: true, isEdit: true, isPDFAnnotate: true, isRestrictedEdit: false, isAnonymousSupport: true, user: {}, trialMode: 0, canLiveView: false, isDesktopApp: false },
		editorConfig: { mode: viewMode ? 'view' : 'edit' },
		_state: {}, _isDocReady: true,
		api: { asc_coAuthoringDisconnect: () => calls.push('disconnect') },
		disableEditing: () => calls.push('disableEditing'),
		disableLiveViewing: () => calls.push('disableLiveViewing'),
		warnNoResources: 'RESOURCES', warnNoLicense: 'CONNECTIONS', warnNoLicenseUsers: 'USERS',
		textNoResourcesTitle: 'RESOURCES_TITLE', textNoLicenseTitle: 'LICENSE_TITLE', titleReadOnly: 'READONLY',
		tipLicenseExceeded: 'TIP_CONN', tipLicenseUsersExceeded: 'TIP_USERS', warnLicenseLimitedRenewed: 'RENEW',
		textBuyNow: 'buy', textContactUs: 'contact', textContinue: 'continue', notcriticalErrorTitle: 'warn', warnLicenseAnonymous: 'anon',
	};
	self.applyLicense = method(text, 'applyLicense', deps);
	const onLicenseChanged = method(text, 'onLicenseChanged', deps);
	onLicenseChanged.call(self, { asc_getLicenseType: () => licType });
	return { calls, shown };
}

for (const ed of editors) {
	const rel = `apps/${ed}/main/app/controller/Main.js`;
	const text = src(rel);
	for (const [label, consts] of [['sdkjs without the constant', withoutConst], ['sdkjs with NotEnoughResources', withConst]]) {
		let r = run(text, 17, consts);
		check(r.calls.includes('disableEditing') && r.calls.includes('disconnect') &&
			r.shown.length === 1 && r.shown[0].msg === 'RESOURCES' && r.shown[0].title === 'RESOURCES_TITLE',
			`${ed} (${label}): type 17 locks editing and shows the resources message (${r.calls.join(',') || 'nothing'}; ${JSON.stringify(r.shown)})`);
		r = run(text, lr.ConnectionsOS, consts);
		check(r.calls.includes('disableEditing') && r.shown.length === 1 && r.shown[0].msg === 'CONNECTIONS',
			`${ed} (${label}): ConnectionsOS shows the connection-limit message (${JSON.stringify(r.shown)})`);
		r = run(text, lr.UsersCountOS, consts);
		check(r.calls.includes('disableEditing') && r.shown.length === 1 && r.shown[0].msg === 'USERS',
			`${ed} (${label}): UsersCountOS shows the user-limit message (${JSON.stringify(r.shown)})`);
		r = run(text, 17, consts, true);
		check(!r.calls.includes('disableEditing') && r.shown.length === 0, `${ed} (${label}): type 17 in a viewer changes nothing`);
	}
}

// forms and mobile editors: source check of the license condition and messages
const other = [
	'apps/documenteditor/forms/app/controller/ApplicationController.js',
	'apps/documenteditor/mobile/src/controller/Main.jsx',
	'apps/spreadsheeteditor/mobile/src/controller/Main.jsx',
	'apps/presentationeditor/mobile/src/controller/Main.jsx',
	'apps/visioeditor/mobile/src/controller/Main.jsx',
];
for (const rel of other) {
	const text = src(rel);
	const cond = /licType\s*===\s*\(?Asc\.c_oLicenseResult\.NotEnoughResources(\s*\|\|\s*17\))?/.test(text) &&
		/licType\s*===\s*Asc\.c_oLicenseResult\.UsersCountOS\s*\|\|\s*licType\s*===\s*\(Asc\.c_oLicenseResult\.NotEnoughResources\s*\|\|\s*17\)/.test(text);
	const msg = /===\s*\(Asc\.c_oLicenseResult\.NotEnoughResources\s*\|\|\s*17\)\)\s*\?\s*(this\.|_t\.)?warnNoResources\s*:\s*\n?\s*\(license\s*===\s*Asc\.c_oLicenseResult\.ConnectionsOS\)\s*\?\s*(this\.)?warnNoLicense\b/.test(text);
	check(cond && msg, `${rel}: type 17 (also without the sdkjs constant) locks editing; ConnectionsOS -> warnNoLicense`);
}

for (const ed of editors) for (const kind of ['main', 'mobile', 'forms']) {
	if (kind === 'forms' && ed !== 'documenteditor') continue;
	if (kind === 'mobile' && ed === 'pdfeditor') continue;
	const rel = `apps/${ed}/${kind}/locale/en.json`;
	const json = JSON.parse(src(rel));
	const found = [];
	(function walk(o) { for (const k in o) { if (o[k] && typeof o[k] === 'object') walk(o[k]); else if (/(^|\.)warnNoLicense$/.test(k)) found.push(o[k]); } })(json);
	check(found.length > 0 && found.every(v => /simultaneous connections/.test(v)), `${rel}: warnNoLicense string present`);
}

if (failed) { console.log(`${failed} check(s) failed`); process.exit(1); }
console.log('PASS');

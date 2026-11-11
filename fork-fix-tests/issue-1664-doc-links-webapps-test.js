/*
 * #1664 (follow-up) - hyperlinks in documents: the editors' side.
 *
 * A click on a hyperlink reaches web-apps (asc_onHyperlinkClick): http/https/
 * mailto go to window.open, anything else (file://, smb://, another app's
 * scheme, and in a local file ANY target string, see sdkjs apiBase.js
 * asc_getUrlType) first shows "This location may be unsafe: <link>" and
 * window.open on Yes. Two problems:
 *
 * 1. The document, visio and forms editors put the link into that warning
 *    unescaped, and so does the PDF editor's link warning
 *    (onOpenLinkPdfForm). Common.UI.alert renders msg with `<%= msg %>`, i.e.
 *    as HTML, so a hyperlink target like a<img src=x onerror=...> in a
 *    received .docx ran script in the editor frame - which has the
 *    AscDesktopEditor bridge - as soon as the warning appeared, before any
 *    answer (seen in a copy of the test app: window.__xss set by a link of a
 *    crafted links.docx, .rd-work/wt/ci-tmp). The cell and slide editors
 *    already encoded it. Now all of them do (Common.Utils.String.htmlEncode).
 *    (The visio warning also read this.txtWarnUrl inside setTimeout, i.e.
 *    window.txtWarnUrl: it threw and such links never opened; now me.txtWarnUrl.)
 *
 * 2. Yes then handed the link to window.open and the shell opened it with the
 *    system opener - a .app/.exe/.command included (that is the desktop-sdk
 *    half of this fix, issue-1664-doc-links/). The shell now asks itself, in a
 *    native dialog naming the target, before anything but http/https/mailto
 *    is opened, and refuses programs outright; so in the desktop app
 *    (Common.Controllers.Desktop.isActive()) the editors no longer ask first -
 *    the user answered twice otherwise. In a browser the warning is unchanged.
 *    The PDF editor keeps its own warning (it asks for every PDF link, http
 *    included), only encoded.
 *
 * This extracts by brace matching the REAL handlers (word/slide
 * DocumentHolderExt dh.onHyperlinkClick, cell dh.onApiHyperlinkClick, visio
 * DocumentHolder onHyperlinkClick, forms ApplicationController
 * onHyperlinkClick, pdf Main onOpenLinkPdfForm), the REAL format/htmlEncode
 * of common utils.js, renders the message through the REAL `<span><%= msg %>`
 * of Window.js's alert template with the repo's underscore, and runs them
 * against stubs (api.asc_getUrlType: Http for http(s), Email for mailto,
 * Unsafe otherwise; setTimeout runs at once).
 *
 * Claimed: no editor's link warning turns a link into markup; in a browser
 * the warning still comes for non-web links with 'no' first and opens on Yes
 * only; in the desktop app a non-web link goes straight to window.open (the
 * shell asks); http/mailto open at once in both.
 * NOT claimed: the shell's dialog (issue-1664-doc-links/), the mobile and
 * embed editors (not used by the desktop app; unchanged), real rendering.
 *
 * RD_WEBAPPS=<web-apps> (default ../web-apps). BASELINE=1 reads the sources
 * with git show at WEBAPPS_BASE_REF, where it must fail.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const WEBAPPS = process.env.RD_WEBAPPS || process.env.RD_REPO || path.join(ROOT, 'web-apps');
// Pinned to the parent of the commit that landed this fix, never HEAD.
const WEBAPPS_BASE_REF = process.env.WEBAPPS_BASE_REF || process.env.BASE_REF || '6b3b01aa96^';

function read(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', WEBAPPS, 'show', `${WEBAPPS_BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 28 })
		: fs.readFileSync(path.join(WEBAPPS, rel), 'utf8');
}

/* From the start of `marker` to the brace that closes the function body. */
function fnAt(text, marker) {
	const at = text.indexOf(marker);
	if (at < 0) throw new Error('not found: ' + marker);
	const open = text.indexOf('{', at);
	let depth = 0;
	for (let i = open; i < text.length; i++) {
		const c = text[i];
		if (c === '"' || c === "'") { const q = c; i++; while (text[i] !== q) i += text[i] === '\\' ? 2 : 1; continue; }
		if (c === '/' && text[i + 1] === '/') { i = text.indexOf('\n', i); continue; }
		if (c === '/' && text[i + 1] === '*') { i = text.indexOf('*/', i) + 1; continue; }
		if (c === '{') depth++;
		else if (c === '}' && --depth === 0) return 'function ' + text.slice(text.indexOf('(', at), i + 1);
	}
	throw new Error('unbalanced braces after ' + marker);
}

// underscore from the repo (the app ships this one)
const _ = (() => {
	const ctx = { module: { exports: {} } };
	ctx.exports = ctx.module.exports;
	vm.runInNewContext(fs.readFileSync(path.join(WEBAPPS, 'vendor/underscore/underscore.js'), 'utf8'), ctx);
	return ctx.module.exports._ || ctx.module.exports || ctx._;
})();

const utils = read('apps/common/main/lib/util/utils.js');
const windowJs = read('apps/common/main/lib/component/Window.js');
const MSG_TPL = '<span><%= msg %></span>';
if (windowJs.indexOf(MSG_TPL) < 0) throw new Error('Window.js alert no longer renders msg with ' + MSG_TPL + ' - revisit this test');

const sandbox = { _ };
vm.createContext(sandbox);
const format = vm.runInContext('(' + fnAt(utils, 'format: function (format)') + ')', sandbox);
const htmlEncode = vm.runInContext('(' + fnAt(utils, 'htmlEncode: function (string)') + ')', sandbox);

const URL_TYPE = { Invalid: 0, Http: 1, Email: 2, Unsafe: 3 };
function urlType(url) {
	if (/^https?:\/\//i.test(url)) return URL_TYPE.Http;
	if (/^mailto:/i.test(url)) return URL_TYPE.Email;
	return URL_TYPE.Unsafe;
}

const EDITORS = [
	{ name: 'word', file: 'apps/documenteditor/main/app/controller/DocumentHolderExt.js', marker: 'dh.onHyperlinkClick = function(url)', self: (s) => ({ documentHolder: { txtWarnUrl: s } }) },
	{ name: 'slide', file: 'apps/presentationeditor/main/app/controller/DocumentHolderExt.js', marker: 'dh.onHyperlinkClick = function(url)', self: (s) => ({ documentHolder: { txtWarnUrl: s } }) },
	{ name: 'cell', file: 'apps/spreadsheeteditor/main/app/controller/DocumentHolderExt.js', marker: 'dh.onApiHyperlinkClick = function(url)', self: (s) => ({ txtWarnUrl: s, errorInvalidLink: 'x', notcriticalErrorTitle: 'x', documentHolder: {} }) },
	{ name: 'visio', file: 'apps/visioeditor/main/app/controller/DocumentHolder.js', marker: 'onHyperlinkClick: function(url)', self: (s) => ({ txtWarnUrl: s }) },
	{ name: 'forms', file: 'apps/documenteditor/forms/app/controller/ApplicationController.js', marker: 'onHyperlinkClick: function(url)', self: (s) => ({ txtWarnUrl: s }) },
];
const WARN = 'This location may be unsafe:<br><br>{0}<br><br>Continue?';

// run one handler: returns {dialog: rendered html | null, opened: [urls], buttons, primary, threw}
function runEditor(ed, url, desktop, answer) {
	const src = fnAt(read(ed.file), ed.marker);
	const rec = { dialog: null, opened: [], buttons: null, primary: null, threw: null };
	const ctx = {
		_,
		AscCommon: { c_oAscUrlType: URL_TYPE },
		Common: {
			Utils: { String: { format, htmlEncode } },
			UI: {
				warning: (o) => { rec.dialog = _.template(MSG_TPL)(o); rec.buttons = o.buttons; rec.primary = o.primary; if (answer) o.callback(answer); },
				alert: (o) => { rec.dialog = _.template(MSG_TPL)(o); if (answer) o.callback(answer); },
			},
			Controllers: { Desktop: { isActive: () => desktop } },
			NotificationCenter: { trigger() {} },
		},
		console,
	};
	ctx.window = { open: (u) => { rec.opened.push(u); } };
	ctx.setTimeout = (f) => f();
	vm.createContext(ctx);
	// the handlers call window.open, not ctx.open
	vm.runInContext('var window = this.window;', ctx);
	const fn = vm.runInContext('(' + src + ')', ctx);
	const self = Object.assign(ed.self(WARN), { api: { asc_getUrlType: urlType } });
	try { fn.call(self, url); } catch (e) { rec.threw = String(e); }
	return rec;
}

function runPdf(url, answer) {
	const src = fnAt(read('apps/pdfeditor/main/app/controller/Main.js'), 'onOpenLinkPdfForm: function(sURI, onAllow, onCancel)');
	const rec = { dialog: null, opened: [], threw: null };
	const ctx = {
		_,
		Common: {
			Utils: { String: { format, htmlEncode } },
			UI: { alert: (o) => { rec.dialog = _.template(MSG_TPL)(o); rec.buttons = o.buttons; if (answer) o.callback(answer); return { $window: { attr() {} } }; } },
		},
	};
	vm.createContext(ctx);
	const fn = vm.runInContext('(' + src + ')', ctx);
	try { fn.call({ txtSecurityWarningLinkOk: 'Open {0}?', notcriticalErrorTitle: 'Warning' }, url, () => rec.opened.push(url), () => {}); } catch (e) { rec.threw = String(e); }
	return rec;
}

let failed = 0;
function check(label, ok, detail) {
	console.log((ok ? 'ok   ' : 'FAIL ') + label + (ok || !detail ? '' : '  -- ' + detail));
	if (!ok) failed++;
}

const EVIL = 'a<img src=x onerror="window.__xss=1">';
const FILE = 'file:///Users/me/Received/report.docx';

for (const ed of EDITORS) {
	// 1. browser: the warning comes, as text
	let r = runEditor(ed, EVIL, false, null);
	check(`${ed.name}: browser, markup in a link stays text in the warning`, !r.threw && r.dialog !== null && r.dialog.indexOf('<img') < 0 && r.dialog.indexOf('&lt;img') >= 0, r.threw || r.dialog);
	r = runEditor(ed, FILE, false, 'no');
	check(`${ed.name}: browser, file link asks with 'no' first and does not open on No`, !r.threw && r.dialog !== null && r.primary === 'no' && r.opened.length === 0, r.threw || JSON.stringify(r));
	r = runEditor(ed, FILE, false, 'yes');
	check(`${ed.name}: browser, file link opens on Yes`, !r.threw && r.opened.length === 1 && r.opened[0] === FILE, r.threw || JSON.stringify(r.opened));
	// 2. desktop: the shell asks; no second dialog here
	r = runEditor(ed, FILE, true, null);
	check(`${ed.name}: desktop, file link goes to the shell without an editor dialog`, !r.threw && r.dialog === null && r.opened.length === 1 && r.opened[0] === FILE, r.threw || JSON.stringify(r));
	r = runEditor(ed, EVIL, true, null);
	check(`${ed.name}: desktop, no editor dialog to inject into`, !r.threw && r.dialog === null, r.threw || r.dialog);
	// 3. web links unchanged
	for (const u of ['https://example.com/a?b=1', 'mailto:a@example.com']) {
		for (const d of [false, true]) {
			r = runEditor(ed, u, d, null);
			check(`${ed.name}: ${d ? 'desktop' : 'browser'}, ${u.split(':')[0]} opens at once`, !r.threw && r.dialog === null && r.opened.length === 1 && r.opened[0] === u, r.threw || JSON.stringify(r));
		}
	}
}

let p = runPdf(EVIL, null);
check('pdf: markup in a link stays text in the warning', !p.threw && p.dialog !== null && p.dialog.indexOf('<img') < 0 && p.dialog.indexOf('&lt;img') >= 0, p.threw || p.dialog);
p = runPdf('https://example.com/', 'ok');
check('pdf: warning still asks and opens on OK', !p.threw && p.dialog !== null && p.opened.length === 1, p.threw || JSON.stringify(p));
p = runPdf('https://example.com/', 'cancel');
check('pdf: Cancel does not open', !p.threw && p.opened.length === 0, p.threw || JSON.stringify(p));

console.log(failed ? `${failed} check(s) FAILED` : 'all checks passed');
process.exit(failed ? 1 : 0);

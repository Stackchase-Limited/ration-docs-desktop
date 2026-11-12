/*
 * #1674 - "need auto save instead of click save when closing": closing a
 * modified document always asks "Save / Don't Save / Cancel"; the reporter
 * wants the changes saved without the question.
 *
 * Today (unchanged by default): win-linux CMainWindow::trySaveDocument and
 * CEditorWindow::closeWindow, macOS -[ASCCommonViewController
 * requestSaveChangesForTab:] and -[ASCEditorWindowController shouldCloseWindow]
 * always show the question.
 *
 * Fix (desktop-apps): Settings > "Save changes automatically when closing a
 * document" (user setting save-on-close, off by default; settings:init/apply on
 * both platforms). When on, and the document is a local file we may write -
 * CAscTabData::canSaveInPlace() / +[NSCefData canSaveInPlace:] - the close takes
 * the "Save" branch without asking. The save is the ordinary one
 * (ASC_MENU_EVENT_TYPE_CEF_SAVE): desktop-sdk still opens Save As where it must
 * and writes through the #2000 safe-save path; the tab closes only after the
 * save succeeded. Anything else keeps the question.
 *
 * This test
 *  1. compiles the real +[NSCefData canSaveInPlace:] (brace-extracted, ARC,
 *     Foundation) and runs it on real files: a writable file -> YES; a file
 *     chmod 0444 -> NO; a folder, a missing file, a relative path, nil -> NO;
 *  2. compiles the real CAscTabData::canSaveInPlace() against minimal stubs of
 *     QString/QFileInfo (POSIX stat/access - Qt is not installed on this Mac)
 *     and checks the same cases plus: not local, opened read-only (features
 *     "readonly":true), empty url (new document) -> false;
 *  3. checks that all four close paths consult save-on-close and
 *     canSaveInPlace before they build the question (source order);
 *  4. loads the real panelsettings.js into jsdom: settings:init with
 *     saveonclose shows the switch, unchecked; ticking it and Apply sends
 *     saveonclose: true in settings:apply.
 *  Baseline: no canSaveInPlace, no switch -> FAILS.
 *
 * NOT claimed: the close paths themselves were not run (need a GUI check on
 * each platform: modify a .docx, close the tab / window / app with the switch on
 * and off, also a read-only file and a new document). Compiled: macOS clang
 * -fsyntax-only, Linux g++ -fsyntax-only (rd-linux-verify, Qt5); Windows not
 * compiled here (QFileInfo::isWritable does not see NTFS ACLs, only the
 * read-only attribute, without qt_ntfs_permission_lookup).
 *
 * Env: RD_REPO  desktop-apps checkout (default ../desktop-apps)
 *      RD_NODE_MODULES  where jsdom lives (default /Users/osindero/dev/active/node_modules)
 *      BASELINE=1 reads sources from BASE_REF via git show; must FAIL.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('assert');

const APPS = path.resolve(process.env.RD_REPO || path.join(__dirname, '..', 'desktop-apps'));
const BASE_REF = process.env.BASE_REF || '6093e48df^';
const NODE_MODULES = process.env.RD_NODE_MODULES || '/Users/osindero/dev/active/node_modules';

function src(rel) {
	return process.env.BASELINE
		? execFileSync('git', ['-C', APPS, 'show', `${BASE_REF}:${rel}`], { encoding: 'utf8', maxBuffer: 1 << 26 })
		: fs.readFileSync(path.join(APPS, rel), 'utf8');
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
function extract(text, marker, what) {
	const at = text.indexOf(marker);
	assert.ok(at !== -1, `${what}: not found - closing always asks`);
	return block(text, at);
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'issue1674-'));
try {
	// real files to ask about
	const rw = path.join(tmp, 'doc.docx'), ro = path.join(tmp, 'locked.docx'), dir = path.join(tmp, 'folder.docx');
	fs.writeFileSync(rw, 'x');
	fs.writeFileSync(ro, 'x');
	fs.chmodSync(ro, 0o444);
	fs.mkdirSync(dir);
	const missing = path.join(tmp, 'gone.docx');
	const CASES = [[rw, 1, 'writable file'], [ro, 0, 'read-only file'], [dir, 0, 'folder'],
		[missing, 0, 'missing file'], ['doc.docx', 0, 'relative path']];

	/* ---- 1. macOS ---- */
	const mm = src('macos/ONLYOFFICE/Code/Views/NSCefData.mm');
	const mac = extract(mm, '+(BOOL)canSaveInPlace:(NSString *)path {', 'macOS +[NSCefData canSaveInPlace:]');
	fs.writeFileSync(path.join(tmp, 'mac.m'), `
#import <Foundation/Foundation.h>
@interface NSCefData : NSObject
@end
@implementation NSCefData
${mac}
@end
int main(int argc, const char **argv) {
	@autoreleasepool {
		for (int i = 1; i < argc; ++i) printf("%d", [NSCefData canSaveInPlace:[NSString stringWithUTF8String:argv[i]]] ? 1 : 0);
		printf("%d\\n", [NSCefData canSaveInPlace:nil] ? 1 : 0);
	}
}`);
	execFileSync('clang', ['-fobjc-arc', '-w', '-framework', 'Foundation', '-o', path.join(tmp, 'mac'), path.join(tmp, 'mac.m')], { stdio: 'inherit' });
	const macOut = execFileSync(path.join(tmp, 'mac'), CASES.map(c => c[0]), { encoding: 'utf8' }).trim();
	const macWant = CASES.map(c => c[1]).join('') + '0';
	console.log(`macOS canSaveInPlace (${CASES.map(c => c[2]).join(', ')}, nil): ${macOut} want ${macWant}`);
	assert.strictEqual(macOut, macWant, 'macOS: wrong answer on whether a document can be saved in place');

	/* ---- 2. win-linux ---- */
	const cc = src('win-linux/src/casctabdata.cpp');
	const qt = extract(cc, 'bool CAscTabData::canSaveInPlace() const', 'win-linux CAscTabData::canSaveInPlace');
	fs.writeFileSync(path.join(tmp, 'qt.cpp'), `
#include <string>
#include <cstdio>
#include <sys/stat.h>
#include <unistd.h>
// minimal stand-ins for the two Qt classes used (POSIX semantics, as on Linux/macOS)
struct QString { std::string s; static QString fromStdWString(const std::wstring& w) { return QString{std::string(w.begin(), w.end())}; } };
struct QFileInfo {
	std::string p; explicit QFileInfo(const QString& q) : p(q.s) {}
	bool isAbsolute() const { return !p.empty() && p[0] == '/'; }
	bool isFile() const { struct stat st; return stat(p.c_str(), &st) == 0 && S_ISREG(st.st_mode); }
	bool isWritable() const { return access(p.c_str(), W_OK) == 0; }
};
struct CAscTabData {
	bool _is_local = true, _is_readonly = false;
	std::wstring _url;
	bool canSaveInPlace() const;
};
${qt}
int main(int argc, char **argv) {
	for (int i = 1; i < argc; ++i) { CAscTabData d; std::string a(argv[i]); d._url.assign(a.begin(), a.end()); printf("%d", d.canSaveInPlace()); }
	std::string a(argv[1]);
	CAscTabData notLocal; notLocal._url.assign(a.begin(), a.end()); notLocal._is_local = false;
	CAscTabData readOnly; readOnly._url.assign(a.begin(), a.end()); readOnly._is_readonly = true;
	CAscTabData fresh;
	printf(" %d%d%d\\n", notLocal.canSaveInPlace(), readOnly.canSaveInPlace(), fresh.canSaveInPlace());
}`);
	execFileSync('clang++', ['-std=c++14', '-w', '-o', path.join(tmp, 'qt'), path.join(tmp, 'qt.cpp')], { stdio: 'inherit' });
	const qtOut = execFileSync(path.join(tmp, 'qt'), CASES.map(c => c[0]), { encoding: 'utf8' }).trim();
	const qtWant = CASES.map(c => c[1]).join('') + ' 000';
	console.log(`win-linux canSaveInPlace (same; then not local, opened read-only, new): ${qtOut} want ${qtWant}`);
	assert.strictEqual(qtOut, qtWant, 'win-linux: wrong answer on whether a document can be saved in place');
} finally {
	fs.rmSync(tmp, { recursive: true, force: true });
}

/* ---- 3. the four close paths ask the setting before building the question ---- */
const PATHS = [
	['win-linux/src/windows/cmainwindow.cpp', 'int CMainWindow::trySaveDocument(int index)', 'CMessage::showMessage', 'canSaveInPlace()'],
	['win-linux/src/windows/ceditorwindow.cpp', 'int CEditorWindow::closeWindow()', 'CMessage::showMessage', 'canSaveInPlace()'],
	['macos/ONLYOFFICE/Code/Controllers/Common/ASCCommonViewController.mm', '- (void)requestSaveChangesForTab:(ASCTabView *)tab {', '[[NSAlert alloc] init]', 'canSaveInPlace:'],
	['macos/ONLYOFFICE/Code/Controllers/EditorWindow/ASCEditorWindowController.mm', '- (BOOL)shouldCloseWindow {', '[[NSAlert alloc] init]', 'canSaveInPlace:'],
];
for (const [file, sig, question, check] of PATHS) {
	const body = extract(src(file), sig, sig);
	const gate = body.indexOf('L"save-on-close") == L"1"');
	assert.ok(gate !== -1 && body.indexOf(check, gate) !== -1 && gate < body.indexOf(question),
		`${sig}: does not consult save-on-close before asking`);
	console.log(`${sig}: checks save-on-close + ${check} before the question`);
}

/* ---- 4. the setting ---- */
const { JSDOM } = require(path.join(NODE_MODULES, 'jsdom'));
const L = 'common/loginpage/';
const dom = new JSDOM(`<!doctype html><body>
	<div class="main-column tool-menu"></div><div class="main-column col-center"></div><div id="placeholder"></div>
	</body>`, { runScripts: 'dangerously', url: 'http://localhost/loginpage/index.html' });
const w = dom.window;
w.addEventListener('error', e => { w.__err = e.error; });
const run = (code) => {
	const s = w.document.createElement('script');
	s.textContent = code;
	w.document.body.appendChild(s);
	if (w.__err) throw w.__err;
};
run(fs.readFileSync(path.join(APPS, L + 'vendor/jquery/jquery.js'), 'utf8'));
run('jQuery.fn.selectpicker = function () { return this; };');
run(src(L + 'src/events.js'));
run(src(L + 'src/base.js'));
run(src(L + 'src/utils.js'));
run(src(L + 'src/locale.js'));
run(`
	utils.Lang = l10n.en; window.RendererProcessVariable = { theme: { id: 'theme-light', type: 'light' } };
	var _native = [], _sent = [];
	window.sdk = { on: function (ev, fn) { ev === 'on_native_message' && _native.push(fn); },
		command: function (c, p) { _sent.push([c, p]); }, GetLocalFeatures: function () { return false; } };
`);
run(src(L + 'src/panelsettings.js'));
run('(new ControllerSettings).init();');
w.eval('_native').forEach(fn => fn('settings:init', JSON.stringify({ keeprecents: true, saveonclose: false })));
const $sw = w.$('#sett-save-on-close');
assert.ok($sw.length && $sw.closest('.settings-field').css('display') !== 'none', 'Settings has no save-on-close switch');
assert.strictEqual($sw.prop('checked'), false, 'the switch must start off');
console.log(`switch "${w.$('label[for=sett-save-on-close]').text().trim()}" shown, checked=${$sw.prop('checked')}`);
$sw.prop('checked', true).trigger('change');
w.$('.sett-btn--apply').first().trigger('click');
const applied = w.eval('_sent').filter(c => c[0] === 'settings:apply').map(c => JSON.parse(c[1]));
console.log('settings:apply', JSON.stringify(applied[applied.length - 1]));
assert.ok(applied.length && applied[applied.length - 1].saveonclose === true, 'Apply does not hand save-on-close to the app');

console.log('PASS #1674: with the setting on, closing a modified local file we may write saves it without asking; anything else still asks');

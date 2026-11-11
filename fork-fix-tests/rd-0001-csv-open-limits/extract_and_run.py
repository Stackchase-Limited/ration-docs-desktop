#!/usr/bin/env python3
"""
#482 follow-up (ours, no upstream issue): a csv opened in the desktop app that x2t
had to cut - rows past 1048576 (AVS_FILEUTILS_ERROR_CONVERT_ROWLIMITS, exit 94) or
cell text past 32767 characters (..._CELLLIMITS, exit 96) - opened shortened
without a word, and saving over the csv lost the rest. Both codes count as success
(SUCCEEDED_X2T); the desktop open path stored the code in m_nLocalFileOpenError
(CCefView_Private::OnFileConvertToEditor) and LocalFile_End dropped it.
web-apps 7ddbfa80c2 warns about rows from the csv dialog's own preview; cell text
was never reported.

Now: LocalFile_End passes 94/96 as argument 5 of "onlocaldocument_loadend"; the
renderer (client_renderer_wrapper.cpp) calls on_native_message("file:openlimits",
code) in the editor frame after the document is handed over; web-apps Desktop.js
passes it to the spreadsheet Main controller, whose onDesktopOpenLimits shows
warnOpenRowLimit / warnOpenCellLimit once the sheet is on screen (deferred to
onDocumentContentReady while loading), and skips the rows one when the csv dialog
already showed warnCsvRowLimit.

The chain is run on the REAL code, lifted out by brace matching:
  desktop-sdk cefview.cpp CCefView_Private::LocalFile_End (stub CEF message,
    lock check, handler) -> the arguments it sends;
  client_renderer_wrapper.cpp, the whole "onlocaldocument_loadend" branch (stub
    CEF frame recording ExecuteJavaScript) -> the JS it runs;
  that JS, evaluated in Node against web-apps Desktop.js's "file:openlimits"
    branch of on_native_message and Main.js's onDesktopOpenLimits, the
    openLimits block of onDocumentContentReady and the warn* strings, with
    Common.UI.warning recording what is shown.
Cases: 94 and 96 reach a warning (after load); 0 and 89 send nothing; 94 after
the dialog's own row warning shows nothing more, 96 still does.

  RD_REPO=<desktop-sdk checkout>  default ../../desktop-sdk
  RD_WEBAPPS=<web-apps checkout>  default ../../web-apps
  BASELINE=1   read both at BASE_REF / WEBAPPS_BASE_REF; must FAIL
  BASE_REF (desktop-sdk) default 95c61da6^, WEBAPPS_BASE_REF default ffc735fa93^

NOT claimed: x2t's side (core 9eed63b760, checked by running x2t), the CEF IPC
itself, the warning's look and its timing against the load mask in the real app
(needs a GUI check), the other editors (only the spreadsheet controller listens).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DSDK = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
WEBAPPS = os.environ.get('RD_WEBAPPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'web-apps'))
BASE_REF = os.environ.get('BASE_REF', '95c61da6^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', 'ffc735fa93^')
BASELINE = bool(os.environ.get('BASELINE'))

results = []


def report(ok, what):
    results.append(ok)
    print(('ok   ' if ok else 'FAIL ') + what)


def read(repo, ref, rel):
    if BASELINE:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig')
    return open(os.path.join(repo, rel), encoding='utf-8-sig').read()


def block(text, start, opener='{'):
    a = text.find(start)
    if a < 0:
        return None
    a = text.rfind('\n', 0, a) + 1
    i = text.find(opener, text.find(start))
    close = '}' if opener == '{' else ')'
    depth = 0
    while i < len(text):
        c = text[i]
        if c in '"\'':
            q = c
            i += 1
            while text[i] != q:
                i += 2 if text[i] == '\\' else 1
        elif c == '/' and text[i + 1] == '/':
            i = text.find('\n', i)
            continue
        elif c == opener:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    return None


CPP = r'''
#include <string>
#include <vector>
#include <map>
#include <cstdio>
#define CEF_V8_SUPPORT_TYPED_ARRAYS
#define U_TO_UTF8(w) std::string((w).begin(), (w).end())
struct CefString {
	std::wstring w;
	CefString() {}
	CefString(const std::wstring& s) : w(s) {}
	std::wstring ToWString() const { return w; }
	std::string ToString() const { return std::string(w.begin(), w.end()); }
};
struct ArgList {
	std::map<int, std::wstring> s; std::map<int, int> i; std::map<int, bool> b; size_t n = 0;
	void t(int k) { if ((size_t)k + 1 > n) n = k + 1; }
	void SetString(int k, const std::wstring& v) { s[k] = v; t(k); }
	void SetString(int k, const std::string& v) { s[k] = std::wstring(v.begin(), v.end()); t(k); }
	void SetBool(int k, bool v) { b[k] = v; t(k); }
	void SetInt(int k, int v) { i[k] = v; t(k); }
	CefString GetString(int k) { return CefString(s[k]); }
	bool GetBool(int k) { return b[k]; }
	int GetInt(int k) { return i[k]; }
	size_t GetSize() { return n; }
};
struct CefProcessMessage {
	std::string name; ArgList args;
	ArgList* GetArgumentList() { return &args; }
	static CefProcessMessage* Create(const std::string& n) { CefProcessMessage* m = new CefProcessMessage(); m->name = n; return m; }
};
template <class T> using CefRefPtr = T*;
struct CefFrame {
	std::vector<std::string> js;
	std::string GetURL() { return "file:///index.html"; }
	void ExecuteJavaScript(const std::string& s, const std::string&, int) { js.push_back(s); }
	void ExecuteJavaScript(const std::wstring& s, const std::string&, int) { js.push_back(std::string(s.begin(), s.end())); }
};
struct CefBrowser {
	CefFrame frame; CefProcessMessage* sent = nullptr;
	CefFrame* GetMainFrame() { return &frame; }
	void SendProcessMessage(int, CefProcessMessage* m) { sent = m; }
};
#define SEND_MESSAGE_TO_RENDERER_PROCESS(browser, message) (browser)->SendProcessMessage(0, message)
namespace NSSystem {
	enum class LockType { ltNone = 0, ltLocked = 1 };
	struct CLocalFileLocker { static LockType IsLocked(const std::wstring&) { return LockType::ltNone; } };
}
namespace NSStringUtils { void string_replace(std::wstring&, const std::wstring&, const std::wstring&) {} }
namespace NSFile {
	std::wstring GetFileName(const std::wstring& s) { return s; }
	struct CFileBinary {
		static bool Exists(const std::wstring&) { return false; }
		static bool ReadAllTextUtf8A(const std::wstring&, std::string&) { return false; }
	};
}
std::string GetFileData(const std::wstring&, int& n) { n = 4; return "DATA"; }
std::string GetFileData2(const std::wstring&, int& n) { n = 4; return "DATA"; }
CefFrame* GetEditorFrame(CefBrowser* b) { return &b->frame; }

struct TInfo { std::wstring m_sFileSrc = L"/tmp/a.csv", m_sRecoveryDir = L"/tmp/rec"; bool m_bIsSaved = true; int m_nCounterConvertion = 0; };
struct TLocalInfo { TInfo m_oInfo; };
struct TConverter { std::wstring m_sName; std::wstring GetSignaturesJSON() { return L""; } };
struct THandler { CefBrowser* b; CefBrowser* GetBrowser() { return b; } };
struct CCefView_Private {
	TConverter m_oConverterToEditor; TLocalInfo m_oLocalInfo; bool m_bIsCloudCryptFile = false;
	THandler* m_handler = nullptr; int m_nLocalFileOpenError = 0;
	void CheckLockLocalFile() {}
	void LocalFile_End();
};
LOCALFILE_END

bool Renderer(CefBrowser* browser, const std::string& sMessageName, CefProcessMessage* message)
{
	if (false) {}
RENDERER_BRANCH
	return false;
}

int main()
{
	int codes[] = { 0, 89, 94, 96 };
	printf("[");
	for (int k = 0; k < 4; ++k)
	{
		CefBrowser oBrowserProcess, oRenderer;
		THandler h{&oBrowserProcess};
		CCefView_Private v; v.m_handler = &h; v.m_nLocalFileOpenError = codes[k];
		v.LocalFile_End();
		CefProcessMessage* m = oBrowserProcess.sent;
		Renderer(&oRenderer, m->name, m);
		printf("%s{\"code\":%d,\"args\":%d,\"arg5\":%d,\"js\":[", k ? "," : "", codes[k], (int)m->args.GetSize(), m->args.GetInt(5));
		for (size_t j = 0; j < oRenderer.frame.js.size(); ++j)
		{
			std::string s = oRenderer.frame.js[j], e;
			for (char c : s) { if (c == '"' || c == '\\') e += '\\'; if (c == '\n') { e += "\\n"; continue; } e += c; }
			printf("%s\"%s\"", j ? "," : "", e.c_str());
		}
		printf("]}");
	}
	printf("]\n");
	return 0;
}
'''

JS = r'''
const runs = JSON.parse(process.argv[2]);
const P = JSON.parse(process.argv[3]);
const shown = [];
const Common = { UI: { warning: (o) => shown.push(o.msg) } };
const main = eval('({' + P.method + ',' + P.strings + ', maxSheetRows: 1048576, notcriticalErrorTitle: "Warning"})');
main._state = {};
main._isDocReady = false;
const webapp = { getController: (n) => n === 'Main' ? main : null };
const window = {};
window.on_native_message = function (cmd, param) { eval(P.branch); };
const docReady = function () { const me = this; eval(P.ready); };
const out = {};
for (const r of runs) {
	shown.length = 0;
	main._state = {}; main._isDocReady = false;
	for (const s of r.js) if (/on_native_message/.test(s)) eval(s);
	const whileLoading = shown.length;
	main._isDocReady = true; docReady.call(main);
	out[r.code] = { whileLoading: whileLoading, shown: shown.slice() };
	// the csv dialog's own row warning already showed
	shown.length = 0;
	main._state = { csvRowLimitWarned: true }; main._isDocReady = true;
	for (const s of r.js) if (/on_native_message/.test(s)) eval(s);
	out[r.code].afterDialog = shown.slice();
}
console.log(JSON.stringify(out));
'''


def main():
    print(('BASELINE %s / %s' % (BASE_REF, WEBAPPS_BASE_REF)) if BASELINE else ('repos ' + DSDK + ' , ' + WEBAPPS))
    cef = read(DSDK, BASE_REF, 'ChromiumBasedEditors/lib/src/cefview.cpp')
    rend = read(DSDK, BASE_REF, 'ChromiumBasedEditors/lib/src/cefwrapper/client_renderer_wrapper.cpp')
    lfe = block(cef, 'void CCefView_Private::LocalFile_End()\n{')
    br = block(rend, 'else if (sMessageName == "onlocaldocument_loadend")')
    if not lfe or not br:
        sys.exit('desktop-sdk extractor needs updating')
    src = CPP.replace('LOCALFILE_END', lfe).replace('RENDERER_BRANCH', br)
    with tempfile.TemporaryDirectory() as work:
        p = os.path.join(work, 't.cpp')
        open(p, 'w').write(src)
        r = subprocess.run(['c++', '-std=c++14', '-w', p, '-o', os.path.join(work, 't')], capture_output=True, text=True)
        if r.returncode:
            sys.exit('compile failed:\n' + r.stderr[-3000:])
        runs = json.loads(subprocess.run([os.path.join(work, 't')], capture_output=True, text=True, check=True).stdout)

        mainjs = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/spreadsheeteditor/main/app/controller/Main.js')
        desk = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/common/main/lib/controller/Desktop.js')
        method = block(mainjs, 'onDesktopOpenLimits: function(code) {')
        ready = block(mainjs, "if (me._state.openLimits) {")
        branch = block(desk, "if (/^file:openlimits$/.test(cmd)) {")
        strings = ','.join(m.group(0) for m in re.finditer(r"warnOpen(Row|Cell)Limit: '[^'\n]*'", mainjs))
        for r_ in runs:
            send = any('file:openlimits' in s for s in r_['js'])
            want = r_['code'] in (94, 96)
            report(send == want and (r_['arg5'] == r_['code'] if want else r_['arg5'] == 0),
                   'x2t code %d: LocalFile_End arg5=%d, renderer %s file:openlimits' % (r_['code'], r_['arg5'], 'sends' if send else 'does not send'))
        if not (method and ready and branch and strings):
            report(False, 'web-apps: Desktop.js file:openlimits / Main.js onDesktopOpenLimits not found')
        else:
            jp = os.path.join(work, 't.js')
            open(jp, 'w').write(JS)
            P = {'method': method.strip(), 'ready': ready.strip(), 'branch': branch.strip(), 'strings': strings}
            r = subprocess.run(['node', jp, json.dumps(runs), json.dumps(P)], capture_output=True, text=True)
            if r.returncode:
                report(False, 'web-apps JS failed: ' + r.stderr[-1500:])
            else:
                out = json.loads(r.stdout)
                for code, needle in (('94', 'more rows than a sheet holds'), ('96', 'more than 32767 characters')):
                    o = out[code]
                    report(o['whileLoading'] == 0 and len(o['shown']) == 1 and needle in o['shown'][0],
                           'x2t code %s: %d warning(s) while loading, then: %s' % (code, o['whileLoading'], ' | '.join(s[:60] for s in o['shown']) or 'nothing'))
                report(out['0']['shown'] == [] and out['89']['shown'] == [], 'codes 0 / 89: no warning')
                report(out['94']['afterDialog'] == [], 'code 94 after the csv dialog already warned about rows: nothing more')
                report(len(out['96']['afterDialog']) == 1, 'code 96 after the csv dialog row warning: still warned')
    ok = all(results)
    print('PASSED' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


main()

#!/usr/bin/env python3
"""
#200 - "add File > New or Ctrl+N": no shortcut made a new document from an editor.

macOS already has one (checked in the running test app): File > New > Document /
Spreadsheet / Presentation / PDF Form on Ctrl+Shift+D/S/P/T; Ctrl+Shift+D through
the main menu's performKeyEquivalent: opened a new document tab. Not changed.

Windows/Linux had nothing: the ONKEYBOARDDOWN handler knew Alt+F4 and Ctrl+O, and
Ctrl+N fell through (the editors use Ctrl+N only as a bare "N" in the paste
options menu, so it is free).

Now Ctrl+N in an editor sends the same "create:new" command, with the same
sender id, that the editor's own File > Create New sends - so the new document
is of the editor's type (word/cell/slide) and opens where that command opens it
(a tab, or a window for an editor in its own window). The start page and
editors with nothing to create (PDF, diagrams) leave the key alone.

This compiles the real CAscApplicationManagerWrapper_Private::sendCreateNewEvent
(cascapplicationmanagerwrapper_private.h) and the real Key_N case of the key
handler (cascapplicationmanagerwrapper.cpp), extracted by brace matching, against
stand-ins for the windows, panels and the event sink, and checks which command
leaves for which editor.

NOT claimed: the running Windows/Linux app (needs a GUI check: the key reaches
the shell as CEF's ONKEYBOARDDOWN, like Ctrl+O; the "create:new" handling it
feeds is unchanged).

BASELINE=1 reads both files from BASE_REF (the parent of the fix): there is no
such case or function, so it fails.
"""
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', '283bb57d3f^')
BASELINE = bool(os.environ.get('BASELINE'))
PRIV = 'win-linux/src/cascapplicationmanagerwrapper_private.h'
WRAP = 'win-linux/src/cascapplicationmanagerwrapper.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def brace_match(src, at):
    open_brace = src.index('{', at)
    depth = 0
    for i in range(open_brace, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces')


print('#200 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO))
priv, wrap = read(PRIV), read(WRAP)
at = priv.find('auto sendCreateNewEvent(int id) -> bool')
at2 = wrap.find('case 0x4e:')
if at == -1 or at2 == -1:
    print('  no Ctrl+N handling: sendCreateNewEvent %s, Key_N case %s' %
          ('present' if at != -1 else 'missing', 'present' if at2 != -1 else 'missing'))
    print('\nFAILED')
    sys.exit(1)
method = brace_match(priv, at)
keycase = wrap[at2:wrap.index('break;', at2) + len('break;')]

HARNESS = r'''
#include <string>
#include <vector>
#include <stdio.h>
#define ASC_MENU_EVENT_TYPE_CEF_EXECUTE_COMMAND 1
enum class AscEditorType { etUndefined, etDocument, etSpreadsheet, etPresentation, etPdf, etDraw };
namespace NSEditorApi {
    struct CAscExecCommand { std::wstring c, p; void put_Command(const std::wstring& s) { c = s; } void put_Param(const std::wstring& s) { p = s; } };
    struct CAscCefMenuEvent { int m_nType; void * m_pData = nullptr; int m_nSenderId = -1; CAscCefMenuEvent(int t) : m_nType(t) {} };
}
struct CAscTabData { AscEditorType t; AscEditorType contentType() const { return t; } };
struct CTabPanel { CAscTabData d; CAscTabData * data() { return &d; } };
struct CEditorWindow { CTabPanel p; CTabPanel * mainView() { return &p; } };
struct CAscTabWidget {
    std::vector<std::pair<int, CTabPanel>> tabs;
    int tabIndexByView(int id) { for (size_t i = 0; i < tabs.size(); ++i) if (tabs[i].first == id) return int(i); return -1; }
    CTabPanel * panel(int i) { return &tabs[size_t(i)].second; }
};
struct CMainWindow {
    int startPage = 1; CAscTabWidget tw;
    bool holdView(int id) { return id == startPage || tw.tabIndexByView(id) >= 0; }
    CAscTabWidget * tabWidget() { return &tw; }
};
static CMainWindow g_main;
static CMainWindow * mainWindow() { return &g_main; }
struct Sent { std::wstring cmd, param; int sender; };
static std::vector<Sent> g_sent;
struct AppManager {
    CEditorWindow win; int winViewId = 40;
    CEditorWindow * editorWindowFromViewId(int id) { return id == winViewId ? &win : nullptr; }
    void OnEvent(NSEditorApi::CAscCefMenuEvent * e) {
        auto * d = static_cast<NSEditorApi::CAscExecCommand *>(e->m_pData);
        g_sent.push_back({d->c, d->p, e->m_nSenderId}); delete d; delete e;
    }
};
struct Private {
    AppManager m_appmanager;
    %(method)s
};
struct Key { int k; bool c, s, a; int get_KeyCode() const { return k; } bool get_IsCtrl() const { return c; }
             bool get_IsShift() const { return s; } bool get_IsAlt() const { return a; } };
struct Event { int id; int get_SenderId() const { return id; } };
static Private g_priv; static Private * m_private = &g_priv;
static bool onKey(int sender, int key, bool ctrl, bool shift, bool alt) {
    Key k{key, ctrl, shift, alt}; Key * data = &k; Event ev{sender}; Event * event = &ev;
    switch ( data->get_KeyCode() ) {
    %(keycase)s
    default: break;
    }
    return false;
}
static int failures = 0;
static void expect(int sender, int key, bool c, bool s, bool a, const wchar_t * want, const char * what) {
    g_sent.clear();
    bool handled = onKey(sender, key, c, s, a);
    std::wstring got = g_sent.empty() ? L"-" : g_sent[0].cmd + L" " + g_sent[0].param;
    bool ok = got == want && handled == (want[0] != L'-') && (g_sent.empty() || g_sent[0].sender == sender);
    printf("  %%-52s -> %%-18ls %%s\n", what, got.c_str(), ok ? "ok" : "FAILED");
    if (!ok) failures++;
}
int main() {
    g_main.tw.tabs = { {10, {{AscEditorType::etDocument}}}, {11, {{AscEditorType::etSpreadsheet}}},
                       {12, {{AscEditorType::etPresentation}}}, {13, {{AscEditorType::etPdf}}} };
    g_priv.m_appmanager.win.p.d.t = AscEditorType::etSpreadsheet;
    expect(10, 0x4e, true, false, false, L"create:new word",  "Ctrl+N in a document tab");
    expect(11, 0x4e, true, false, false, L"create:new cell",  "Ctrl+N in a spreadsheet tab");
    expect(12, 0x4e, true, false, false, L"create:new slide", "Ctrl+N in a presentation tab");
    expect(40, 0x4e, true, false, false, L"create:new cell",  "Ctrl+N in a spreadsheet in its own window");
    expect(13, 0x4e, true, false, false, L"-",                "Ctrl+N in the PDF editor: nothing");
    expect(1,  0x4e, true, false, false, L"-",                "Ctrl+N on the start page: nothing");
    expect(10, 0x4e, true, true,  false, L"-",                "Ctrl+Shift+N: nothing");
    expect(10, 0x4e, true, false, true,  L"-",                "Ctrl+Alt+N: nothing");
    expect(10, 0x4e, false, false, false, L"-",               "N alone: nothing");
    printf("\n%%s\n", failures ? "FAILED" : "ok - Ctrl+N creates a new document of the editor's type");
    return failures ? 1 : 0;
}
''' % {'method': method, 'keycase': keycase}

with tempfile.TemporaryDirectory() as tmp:
    src, exe = os.path.join(tmp, 'h.cpp'), os.path.join(tmp, 'h')
    open(src, 'w').write(HARNESS)
    cxx = 'clang++' if platform.system() == 'Darwin' else 'c++'
    c = subprocess.run([cxx, '-std=c++14', '-w', '-o', exe, src], capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.stdout.flush()
    sys.exit(subprocess.run([exe]).returncode)

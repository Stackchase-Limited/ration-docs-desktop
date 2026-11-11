#!/usr/bin/env python3
"""
#905 - "Inserting images via Drag'n'drop not working on Linux" (also #616, #275).

Drag and drop on Linux was added upstream in 2023 (desktop-sdk 405e1864 "drag'n'drop
inside QCefView", f3181f31 "dnd class"): QCefView takes the Qt drop, the browser
process records the dropped paths (set_drop_files) and the renderer builds a JS
script (CAscDragDrop::CreateEvent) that dispatches a synthetic "drop" event into
the editor. So the report as filed (6.x/7.x: nothing is accepted) is out of date.
Two defects remain in that code, both making a drop silently do nothing or
corrupting what is dropped:

 1. qt_wrapper/src/qcefview.cpp QCefView::convertMimeData turned each dropped
    URL into a path with QUrl::toString() and a "file://" strip. A file manager
    sends RFC 2483 percent-encoded URIs and toString() leaves %23 (#), %25 (%)
    and %3F (?) encoded, so "a#b.png" became "/.../a%23b.png", a file that does
    not exist: IsImageFile() is false and the image is not inserted. Now
    toLocalFile() for local URLs.
 2. src/cefwrapper/client_renderer_wrapper.cpp CAscDragDrop::CreateEvent put
    the dropped text/html into JS string literals after DELETING \\r and \\n (a
    literal newline would end the string), so a dropped multi-line text was
    pasted as one joined line. The file name went into a literal unescaped, so a
    name with a quote or backslash made the whole script a syntax error and the
    drop did nothing. Now both are escaped (\\\\, \\", \\r, \\n, U+2028/2029).

This compiles the REAL convertMimeData (sliced from qcefview.cpp, the real
CAscLocalDragDropData from include/applicationmanager_events.h, real Qt5 QtCore
QMimeData/QUrl) and the REAL CAscDragDrop class (sliced from
client_renderer_wrapper.cpp, with minimal CEF stubs and core's real
NSStringUtils::string_replace), then runs the generated script in node with a
fake DOM and checks what the editor's ondrop handler would receive.

Claimed: decoded paths for %, #, ?, spaces and UTF-8; dropped text keeps its
line breaks; names with quotes/backslashes reach the event intact.
NOT claimed: the X11/XDND hand-off from the file manager to QCefView, or the
editor inserting the picture - that needs a Linux GUI run (no Linux app build
here). file://localhost/ URLs are not handled specially (Qt gives //localhost/...).

  python3 fork-fix-tests/issue-905-linux-drop/extract_and_run.py
  RD_REPO=<desktop-sdk checkout>  (default ../../desktop-sdk)
  RD_CORE=<core checkout>         (default ../../core; read only: string_replace, GetFileName)
  QT5_PREFIX=<qt5>                (default: brew --prefix qt@5, or pkg-config Qt5Core on Linux)
  BASELINE=1                      reads desktop-sdk sources from BASE_REF; must FAIL.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '11818b60^')
BASELINE = bool(os.environ.get('BASELINE'))

QCEF = 'ChromiumBasedEditors/lib/qt_wrapper/src/qcefview.cpp'
RENDER = 'ChromiumBasedEditors/lib/src/cefwrapper/client_renderer_wrapper.cpp'
EVENTS = 'ChromiumBasedEditors/lib/include/applicationmanager_events.h'


def read(rel, repo=REPO, baseline=BASELINE):
    if baseline:
        return subprocess.check_output(['git', '-C', repo, 'show', BASE_REF + ':' + rel]).decode('utf-8')
    with open(os.path.join(repo, rel), encoding='utf-8') as f:
        return f.read()


def braces(src, start):
    """src[start:] up to the brace closing the first '{' after start."""
    o = src.index('{', start)
    d = 0
    for i in range(o, len(src)):
        if src[i] == '{':
            d += 1
        elif src[i] == '}':
            d -= 1
            if d == 0:
                return src[start:i + 1]
    raise SystemExit('unbalanced braces')


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit('command failed: ' + ' '.join(cmd[:3]))
    return r.stdout


def qt_flags():
    if platform.system() == 'Darwin':
        prefix = os.environ.get('QT5_PREFIX') or subprocess.check_output(['brew', '--prefix', 'qt@5']).decode().strip()
        fw = os.path.join(prefix, 'lib')
        return ['-F' + fw, '-I' + os.path.join(fw, 'QtCore.framework', 'Headers')], ['-F' + fw, '-framework', 'QtCore', '-Wl,-rpath,' + fw]
    c = subprocess.check_output(['pkg-config', '--cflags', 'Qt5Core']).decode().split()
    l = subprocess.check_output(['pkg-config', '--libs', 'Qt5Core']).decode().split()
    return c + ['-fPIC'], l


failures = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + detail) if detail and not cond else ''))
    if not cond:
        failures.append(name)


tmp = tempfile.mkdtemp(prefix='rd905-')
try:
    # ------------------------------------------------------------ 1. convertMimeData
    qsrc = read(QCEF)
    at = qsrc.index('NSEditorApi::CAscLocalDragDropData* QCefView::convertMimeData(')
    fn = braces(qsrc, at).replace('QCefView::convertMimeData', 'convertMimeData')
    assert 'pMimeData->urls()' in fn and 'put_Html' in fn, 'sliced the wrong function'
    events = read(EVENTS)
    with open(os.path.join(tmp, 'applicationmanager_events.h'), 'w') as f:
        f.write(events)
    uris = [
        ('plain', 'file:///home/u/Pictures/photo.png', '/home/u/Pictures/photo.png'),
        ('space+utf8', 'file:///home/u/My%20Pictures/caf%C3%A9.png', '/home/u/My Pictures/café.png'),
        ('hash', 'file:///home/u/a%23b.png', '/home/u/a#b.png'),
        ('percent', 'file:///home/u/100%25.png', '/home/u/100%.png'),
        ('question', 'file:///home/u/what%3F.png', '/home/u/what?.png'),
    ]
    main = r'''
#include <QMimeData>
#include <QUrl>
#include <QString>
#include <cstdio>
#include "applicationmanager_events.h"
''' + fn + r'''
int main(int argc, char** argv)
{
    for (int i = 1; i < argc; i++)
    {
        QMimeData m;
        m.setData("text/uri-list", QByteArray(argv[i]) + "\r\n");
        NSEditorApi::CAscLocalDragDropData* p = convertMimeData(&m);
        std::wstring s = p->get_Files().empty() ? L"<none>" : p->get_Files()[0];
        printf("%s\n", QString::fromStdWString(s).toUtf8().constData());
        delete p;
    }
    return 0;
}
'''
    with open(os.path.join(tmp, 'mime.cpp'), 'w') as f:
        f.write(main)
    cf, lf = qt_flags()
    run(['c++', '-std=c++17', '-I' + tmp] + cf + [os.path.join(tmp, 'mime.cpp'), '-o', os.path.join(tmp, 'mime')] + lf)
    out = run([os.path.join(tmp, 'mime')] + [u for _, u, _ in uris]).split('\n')
    for (name, uri, want), got in zip(uris, out):
        check('drop path ' + name + ': ' + uri, got == want, 'got ' + repr(got))

    # ------------------------------------------------------------ 2. CAscDragDrop::CreateEvent
    rsrc = read(RENDER)
    at = rsrc.index('\tclass CAscDragDrop\n')
    cls = braces(rsrc, at) + ';'
    assert 'CreateEvent' in cls and 'addFileToDataTransfer' in cls, 'sliced the wrong class'
    core_sb = read('DesktopEditor/common/StringBuilder.cpp', repo=CORE, baseline=False)
    sr = braces(core_sb, core_sb.index('void string_replace(std::wstring& text'))
    core_file = read('DesktopEditor/common/File.cpp', repo=CORE, baseline=False)
    gfn = braces(core_file, core_file.index('std::wstring GetFileName(const std::wstring& sPath)'))
    stubs = r'''
#include <string>
#include <vector>
#include <cstdio>
#include <cstdlib>
#include <locale>
#include <codecvt>
namespace NSStringUtils { ''' + sr + r''' }
namespace NSFile { ''' + gfn + r''' }
// not under test: the bytes of the file (a 1x1 PNG header is enough)
std::string GetFileBase64(const std::wstring&, int* outSize = NULL) { if (outSize) *outSize = 8; return "iVBORw0KGgo="; }
#define UTF8_TO_U(val) std::wstring((val).begin(), (val).end())
struct CefString {
    std::wstring s; CefString() {} CefString(const std::wstring& v) : s(v) {}
    std::wstring ToWString() const { return s; } operator std::wstring() const { return s; }
};
struct CefListValue {
    std::vector<int> ints; std::vector<std::wstring> strs; size_t n = 0;
    int GetInt(size_t i) { return ints[i]; }
    CefString GetString(size_t i) { return CefString(strs[i]); }
    size_t GetSize() { return n; }
};
template <class T> struct CefRefPtr {
    T* p = nullptr; CefRefPtr() {} CefRefPtr(T* v) : p(v) {}
    T* operator->() const { return p; } T* get() const { return p; }
};
struct CefProcessMessage {
    CefListValue args;
    CefRefPtr<CefListValue> GetArgumentList() { return CefRefPtr<CefListValue>(&args); }
    CefRefPtr<CefProcessMessage> Copy() { return CefRefPtr<CefProcessMessage>(new CefProcessMessage(*this)); }
};
'''
    main2 = stubs + cls + r'''
static std::wstring u8(const char* s) { return std::wstring_convert<std::codecvt_utf8<wchar_t>>().from_bytes(s); }
int main(int argc, char** argv)
{
    // argv: text html file...
    CefProcessMessage m;
    m.args.ints = {10, 20, 110, 120, 0, 0};
    m.args.strs = {L"", L"", L"", L"", u8(argv[1]), u8(argv[2])};
    for (int i = 3; i < argc; i++) m.args.strs.push_back(u8(argv[i]));
    m.args.n = m.args.strs.size();
    CefRefPtr<CefProcessMessage> pm(&m);
    CAscDragDrop d(pm);
    std::wstring code = d.CreateEvent(L"drop");
    printf("%s", std::wstring_convert<std::codecvt_utf8<wchar_t>>().to_bytes(code).c_str());
    return 0;
}
'''
    with open(os.path.join(tmp, 'dnd.cpp'), 'w') as f:
        f.write(main2)
    run(['c++', '-std=c++17', '-Wno-deprecated-declarations', os.path.join(tmp, 'dnd.cpp'), '-o', os.path.join(tmp, 'dnd')])

    js_runner = r'''
// runs the generated drop script against a fake DOM and prints what the target got
const code = require('fs').readFileSync(process.argv[2], 'utf8');
let got = null;
const document = { elementFromPoint: () => ({ dispatchEvent: e => { got = e; } }) };
const res = { syntaxError: null };
try { new Function('document', code)(document); } catch (e) { res.syntaxError = String(e); }
if (got) {
  res.text = got.dataTransfer.getData('text/plain');
  res.html = got.dataTransfer.getData('text/html');
  res.files = got.dataTransfer.files.map(f => f.name);
}
console.log(JSON.stringify(res));
'''
    with open(os.path.join(tmp, 'run.js'), 'w') as f:
        f.write(js_runner)

    import json

    def drop(text, html, files):
        code = run([os.path.join(tmp, 'dnd'), text, html] + files)
        p = os.path.join(tmp, 'code.js')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(code)
        return json.loads(run(['node', p.replace('code.js', 'run.js'), p]))

    text = 'line 1\nline 2\r\nline "3" \\ end'
    r = drop(text, '', [])
    check('dropped text: script runs', r.get('syntaxError') is None, str(r.get('syntaxError')))
    check('dropped text keeps its line breaks', r.get('text') == text, 'got ' + repr(r.get('text')))

    html = '<pre>a\nb</pre>'
    r = drop('', html, [])
    check('dropped html keeps <pre> line breaks', r.get('html') == html, 'got ' + repr(r.get('html')))

    for name in ['/home/u/plain.png', '/home/u/my "best" photo.png', '/home/u/back\\slash.png']:
        r = drop('', '', [name])
        ok = r.get('syntaxError') is None and r.get('files') == [name.rsplit('/', 1)[1]]
        check('dropped file name ' + repr(name.rsplit('/', 1)[1]) + ' reaches the event', ok, json.dumps(r))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
sys.exit(1 if failures else 0)

#!/usr/bin/env python3
"""
#1167 - "Opening Google Docs file opens Google Docs editor inside ONLYOFFICE" (Linux,
GNOME Files with a Google Drive online account).

Cause.  gvfs's google backend shows a native Google document (Docs/Sheets/Slides) as a
shortcut with no content; its target URI is the document's docs.google.com page, and
Nautilus "Open with" passes that https link to the app.  handleInputCmd
(desktop-apps win-linux/src/cascapplicationmanagerwrapper.cpp) opens any http(s)
argument as a web page in a tab (open_scheme), so Google's own editor showed up inside
the app.  There is no file our editors could open: exporting needs the user's Google
sign-in.

Fix.  isGoogleNativeDocumentUrl() recognises http(s) links whose host is
docs.google.com or drive.google.com, and handleInputCmd hands those to Utils::openUrl
(xdg-open / the system browser) instead of opening a tab.

What this runs.  The REAL isGoogleNativeDocumentUrl, brace-matched out of the source,
compiled with the host C++ compiler and run over Google links (the kind gvfs gives,
mixed case, with port/query) and over links that must still open in a tab or as files
(portal URLs, look-alike hosts such as docs.google.com.evil.example, a local .docx,
google-drive:// URIs).  It also checks, in the extracted handleInputCmd, that the URL
branch calls it and skips the tab (`continue`) - that part is a source check only.

NOT claimed.  No GNOME/gvfs Google account was available, so Nautilus passing the
https target is taken from gvfs/Nautilus behaviour and the reporter's screencast, not
observed here; that xdg-open then opens a browser is not run.  .gdoc/.gsheet link files
(Google Drive for desktop on Windows/macOS) are not handled.  macOS opens URLs through
its own code (not this file).

  RD_REPO     desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1  sources from BASE_REF via git show (default: parent of the fix) -> FAIL
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '82e255608^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'win-linux/src/cascapplicationmanagerwrapper.cpp'


def read(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def extract(text, anchor):
    at = text.find(anchor)
    if at == -1:
        return None
    ob = text.index('{', at)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[at:i + 1]
    raise SystemExit('unbalanced braces after %r' % anchor)


text = read(SRC)
helper = extract(text, 'static bool isGoogleNativeDocumentUrl(const std::wstring& url)')
if helper is None:
    print('FAIL: isGoogleNativeDocumentUrl not in %s - https Google links open in a tab' % SRC)
    sys.exit(1)

CASES = [
    ('https://docs.google.com/document/d/1AbC/edit?usp=drivesdk', 1),
    ('https://docs.google.com/spreadsheets/d/1AbC/edit', 1),
    ('https://docs.google.com/presentation/d/1AbC/edit', 1),
    ('HTTPS://Docs.Google.COM/document/d/1AbC', 1),
    ('https://drive.google.com/file/d/1AbC/view', 1),
    ('http://docs.google.com:443/document/d/x', 1),
    ('https://docs.google.com', 1),
    ('https://portal.example.com/products/files/doceditor.aspx?fileid=1', 0),
    ('https://docs.google.com.evil.example/document/d/x', 0),
    ('https://notdocs.google.com/document/d/x', 0),
    ('https://www.google.com/search?q=docs.google.com', 0),
    ('google-drive://user@gmail.com/1AbC', 0),
    ('/home/user/Report.docx', 0),
    ('docs.google.com/document/d/x', 0),
    ('', 0),
]

main = '#include <string>\n#include <cwctype>\n#include <cstdio>\n#include <cwchar>\n' + helper + r'''
int main(int argc, char** argv)
{
    for (int i = 1; i < argc; ++i) {
        std::string a(argv[i]);
        std::wstring w(a.begin(), a.end());
        printf("%d\n", isGoogleNativeDocumentUrl(w) ? 1 : 0);
    }
    return 0;
}
'''
tmp = tempfile.mkdtemp(prefix='rd1167-')
with open(os.path.join(tmp, 'm.cpp'), 'w') as f:
    f.write(main)
cxx = os.environ.get('CXX', 'c++')
r = subprocess.run([cxx, '-std=c++11', '-o', os.path.join(tmp, 'm'), os.path.join(tmp, 'm.cpp')],
                   capture_output=True, text=True)
if r.returncode != 0:
    print(r.stderr)
    raise SystemExit('FAIL: the extracted helper does not compile')
out = subprocess.run([os.path.join(tmp, 'm')] + [c[0] for c in CASES], capture_output=True, text=True).stdout.split()
shutil.rmtree(tmp, ignore_errors=True)
failed = 0
for (url, want), got in zip(CASES, out):
    ok = int(got) == want
    failed += not ok
    print('%s %-62s -> %s' % ('ok  ' if ok else 'FAIL', url or '(empty)', 'browser' if got == '1' else 'unchanged'))

body = extract(text, 'void CAscApplicationManagerWrapper::handleInputCmd(')
seg = body[body.find('check_params(open_opts.wurl, open_scheme) < 0'):] if body else ''
call = seg.find('isGoogleNativeDocumentUrl(open_opts.wurl)')
ok = call != -1 and 'Utils::openUrl' in seg[call:call + 200] and 'continue;' in seg[call:call + 200]
print('%s handleInputCmd sends a Google link to Utils::openUrl and opens no tab (source check)' % ('ok  ' if ok else 'FAIL'))
failed += not ok

if failed:
    print('FAIL: %d check(s)' % failed)
    sys.exit(1)
print('PASS #1167: Google Docs links from the command line go to the browser, not a tab')

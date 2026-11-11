#!/usr/bin/env python3
"""
#1664 (follow-up) - links from documents and pages were handed to the
operating system's opener whatever they pointed at.

Every link a page opens in a new window - a hyperlink clicked in a document of
any editor (after the editor's own "may be unsafe" Yes, or with no question at
all for anything the editor takes for a web address), a PDF link annotation or
URI action, a plugin's window.open, a link on a cloud portal or the start page
- reaches CheckPopup (desktop-sdk cefview.cpp, OnBeforePopup). For an editor or
simple view it sent ASC_MENU_EVENT_TYPE_CEF_ONOPENLINK with the URL, and the
application passed it straight to NSWorkspace openURL (macOS
ASCCommonViewController onCEFOpenUrl), QDesktopServices::openUrl (Windows) or
xdg-open (Linux; CheckPopup even rewrites existing file:// paths to "xdg:").
So file:///.../X.app, .command, .exe, .desktop, .jar, an executable without
extension, smb://host/share, or another application's URL scheme from a
received document started a program or connected to a share. Shown in a copy
of the test app: window.open('file://.../Marker.app') from the editor frame,
and a hyperlink of a crafted .docx after the editor's Yes, both started the
marker program; there was no native question.

Now (desktop-sdk link_policy.h + NSLinkConfirm in cefview.cpp):
- http, https and mailto: sent at once, as before.
- refused, never sent: a program, app bundle (anywhere in the path), script,
  installer, disk image, shortcut/location file (by extension, for any scheme,
  after %-decoding, trailing dots/spaces and ":stream" pieces), an existing
  file that is executable without an extension, a folder that is an app bundle,
  a symbolic link to any of these; on macOS also what Launch Services types as
  an application, alias, executable, script or installer; and script/data/
  internal/known-dangerous schemes (javascript:, data:, ms-msdt:, search-ms:...).
- anything else (a local document or folder, file://host or smb:// shares,
  other applications' schemes): sent only after the user said "Open" in a native
  dialog that shows the decoded target (control and bidi characters as \\uXXXX),
  "Cancel" being the default. macOS: NSAlert in the library; Windows/Linux:
  ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_CONFIRM to the application (desktop-apps
  shows a plain-text QMessageBox, Cancel default) which answers through Apply.
  A refused link is reported the same way (_REFUSED, "OK" only).
  One dialog at a time; a link asked for meanwhile is dropped.

This compiles the REAL link_policy.h and runs a table of links against files
made in a temporary directory (a document, a folder, an X.app bundle, a folder
bundle without extension, an executable without extension, a symlink named
.docx to the bundle, ...). It compiles the REAL NSLinkConfirm namespace (brace
matched from cefview.cpp, the Windows/Linux branch) with the REAL
applicationmanager_events.h against stubs for the CEF task functions and runs
the ask/answer flow. It checks by text that CheckPopup classifies before it
builds ONOPENLINK and returns without it otherwise, that Apply routes the
answer, and that desktop-apps answers the new event with Cancel as default. On
macOS it also compiles the REAL IsLauncherMac (mac_cefview.mm) and asks it about
/System/Applications/Calculator.app and a text file.

BASELINE=1 reads desktop-sdk at BASE_REF and desktop-apps at APPS_BASE_REF:
there is no link_policy.h and CheckPopup sends every URL to the opener, which is
what the table is checked against there - it FAILS.

  RD_REPO=<desktop-sdk>    (default ../../desktop-sdk)
  RD_APPS=<desktop-apps>   (default ../../desktop-apps)
  BASELINE=1, BASE_REF (default 833fea20^), APPS_BASE_REF (default 9b2f78275^)

NOT claimed: the dialogs as drawn (checked by hand in the test app on macOS:
see the report), Windows behaviour (not built here; the Windows path is the
same CheckPopup and the same Qt handler as Linux), that the extension list is
complete - the "ask" default covers what it misses, but a file type that runs
code when opened by its own application (an Office document with macros,
an HTML file) is still opened after "Open".
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
APPS = os.environ.get('RD_APPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
# Pinned to the parents of the commits that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '833fea20^')
APPS_BASE_REF = os.environ.get('APPS_BASE_REF', '9b2f78275^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'
INC = 'ChromiumBasedEditors/lib/include/'


def read(repo, ref, rel, missing_ok=False):
    if BASELINE:
        r = subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            if missing_ok:
                return None
            sys.exit('git show %s:%s failed: %s' % (ref, rel, r.stderr.strip()))
        return r.stdout
    p = os.path.join(repo, rel)
    if missing_ok and not os.path.exists(p):
        return None
    return open(p, encoding='utf-8').read()


def brace_block(text, start, from_pos=0):
    """From the line holding `start` to its matching closing brace."""
    a = text.find(start, from_pos)
    if a < 0:
        return None
    a = text.rfind('\n', 0, a) + 1
    b = text.find('{', text.find(start, from_pos))
    depth = 0
    i = b
    while i < len(text):
        c = text[i]
        if text.startswith('//', i):
            i = text.find('\n', i)
            continue
        if text.startswith('/*', i):
            i = text.find('*/', i) + 2
            continue
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == "'":
            i += 1
            while text[i] != "'":
                i += 2 if text[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


def compile_run(work, name, source, args, extra=()):
    src = os.path.join(work, name + ('.mm' if '-x' in extra else '.cpp'))
    with open(src, 'w', encoding='utf-8') as f:
        f.write(source)
    exe = os.path.join(work, name)
    r = subprocess.run(['c++', '-std=c++11', '-Wall', '-Wno-unused-function', '-I', work] + list(extra) + ['-o', exe, src], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('compile of %s failed:\n%s' % (name, r.stderr))
    return subprocess.run([exe] + list(args), capture_output=True, text=True, check=True).stdout


def make_tree(root):
    os.makedirs(os.path.join(root, 'Docs'))
    open(os.path.join(root, 'Docs', 'report.docx'), 'w').write('x')
    open(os.path.join(root, 'Docs', 'notes 10:30.txt'), 'w').write('x')
    os.makedirs(os.path.join(root, 'Folder'))
    os.makedirs(os.path.join(root, 'Evil.app', 'Contents', 'MacOS'))
    open(os.path.join(root, 'Evil.app', 'Contents', 'MacOS', 'Evil'), 'w').write('#!/bin/sh\n')
    os.chmod(os.path.join(root, 'Evil.app', 'Contents', 'MacOS', 'Evil'), 0o755)
    os.makedirs(os.path.join(root, 'Plain', 'Contents', 'MacOS'))   # a bundle without the extension
    open(os.path.join(root, 'run'), 'w').write('#!/bin/sh\n')
    os.chmod(os.path.join(root, 'run'), 0o755)
    open(os.path.join(root, 'exec.pdf'), 'w').write('%PDF')            # exec bit from a FAT stick
    os.chmod(os.path.join(root, 'exec.pdf'), 0o755)
    os.symlink(os.path.join(root, 'Evil.app'), os.path.join(root, 'Docs', 'innocent.docx'))
    os.symlink(os.path.join(root, 'Docs', 'report.docx'), os.path.join(root, 'Docs', 'shortcut.docx'))


OPEN, ASK, REFUSE = 0, 1, 2
NAMES = {0: 'open', 1: 'ask', 2: 'refuse'}


def cases(T):
    return [
        ('https', 'https://example.com/a?b=1#c', OPEN),
        ('http to an .exe download (the browser decides)', 'http://example.com/setup.exe', OPEN),
        ('mailto', 'mailto:a@example.com?subject=x', OPEN),
        ('local document', 'file://%s/Docs/report.docx' % T, ASK),
        ('local document with spaces and %-escapes', 'file://%s/Docs/notes%%2010%%3A30.txt' % T, ASK),
        ('symlink to a document', 'file://%s/Docs/shortcut.docx' % T, ASK),
        ('local folder', 'file://%s/Folder' % T, ASK),
        ('app bundle', 'file://%s/Evil.app' % T, REFUSE),
        ('app bundle, trailing slash', 'file://%s/Evil.app/' % T, REFUSE),
        ('app bundle, %2E-escaped dot', 'file://%s/Evil%%2Eapp' % T, REFUSE),
        ('the executable inside a bundle', 'file://%s/Evil.app/Contents/MacOS/Evil' % T, REFUSE),
        ('bundle folder without extension', 'file://%s/Plain' % T, REFUSE),
        ('executable without extension', 'file://%s/run' % T, REFUSE),
        ('document with the exec bit (FAT volume)', 'file://%s/exec.pdf' % T, ASK),
        ('symlink named .docx to an app', 'file://%s/Docs/innocent.docx' % T, REFUSE),
        ('Linux xdg: rewrite of an executable', 'xdg:file://%s/run' % T, REFUSE),
        ('.command script (not on disk)', 'file:///Users/x/Downloads/README.command', REFUSE),
        ('.desktop launcher', 'file:///home/x/Downloads/a.desktop', REFUSE),
        ('.jar', 'file:///tmp/tool.jar', REFUSE),
        ('.webloc', 'file:///tmp/x.webloc', REFUSE),
        ('.exe, upper case, trailing dot', 'file:///C:/Users/x/Downloads/SETUP.EXE.', REFUSE),
        ('Windows path with backslashes', 'C:\\Users\\x\\Downloads\\run.bat', REFUSE),
        ('NTFS stream suffix', 'file:///C:/x/readme.txt:evil.exe', REFUSE),
        ('.lnk on a share', 'file://server/share/x.lnk', REFUSE),
        ('share via file://host', 'file://server/share/report.docx', ASK),
        ('UNC path', '\\\\server\\share\\report.docx', ASK),
        ('smb share', 'smb://server/share', ASK),
        ('smb to an .exe', 'smb://server/share/x.exe', REFUSE),
        ('afp share', 'afp://server/vol', ASK),
        ('another application\'s scheme', 'zoommtg://zoom.us/join?confno=1', ASK),
        ('custom scheme to an .app', 'x-custom:/tmp/Evil.app', REFUSE),
        ('ftp', 'ftp://example.com/a.pdf', ASK),
        ('javascript:', 'javascript:alert(1)', REFUSE),
        ('data:', 'data:text/html,<b>x</b>', REFUSE),
        ('ms-msdt: (Follina)', 'ms-msdt:/id PCWDiagnostic', REFUSE),
        ('search-ms:', 'search-ms:query=x&crumb=location:\\\\evil\\s', REFUSE),
        ('relative path to an app', 'Evil.app', REFUSE),
        ('relative path to a document', 'report.docx', ASK),
    ]


POLICY_DRIVER = r'''
#include "link_policy.h"
#include <cstdio>
int main(int argc, char** argv)
{
	for (int i = 1; i < argc; ++i)
	{
		NSLinkPolicy::CDecision d = NSLinkPolicy::Classify(argv[i]);
		printf("%d\n", (int)d.Kind);
	}
	std::string sUrl = "file:///tmp/a%E2%80%AEgpj.app";
	NSLinkPolicy::CDecision d = NSLinkPolicy::Classify(sUrl);
	std::vector<std::string> t = NSLinkPolicy::GetDialogText(sUrl, d);
	printf("TEXT %s\n", (t[1].find("a\\u202Egpj.app") != std::string::npos && t[1].find("\xE2\x80\xAE") == std::string::npos) ? "bidi-escaped" : "bidi-raw");
	sUrl = "file:///Users/me/My%20Docs/report.docx";
	t = NSLinkPolicy::GetDialogText(sUrl, NSLinkPolicy::Classify(sUrl));
	printf("TEXT %s\n", t[1].find("/Users/me/My Docs/report.docx") != std::string::npos ? "decoded-path" : "raw-path");
	sUrl = "smb://evil.example/share";
	t = NSLinkPolicy::GetDialogText(sUrl, NSLinkPolicy::Classify(sUrl));
	printf("TEXT %s\n", t[1].find("evil.example") != std::string::npos ? "names-host" : "no-host");
	return 0;
}
'''

CONFIRM_DRIVER = r'''
#include <string>
#include <vector>
#include <cstdio>
#include "applicationmanager_events.h"
static std::string ToUtf8(const std::wstring& w) { return std::string(w.begin(), w.end()); }
static std::wstring FromUtf8(const std::string& s) { return std::wstring(s.begin(), s.end()); }
#define U_TO_UTF8(w) ToUtf8(w)
#define UTF8_TO_U(s) FromUtf8(s)
struct CefTask { virtual ~CefTask() {} virtual void Execute() = 0; };
#define IMPLEMENT_REFCOUNTING(x)
enum { TID_UI };
static bool CefCurrentlyOn(int) { return true; }
static void CefPostTask(int, CefTask* t) { t->Execute(); delete t; }
#include "link_policy.h"
struct CListener : public NSEditorApi::CAscCefMenuEventListener {
	std::vector<std::string> log; int lastAsk = 0;
	virtual void OnEvent(NSEditorApi::CAscCefMenuEvent* e) {
		char b[512];
		if (e->m_nType == ASC_MENU_EVENT_TYPE_CEF_ONOPENLINK) {
			NSEditorApi::CAscOnOpenExternalLink* d = (NSEditorApi::CAscOnOpenExternalLink*)e->m_pData;
			snprintf(b, sizeof(b), "OPEN view=%d %s", e->get_SenderId(), ToUtf8(d->get_Url()).c_str());
		} else if (e->m_nType == ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_CONFIRM) {
			NSEditorApi::CAscExternalProcessConfirm* d = (NSEditorApi::CAscExternalProcessConfirm*)e->m_pData;
			lastAsk = d->get_Id();
			snprintf(b, sizeof(b), "ASK id>0=%d shows-target=%d", (int)(d->get_Id() > 0), (int)(d->get_Text().find(L"/Docs/report.docx") != std::wstring::npos));
		} else if (e->m_nType == ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_REFUSED) {
			NSEditorApi::CAscExternalProcessConfirm* d = (NSEditorApi::CAscExternalProcessConfirm*)e->m_pData;
			lastAsk = d->get_Id();
			snprintf(b, sizeof(b), "REFUSED id>0=%d", (int)(d->get_Id() > 0));
		} else
			snprintf(b, sizeof(b), "EVENT %d", e->m_nType);
		log.push_back(b);
	}
};
@@NAMESPACE@@
static CListener L;
static void Dump(const char* step) { printf("%s:", step); for (size_t i = 0; i < L.log.size(); ++i) printf(" [%s]", L.log[i].c_str()); if (L.log.empty()) printf(" -"); printf("\n"); L.log.clear(); }
static void Click(const std::wstring& url) {
	// what CheckPopup does with a link (cefview.cpp, Ration Docs #1664 block)
	NSLinkPolicy::CDecision d = NSLinkConfirm::Classify(url);
	if (NSLinkPolicy::lpOpen != d.Kind) { NSLinkConfirm::Request(&L, 5, url, d); return; }
	NSLinkConfirm::SendOpenLink(&L, 5, url);
}
int main()
{
	Click(L"https://example.com/");                    Dump("https");
	Click(L"file:///Users/me/Docs/report.docx");      Dump("document asks");
	Click(L"file:///Users/me/Docs/other.docx");       Dump("second link while asking");
	NSLinkConfirm::Answer(L.lastAsk, false);           Dump("Cancel");
	NSLinkConfirm::Answer(L.lastAsk, true);            Dump("stale answer");
	Click(L"file:///Users/me/Docs/report.docx");      Dump("document asks again");
	NSLinkConfirm::Answer(L.lastAsk + 1000, true);     Dump("answer to another id");
	NSLinkConfirm::Answer(L.lastAsk, true);            Dump("Open");
	Click(L"file:///Applications/Calculator.app");    Dump("app");
	Click(L"file:///Applications/Calculator.app");    Dump("app again while the notice is up");
	NSLinkConfirm::Answer(L.lastAsk, true);            Dump("notice closed (even a yes opens nothing)");
	Click(L"file:///Users/me/Docs/report.docx");      Dump("asks after a refusal");
	NSLinkConfirm::Answer(L.lastAsk, true);            Dump("Open again");
	return 0;
}
'''

CONFIRM_EXPECT = [
    'https: [OPEN view=5 https://example.com/]',
    'document asks: [ASK id>0=1 shows-target=1]',
    'second link while asking: -',
    'Cancel: -',
    'stale answer: -',
    'document asks again: [ASK id>0=1 shows-target=1]',
    'answer to another id: -',
    'Open: [OPEN view=5 file:///Users/me/Docs/report.docx]',
    'app: [REFUSED id>0=1]',
    'app again while the notice is up: -',
    'notice closed (even a yes opens nothing): -',
    'asks after a refusal: [ASK id>0=1 shows-target=1]',
    'Open again: [OPEN view=5 file:///Users/me/Docs/report.docx]',
]

MAC_DRIVER = r'''
#import <Cocoa/Cocoa.h>
#include <string>
#include <cstdio>
namespace NSLinkConfirm {
@@FUNC@@
}
int main(int argc, char** argv)
{
	for (int i = 1; i < argc; ++i) { std::string r; bool b = NSLinkConfirm::IsLauncherMac(argv[i], r); printf("%d %s\n", (int)b, r.c_str()); }
	return 0;
}
'''


def main():
    policy = read(REPO, BASE_REF, SRC + 'link_policy.h', missing_ok=True)
    view = read(REPO, BASE_REF, SRC + 'cefview.cpp')
    events = read(REPO, BASE_REF, INC + 'applicationmanager_events.h')
    manager = read(REPO, BASE_REF, SRC + 'applicationmanager.cpp')
    macview = read(REPO, BASE_REF, SRC + 'mac_cefview.mm')
    wrapper = read(APPS, APPS_BASE_REF, 'win-linux/src/cascapplicationmanagerwrapper.cpp')
    failures = []

    popup = brace_block(view, 'bool CheckPopup(std::wstring sUrl')
    if popup is None:
        sys.exit('CheckPopup not found')
    pos_event = popup.find('CreateCefEvent(ASC_MENU_EVENT_TYPE_CEF_ONOPENLINK)')
    pos_classify = popup.find('NSLinkConfirm::Classify(sUrl)')
    gated = pos_classify >= 0 and pos_classify < pos_event and \
        re.search(r'if \(NSLinkPolicy::lpOpen != \w+\.Kind\)\s*\{[^}]*NSLinkConfirm::Request\([^}]*return true;', popup[pos_classify:pos_event]) is not None
    print('CheckPopup classifies a link before ONOPENLINK and returns without it unless it is a web link:', gated)
    if not gated:
        failures.append('CheckPopup sends every link to the system opener')

    work = tempfile.mkdtemp(prefix='rd1664l-')
    try:
        T = os.path.join(os.path.realpath(work), 'tree')
        make_tree(T)
        table = cases(T)
        print('\n-- what reaches the system opener --')
        if policy is not None and gated:
            with open(os.path.join(work, 'link_policy.h'), 'w', encoding='utf-8') as f:
                f.write(policy)
            out = compile_run(work, 'policy', POLICY_DRIVER, [u for _, u, _ in table]).split('\n')
            got = [int(x) for x in out[:len(table)]]
            texts = [x for x in out if x.startswith('TEXT ')]
        else:
            print('(no link_policy.h / no gate in CheckPopup: every link is sent to the opener as it is)')
            got = [OPEN] * len(table)
            texts = ['TEXT none'] * 3
        for (desc, url, want), g in zip(table, got):
            ok = g == want
            print('%-4s %-46s %-6s (want %s)  %s' % ('ok' if ok else 'FAIL', desc, NAMES[g], NAMES[want], url.replace(T, '<tmp>')))
            if not ok:
                failures.append(desc)
        for want in ('TEXT bidi-escaped', 'TEXT decoded-path', 'TEXT names-host'):
            ok = want in texts
            print('%-4s dialog text: %s' % ('ok' if ok else 'FAIL', want[5:]))
            if not ok:
                failures.append(want)

        print('\n-- the question and the answer (Windows/Linux branch of NSLinkConfirm) --')
        ns = brace_block(view, 'namespace NSLinkConfirm')
        if ns is None or policy is None or 'ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_CONFIRM' not in events:
            print('FAIL no NSLinkConfirm / OPEN_LINK_CONFIRM: nothing asks the user')
            failures.append('no confirmation')
        else:
            with open(os.path.join(work, 'applicationmanager_events.h'), 'w', encoding='utf-8') as f:
                f.write(events)
            got = compile_run(work, 'confirm', CONFIRM_DRIVER.replace('@@NAMESPACE@@', ns), []).strip().split('\n')
            for want_line, got_line in zip(CONFIRM_EXPECT, got + [''] * len(CONFIRM_EXPECT)):
                ok = want_line == got_line
                print('%-4s %s%s' % ('ok' if ok else 'FAIL', got_line, '' if ok else '   (want: %s)' % want_line))
                if not ok:
                    failures.append('confirm: ' + want_line)

        if sys.platform == 'darwin':
            print('\n-- macOS: Launch Services types (IsLauncherMac) --')
            fn = brace_block(macview, 'bool IsLauncherMac(') if 'bool IsLauncherMac(' in macview else None
            if fn is None:
                print('FAIL no IsLauncherMac')
                failures.append('no IsLauncherMac')
            else:
                txt = os.path.join(T, 'Docs', 'notes 10:30.txt')
                out = compile_run(work, 'mac', MAC_DRIVER.replace('@@FUNC@@', fn),
                                  ['/System/Applications/Calculator.app', txt, os.path.join(T, 'Folder')],
                                  extra=('-x', 'objective-c++', '-fobjc-arc', '-framework', 'Cocoa')).strip().split('\n')
                for (desc, want), line in zip((('Calculator.app', '1'), ('a text file', '0'), ('a folder', '0')), out):
                    ok = line.split(' ')[0] == want
                    print('%-4s %-16s launcher=%s' % ('ok' if ok else 'FAIL', desc, line))
                    if not ok:
                        failures.append('mac: ' + desc)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print('\n-- wiring --')
    apply_block = brace_block(manager, 'void CAscApplicationManager::Apply(') or ''
    ok = re.search(r'case ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_CONFIRM:[^}]*NSLinkConfirm::Answer\(pData->get_Id\(\), pData->get_Allowed\(\)\)', apply_block) is not None
    print('%-4s Apply routes the application\'s answer to NSLinkConfirm::Answer' % ('ok' if ok else 'FAIL'))
    if not ok:
        failures.append('Apply')
    mac_ok = 'void AskMac(int nAskId, const std::wstring& sTitle, const std::wstring& sText, bool bRefused)' in macview and \
        re.search(r'addButtonWithTitle:@"Cancel"\];\s*\[alert addButtonWithTitle:@"Open"\]', macview) is not None
    print('%-4s macOS dialog: "Cancel" first (the default button), then "Open"' % ('ok' if mac_ok else 'FAIL'))
    if not mac_ok:
        failures.append('mac dialog')
    case = brace_block(wrapper, 'case ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_CONFIRM:') if 'case ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_CONFIRM:' in wrapper else ''
    app_ok = bool(case) and 'setTextFormat(Qt::PlainText)' in case and 'setDefaultButton(btnCancel)' in case and \
        'setEscapeButton(btnCancel)' in case and 'new CAscMenuEvent(ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_CONFIRM)' in case and \
        'put_Allowed(box.clickedButton() == btnOpen)' in case and 'Apply(pAnswer)' in case
    print('%-4s Windows/Linux: plain-text box, Cancel default and Escape, answer through Apply' % ('ok' if app_ok else 'FAIL'))
    if not app_ok:
        failures.append('desktop-apps handler')
    ref = brace_block(wrapper, 'case ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_REFUSED:') if 'case ASC_MENU_EVENT_TYPE_SYSTEM_OPEN_LINK_REFUSED:' in wrapper else ''
    ref_ok = bool(ref) and 'setTextFormat(Qt::PlainText)' in ref and 'put_Allowed(false)' in ref and 'Apply(pAnswer)' in ref
    print('%-4s Windows/Linux: a refused link is reported, and the notice answered when closed' % ('ok' if ref_ok else 'FAIL'))
    if not ref_ok:
        failures.append('refused handler')

    print()
    if failures:
        print('FAILED (%d): %s' % (len(failures), '; '.join(failures)))
        sys.exit(1)
    print('PASSED')


if __name__ == '__main__':
    main()

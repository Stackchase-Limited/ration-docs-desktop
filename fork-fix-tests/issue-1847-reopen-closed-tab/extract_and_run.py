#!/usr/bin/env python3
"""
#1847 - "Shortcut to reopen previous tabs": Ctrl+Shift+T (Shift+Cmd+T on macOS)
should reopen the most recently closed document tab, as in a browser.

There was no such thing in 9.4: closing a tab forgot the document, and no
shortcut or menu item could bring it back (the only way was the Recent list).

Now both shells keep, for this session only, the local documents that were
closed (newest last, each path once, at most 20):
  win-linux  CAscApplicationManagerWrapper::rememberClosedDocument(), called from
             CMainWindow::onEditorAllowedClose (a tab) and CEditorWindowPrivate::
             onEditorAllowedClose (an editor window); Ctrl+Shift+T in the
             ONKEYBOARDDOWN handler calls reopenClosedDocument(), which opens the
             newest entry whose file still exists through handleInputCmd() - so it
             honours "open in editor window" and brings an already open copy to the
             front. A missing file is skipped (handleInputCmd would open a missing
             path as a new blank document).
  macOS      -[AppDelegate rememberClosedDocument:] from -tabs:didRemovedTab: and
             -[ASCEditorWindowController windowWillClose:]; File > "Reopen Closed
             Tab" (Shift+Cmd+T) posts the same CEFEventNameCreateTab/OpenLocalFile
             request that opening a file from Finder does.

What this runs: the real win-linux functions and the real Key_T case, lifted out
of cascapplicationmanagerwrapper.cpp by brace matching and compiled against Qt
(QFileInfo, QTimer) with stand-ins for CAscTabData and handleInputCmd; the real
macOS methods lifted out of AppDelegate.mm and compiled into a stand-in class,
observing the notification they post. Real files are created and deleted.
The call sites (both close paths per platform) and the macOS menu item are
checked in the source text.

NOT claimed: restoring a whole window of tabs after quitting (the second half of
the report - a design decision, not done); cloud documents and unsaved new
documents (not reopened: no local file); the shortcut in a running app (needs a
GUI check: on macOS the menu key equivalent, on Windows/Linux the CEF key event).

BASELINE=1 reads the sources from BASE_REF (the parent of the fix), where none of
this exists, and fails.
"""
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', 'b76fc9693a^')
BASELINE = bool(os.environ.get('BASELINE'))

WRAPPER = 'win-linux/src/cascapplicationmanagerwrapper.cpp'
MAINWIN = 'win-linux/src/windows/cmainwindow.cpp'
EDITWIN = 'win-linux/src/windows/ceditorwindow_p.h'
APPDEL = 'macos/ONLYOFFICE/AppDelegate.mm'
COMMON = 'macos/ONLYOFFICE/Code/Controllers/Common/ASCCommonViewController.mm'
EDCTRL = 'macos/ONLYOFFICE/Code/Controllers/EditorWindow/ASCEditorWindowController.mm'
STORY = 'macos/ONLYOFFICE/Base.lproj/Main.storyboard'

failures = []


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


def extract(src, anchor):
    at = src.find(anchor)
    return None if at == -1 else brace_match(src, at)


def check(ok, what):
    print('  %-74s %s' % (what, 'ok' if ok else 'FAILED'))
    if not ok:
        failures.append(what)


def compile_run(cmd, src_name, text, tmp):
    src = os.path.join(tmp, src_name)
    exe = os.path.join(tmp, src_name + '.bin')
    open(src, 'w').write(text)
    c = subprocess.run(cmd + ['-o', exe, src], capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile: %s' % src_name)
    r = subprocess.run([exe, os.path.join(tmp, 'docs')], capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    return r.returncode


QT_HARNESS = r'''
#include <QCoreApplication>
#include <QFileInfo>
#include <QTimer>
#include <QFile>
#include <QDir>
#include <vector>
#include <string>
#include <algorithm>
#include <stdio.h>

struct CAscTabData {
    bool local; std::wstring u;
    bool isLocal() const { return local; }
    std::wstring url() const { return u; }
};

static std::vector<std::wstring> g_opened;   /* what handleInputCmd was asked to open */

class CAscApplicationManagerWrapper : public QObject {
public:
    static void rememberClosedDocument(const CAscTabData *);
    static void reopenClosedDocument();
    static void handleInputCmd(const std::vector<std::wstring>& v) { g_opened.insert(g_opened.end(), v.begin(), v.end()); }
    bool onKey(int key, bool ctrl, bool shift, bool alt);
};

struct FakeKey {
    int k; bool c, s, a;
    int get_KeyCode() const { return k; } bool get_IsCtrl() const { return c; }
    bool get_IsShift() const { return s; } bool get_IsAlt() const { return a; }
};

%(decl)s
%(remember)s
%(reopen)s

bool CAscApplicationManagerWrapper::onKey(int key, bool ctrl, bool shift, bool alt) {
    FakeKey k{key, ctrl, shift, alt}; FakeKey * data = &k;
    switch ( data->get_KeyCode() ) {
    %(keycase)s
    default: break;
    }
    return false;
}

static int failures = 0;
static void check(bool ok, const char *what) { printf("  %%-74s %%s\n", what, ok ? "ok" : "FAILED"); if (!ok) failures++; }
static std::wstring W(const QString &s) { return s.toStdWString(); }

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QDir().mkpath(argv[1]);
    const QString a = QString(argv[1]) + "/Budget.xlsx", b = QString(argv[1]) + "/Report.docx";
    QFile(a).open(QIODevice::WriteOnly); QFile(b).open(QIODevice::WriteOnly);
    CAscApplicationManagerWrapper w;
    auto press = [&](int key, bool c, bool s, bool alt) { bool h = w.onKey(key, c, s, alt); app.processEvents(); return h; };

    CAscTabData da{true, W(a)}, db{true, W(b)}, cloud{false, L"https://cloud.example/doc?id=1"}, fresh{true, L""};
    CAscApplicationManagerWrapper::rememberClosedDocument(&da);
    CAscApplicationManagerWrapper::rememberClosedDocument(&cloud);
    CAscApplicationManagerWrapper::rememberClosedDocument(&fresh);
    CAscApplicationManagerWrapper::rememberClosedDocument(&db);

    check(press(0x54, true, true, false) && g_opened.size() == 1 && g_opened[0] == W(b), "win-linux: Ctrl+Shift+T reopens the last closed document");
    check(press(0x54, true, true, false) && g_opened.size() == 2 && g_opened[1] == W(a), "win-linux: again - the one closed before it (cloud/new ones were not kept)");
    check(press(0x54, true, true, false) && g_opened.size() == 2, "win-linux: nothing left - nothing is opened");

    CAscApplicationManagerWrapper::rememberClosedDocument(&da);
    CAscApplicationManagerWrapper::rememberClosedDocument(&db);
    CAscApplicationManagerWrapper::rememberClosedDocument(&da);
    QFile::remove(b);
    g_opened.clear();
    press(0x54, true, true, false);
    press(0x54, true, true, false);
    check(g_opened.size() == 1 && g_opened[0] == W(a), "win-linux: closed twice = kept once; a deleted file is skipped, not recreated");

    CAscApplicationManagerWrapper::rememberClosedDocument(&da);
    g_opened.clear();
    check(!press(0x54, true, false, false) && g_opened.empty(), "win-linux: Ctrl+T alone does nothing");
    check(!press(0x54, true, true, true) && g_opened.empty(), "win-linux: Ctrl+Alt+Shift+T does nothing");
    return failures ? 1 : 0;
}
'''

OBJC_HARNESS = r'''
#import <Cocoa/Cocoa.h>
#include <stdio.h>
typedef NS_ENUM(NSInteger, FakeAction) { ASCTabActionOpenLocalFile = 7 };
static NSString * const CEFEventNameCreateTab = @"CEF_createTab";

@interface FakeDelegate : NSObject
@property (nonatomic) NSMutableArray<NSString *> *closedDocumentPaths;
- (void)rememberClosedDocument:(NSString *)path;
@end
@implementation FakeDelegate
%(methods)s
@end

static int failures = 0;
static void check(BOOL ok, const char *what) { printf("  %%-74s %%s\n", what, ok ? "ok" : "FAILED"); if (!ok) failures++; }

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *dir = [NSString stringWithUTF8String:argv[1]];
        [[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *a = [dir stringByAppendingPathComponent:@"Budget.xlsx"], *b = [dir stringByAppendingPathComponent:@"Report.docx"];
        [@"x" writeToFile:a atomically:NO encoding:NSUTF8StringEncoding error:nil];
        [@"x" writeToFile:b atomically:NO encoding:NSUTF8StringEncoding error:nil];

        NSMutableArray *opened = [NSMutableArray array];
        [[NSNotificationCenter defaultCenter] addObserverForName:CEFEventNameCreateTab object:nil queue:nil usingBlock:^(NSNotification *n) {
            if ([n.userInfo[@"action"] integerValue] == ASCTabActionOpenLocalFile) [opened addObject:n.userInfo[@"path"]];
        }];
        FakeDelegate *d = [FakeDelegate new];
        [d rememberClosedDocument:a];
        [d rememberClosedDocument:nil];
        [d rememberClosedDocument:@"https://cloud.example/doc?id=1"];
        [d rememberClosedDocument:b];
        [d onMenuReopenClosedTab:nil];
        check(opened.count == 1 && [opened[0] isEqualToString:b], "macOS: Reopen Closed Tab opens the last closed document");
        [d onMenuReopenClosedTab:nil];
        check(opened.count == 2 && [opened[1] isEqualToString:a], "macOS: again - the one closed before it");
        [d onMenuReopenClosedTab:nil];
        check(opened.count == 2, "macOS: nothing left - nothing is opened");

        [d rememberClosedDocument:a]; [d rememberClosedDocument:b]; [d rememberClosedDocument:a];
        [[NSFileManager defaultManager] removeItemAtPath:b error:nil];
        [opened removeAllObjects];
        [d onMenuReopenClosedTab:nil]; [d onMenuReopenClosedTab:nil];
        check(opened.count == 1 && [opened[0] isEqualToString:a], "macOS: closed twice = kept once; a deleted file is skipped");
    }
    return failures ? 1 : 0;
}
'''


def main():
    print('#1847 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO))
    wrapper = read(WRAPPER)
    m = re.search(r'^static std::vector<std::wstring> g_closedDocuments;', wrapper, re.M)
    remember = extract(wrapper, 'void CAscApplicationManagerWrapper::rememberClosedDocument(')
    reopen = extract(wrapper, 'void CAscApplicationManagerWrapper::reopenClosedDocument(')
    keycase = None
    at = wrapper.find('case 0x54:')
    if at != -1:
        end = wrapper.index('break;', wrapper.index('return true;', at)) + len('break;')
        keycase = wrapper[at:end]

    check(bool(m and remember and reopen and keycase), 'win-linux: closed-document list and a Ctrl+Shift+T case exist')
    check('AscAppManager::rememberClosedDocument(m_pTabs->panel(_index)->data())' in
          (extract(read(MAINWIN), 'void CMainWindow::onEditorAllowedClose(') or ''),
          'win-linux: a closed tab is remembered (CMainWindow::onEditorAllowedClose)')
    check('AscAppManager::rememberClosedDocument(m_panel->data())' in
          (extract(read(EDITWIN), 'void onEditorAllowedClose(int) override') or ''),
          'win-linux: a closed editor window is remembered')

    appdel = read(APPDEL)
    methods = [extract(appdel, '- (void)rememberClosedDocument:(NSString *)path'),
               extract(appdel, '- (NSString *)takeClosedDocumentToReopen'),
               extract(appdel, '- (IBAction)onMenuReopenClosedTab:(NSMenuItem *)sender')]
    check(all(methods), 'macOS: AppDelegate keeps closed documents and can reopen one')
    check('rememberClosedDocument:tab.params[@"path"]' in
          (extract(read(COMMON), '- (void)tabs:(ASCTabsControl *)control didRemovedTab:') or ''),
          'macOS: a closed tab is remembered (-tabs:didRemovedTab:)')
    check('rememberClosedDocument:cefView.data.path' in
          (extract(read(EDCTRL), '- (void)windowWillClose:(NSNotification *)notification') or ''),
          'macOS: a closed editor window is remembered')
    story = read(STORY)
    item = re.search(r'<menuItem title="Reopen Closed Tab" keyEquivalent="T"[^>]*>\s*<connections>\s*'
                     r'<action selector="onMenuReopenClosedTab:" target="Voe-Tx-rLC"', story)
    check(bool(item), 'macOS: File > Reopen Closed Tab, Shift+Cmd+T, wired to AppDelegate')
    check('@selector(onMenuReopenClosedTab:)' in (extract(appdel, '- (BOOL)validateMenuItem:(NSMenuItem *)item') or ''),
          'macOS: the menu item is validated (disabled while nothing was closed)')

    with tempfile.TemporaryDirectory() as tmp:
        if m and remember and reopen and keycase:
            q = '/opt/homebrew/opt/qt@5'
            if platform.system() == 'Darwin':
                cmd = ['clang++', '-std=c++14', '-w', '-I' + q + '/lib/QtCore.framework/Headers',
                       '-F' + q + '/lib', '-framework', 'QtCore']
            else:
                flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt5Core'],
                                       capture_output=True, text=True, check=True).stdout.split()
                cmd = ['c++', '-std=c++14', '-w', '-fPIC'] + flags
            text = QT_HARNESS % {'decl': m.group(0), 'remember': remember, 'reopen': reopen, 'keycase': keycase}
            if compile_run(cmd + ['-x', 'c++'], 'qt_harness.cpp', text, tmp) != 0:
                failures.append('win-linux harness')
        if all(methods) and platform.system() == 'Darwin':
            text = OBJC_HARNESS % {'methods': '\n'.join(methods)}
            if compile_run(['clang', '-fobjc-arc', '-w', '-framework', 'Cocoa'], 'objc_harness.m', text, tmp) != 0:
                failures.append('macOS harness')

    print('\n%s' % ('FAILED: %d check(s)' % len(failures) if failures
                    else 'ok - Ctrl/Cmd+Shift+T reopens the last closed local document that still exists'))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

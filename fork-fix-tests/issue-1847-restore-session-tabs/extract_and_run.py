#!/usr/bin/env python3
"""
#1847 (second half) - "restore all previously open tabs after closing and reopening
the window". Ctrl/Cmd+Shift+T (first half, b76fc9693a) only reopens tabs closed in
the running session; quitting forgot every open document.

Now (option, off by default - Settings > "Reopen documents from the last session at
start", user setting restore-tabs) both shells keep the absolute paths of the local
documents open when the app quits or its main window is closed, and open the ones
that still exist at the next start that names no file:
  win-linux  CAscApplicationManagerWrapper::rememberSessionDocuments() from
             closeAppWindows() (Ctrl+Q, session end, update) and CMainWindow::closeEvent
             (the close button), skipped while a close is already under way; stored in
             the user registry as lastSessionFiles. startApp() appends
             lastSessionDocuments() (existing files only) to the start arguments when
             they name no document, so handleInputCmd() opens them as from the command
             line (honouring "open in editor window").
  macOS      -[AppDelegate rememberSessionDocuments] from applicationShouldTerminate:
             (not after the main window's close, not during "Review Changes...") and
             ASCTitleWindowController windowShouldClose:; NSUserDefaults
             asc_user_lastSessionFiles. -reopenSessionDocuments at the end of
             applicationDidFinishLaunching when no file was opened on launch posts the
             same CEFEventNameCreateTab/OpenLocalFile request as Reopen Closed Tab.
  Both: switching the option off forgets the stored list.

What this runs: the real win-linux functions and the real startApp() block, lifted
out of cascapplicationmanagerwrapper.cpp by brace matching and compiled against Qt
(QSettings in an ini file, QFileInfo) with stand-ins for tabs, editor windows,
user settings and the close queue; the real macOS -rememberSessionDocuments and
-reopenSessionDocuments compiled into a stand-in class (the option and the list of
open documents stubbed), observing the notifications they post. Real files are
created and deleted. Call sites, the settings glue and the start page switch are
checked in the source text.

NOT claimed: the quit/start sequence in a running app (GUI check on each platform:
turn the option on, open two local files plus a new unsaved one, quit with Ctrl+Q /
Cmd+Q and once with the main window's close button, start again - the two files come
back, the unsaved one does not; start by double-clicking a file - only that file
opens); -openLocalDocumentPaths walking real NSWindows; Windows not compiled here
(Linux syntax-only compile of the changed units was run separately).

BASELINE=1 reads the sources from BASE_REF (the parent of the fix) and fails.
"""
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', 'ccb7f894af^')
BASELINE = bool(os.environ.get('BASELINE'))

WRAPPER = 'win-linux/src/cascapplicationmanagerwrapper.cpp'
MAINWIN = 'win-linux/src/windows/cmainwindow.cpp'
WININIT = 'win-linux/src/prop/cmainwindowimpl.cpp'
APPDEL = 'macos/ONLYOFFICE/AppDelegate.mm'
TITLEWC = 'macos/ONLYOFFICE/Code/Controllers/MainWindow/ASCTitleWindowController.mm'
COMMON = 'macos/ONLYOFFICE/Code/Controllers/Common/ASCCommonViewController.mm'
EVENTS = 'macos/ONLYOFFICE/Code/Controllers/Common/ASCEventsController.mm'
PANEL = 'common/loginpage/src/panelsettings.js'

failures = []


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def brace_match(src, at, open_brace=None):
    if open_brace is None:
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
    print('  %-78s %s' % (what, 'ok' if ok else 'FAILED'))
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
#include <QSettings>
#include <QStringList>
#include <QFileInfo>
#include <QFile>
#include <QDir>
#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <stdio.h>

static QString g_ini;
#define GET_REGISTRY_USER(variable) QSettings variable(g_ini, QSettings::IniFormat);
#define APP_CAST(app) CAscApplicationManagerWrapper & app = getInstance();

struct CAscTabData {
    bool local; std::wstring u;
    bool isLocal() const { return local; }
    std::wstring url() const { return u; }
};
struct CTabPanel { CAscTabData d; const CAscTabData * data() const { return &d; } };
struct CAscTabWidget {
    std::vector<CTabPanel *> v;
    int count() const { return int(v.size()); }
    CTabPanel * panel(int i) const { return v[size_t(i)]; }
};
struct CMainWindow {
    CAscTabWidget tabs; bool closing = false;
    CAscTabWidget * tabWidget() { return &tabs; }
    bool isAboutToClose() const { return closing; }
};
struct CEditorWindow { CTabPanel p; CTabPanel * mainView() const { return const_cast<CTabPanel *>(&p); } };
struct Queue { bool busy = false; bool empty() { return !busy; } };

static std::map<std::wstring, std::wstring> g_settings;

class CAscApplicationManagerWrapper {
public:
    CMainWindow * m_pMainWindow = nullptr;
    std::vector<size_t> m_vecEditors;
    Queue q;
    Queue& closeQueue() { return q; }
    static CAscApplicationManagerWrapper & getInstance() { static CAscApplicationManagerWrapper a; return a; }
    static std::wstring userSettings(const std::wstring& n) { return g_settings[n]; }
    static void rememberSessionDocuments();
    static std::vector<std::wstring> lastSessionDocuments();
    static std::vector<std::wstring> startArgs(std::vector<std::wstring> in_args, bool files_in_args);
};

%(remember)s
%(last)s

std::vector<std::wstring> CAscApplicationManagerWrapper::startArgs(std::vector<std::wstring> in_args, bool files_in_args)
{
    %(startblock)s
    return in_args;
}

static int failures = 0;
static void check(bool ok, const char *what) { printf("  %%-78s %%s\n", what, ok ? "ok" : "FAILED"); if (!ok) failures++; }
static std::wstring W(const QString &s) { return s.toStdWString(); }
typedef CAscApplicationManagerWrapper App;

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QDir().mkpath(argv[1]);
    g_ini = QString(argv[1]) + "/user.ini";
    const QString a = QString(argv[1]) + "/Budget.xlsx", b = QString(argv[1]) + "/Report.docx", c = QString(argv[1]) + "/Slides.pptx";
    for (auto f : {a, b, c}) QFile(f).open(QIODevice::WriteOnly);

    CMainWindow mw;
    CTabPanel ta{{true, W(a)}}, tcloud{{false, L"https://cloud.example/doc?id=1"}}, tnew{{true, L""}}, tb{{true, W(b)}}, tdup{{true, W(a)}};
    mw.tabs.v = {&ta, &tcloud, &tnew, &tb, &tdup};
    CEditorWindow ew{{{true, W(c)}}};
    App & w = App::getInstance();
    w.m_pMainWindow = &mw;
    w.m_vecEditors = {size_t(&ew)};

    App::rememberSessionDocuments();
    check(App::startArgs({}, false).empty() && !QSettings(g_ini, QSettings::IniFormat).contains("lastSessionFiles"),
          "win-linux: option off (default) - nothing is kept, nothing reopened");

    g_settings[L"restore-tabs"] = L"1";
    App::rememberSessionDocuments();
    auto args = App::startArgs({}, false);
    check(args == std::vector<std::wstring>({W(a), W(b), W(c)}),
          "win-linux: tabs + editor windows kept once each; cloud/new not; reopened at start");

    mw.tabs.v = {&tb};
    w.q.busy = true;
    App::rememberSessionDocuments();
    w.q.busy = false;
    mw.closing = true;
    App::rememberSessionDocuments();
    mw.closing = false;
    check(App::startArgs({}, false).size() == 3, "win-linux: a close under way does not shrink the list taken at its start");

    QFile::remove(b);
    check(App::startArgs({L"--system-title-bar"}, false) == std::vector<std::wstring>({L"--system-title-bar", W(a), W(c)}),
          "win-linux: a deleted file is skipped; plain switches still restore");
    check(App::startArgs({L"/home/u/Other.docx"}, false) == std::vector<std::wstring>({L"/home/u/Other.docx"}),
          "win-linux: a start that names a file opens only that file");
    check(App::startArgs({L"--new:word"}, true) == std::vector<std::wstring>({L"--new:word"}),
          "win-linux: --new/--view/--edit starts do not restore");
    g_settings[L"restore-tabs"] = L"0";
    check(App::startArgs({}, false).empty(), "win-linux: option switched off - nothing reopened");
    return failures ? 1 : 0;
}
'''

OBJC_HARNESS = r'''
#import <Cocoa/Cocoa.h>
#include <stdio.h>
typedef NS_ENUM(NSInteger, FakeAction) { ASCTabActionOpenLocalFile = 7 };
static NSString * const CEFEventNameCreateTab = @"CEF_createTab";
static NSString * const ASCUserLastSessionFiles = @"rd_test_1847_lastSessionFiles";

@interface FakeDelegate : NSObject
@property (nonatomic) BOOL option;
@property (nonatomic) NSArray<NSString *> *open;
@end
@implementation FakeDelegate
- (BOOL)restoresSessionDocuments { return self.option; }
- (NSArray<NSString *> *)openLocalDocumentPaths { return self.open; }
%(methods)s
@end

static int failures = 0;
static void check(BOOL ok, const char *what) { printf("  %%-78s %%s\n", what, ok ? "ok" : "FAILED"); if (!ok) failures++; }

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *dir = [NSString stringWithUTF8String:argv[1]];
        [[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *a = [dir stringByAppendingPathComponent:@"Budget.xlsx"], *b = [dir stringByAppendingPathComponent:@"Report.docx"];
        [@"x" writeToFile:a atomically:NO encoding:NSUTF8StringEncoding error:nil];
        [@"x" writeToFile:b atomically:NO encoding:NSUTF8StringEncoding error:nil];
        NSUserDefaults *ud = [NSUserDefaults standardUserDefaults];
        [ud removeObjectForKey:ASCUserLastSessionFiles];

        NSMutableArray *opened = [NSMutableArray array];
        [[NSNotificationCenter defaultCenter] addObserverForName:CEFEventNameCreateTab object:nil queue:nil usingBlock:^(NSNotification *n) {
            if ([n.userInfo[@"action"] integerValue] == ASCTabActionOpenLocalFile) [opened addObject:n.userInfo[@"path"]];
        }];
        void (^spin)(void) = ^{ [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.4]]; };

        FakeDelegate *d = [FakeDelegate new];
        d.open = @[a, b];
        [d rememberSessionDocuments];
        [d reopenSessionDocuments]; spin();
        check([ud arrayForKey:ASCUserLastSessionFiles] == nil && opened.count == 0, "macOS: option off (default) - nothing kept, nothing reopened");

        d.option = YES;
        [d rememberSessionDocuments];
        [d reopenSessionDocuments]; spin();
        check([opened isEqualToArray:(@[a, b])], "macOS: the documents open at quit are reopened at start");

        [opened removeAllObjects];
        [[NSFileManager defaultManager] removeItemAtPath:b error:nil];
        [d reopenSessionDocuments]; spin();
        check([opened isEqualToArray:(@[a])], "macOS: a deleted file is skipped, not recreated");
        [ud removeObjectForKey:ASCUserLastSessionFiles];
    }
    return failures ? 1 : 0;
}
'''


def main():
    print('#1847 restore %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO))
    wrapper = read(WRAPPER)
    remember = extract(wrapper, 'void CAscApplicationManagerWrapper::rememberSessionDocuments(')
    last = extract(wrapper, 'std::vector<std::wstring> CAscApplicationManagerWrapper::lastSessionDocuments(')
    startblock = None
    at = wrapper.find('// #1847: a start that opens nothing')
    if at != -1:
        if_at = wrapper.index('if (', at)
        startblock = brace_match(wrapper, at, wrapper.index('{\n', wrapper.index(') )', if_at)))
    check(bool(remember and last and startblock), 'win-linux: session list functions and the startApp() restore exist')
    check('rememberSessionDocuments();' in (extract(wrapper, 'void CAscApplicationManagerWrapper::closeAppWindows(') or ''),
          'win-linux: Ctrl+Q / session end / update (closeAppWindows) records the session')
    check('AscAppManager::rememberSessionDocuments();' in (extract(read(MAINWIN), 'void CMainWindow::closeEvent(') or ''),
          'win-linux: the main window close button records the session')
    check('setUserSettings(L"restore-tabs"' in wrapper and '_reg_user.remove("lastSessionFiles")' in wrapper
          and '_json_obj["restoretabs"]' in read(WININIT), 'win-linux: settings:init/apply carry restoretabs; off forgets the list')

    appdel = read(APPDEL)
    methods = [extract(appdel, '- (void)rememberSessionDocuments'), extract(appdel, '- (void)reopenSessionDocuments')]
    check(all(methods), 'macOS: AppDelegate records and reopens the session')
    term = extract(appdel, '- (NSApplicationTerminateReply)applicationShouldTerminate:') or ''
    check('[self rememberSessionDocuments]' in term and '!self.waitingForTerminateApp' in term,
          'macOS: quitting records it (not during Review Changes / after the main window closed)')
    launch = extract(appdel, '- (void)applicationDidFinishLaunching:') or ''
    check(re.search(r'if \(!self\.hasFilesToOpenOnLaunch\) \{\s*\[self presentMainWindow\];\s*\[self reopenSessionDocuments\];', launch) is not None,
          'macOS: a launch that opens no file reopens the session')
    check('rememberSessionDocuments]' in (extract(read(TITLEWC), '- (BOOL)windowShouldClose:(id)sender') or ''),
          'macOS: the main window close button records the session')
    check('forKey:@"restoretabs"' in read(COMMON) and 'L"restore-tabs"' in read(EVENTS),
          'macOS: settings:init/apply carry restoretabs')
    panel = read(PANEL)
    check('id="sett-restore-tabs"' in panel and '_new_settings.restoretabs' in panel, 'start page: the switch and Apply')

    with tempfile.TemporaryDirectory() as tmp:
        if remember and last and startblock:
            q = '/opt/homebrew/opt/qt@5'
            if platform.system() == 'Darwin':
                cmd = ['clang++', '-std=c++14', '-w', '-I' + q + '/lib/QtCore.framework/Headers',
                       '-F' + q + '/lib', '-framework', 'QtCore']
            else:
                flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt5Core'],
                                       capture_output=True, text=True, check=True).stdout.split()
                cmd = ['c++', '-std=c++14', '-w', '-fPIC'] + flags
            text = QT_HARNESS % {'remember': remember, 'last': last, 'startblock': startblock}
            if compile_run(cmd + ['-x', 'c++'], 'qt_harness.cpp', text, tmp) != 0:
                failures.append('win-linux harness')
        if all(methods) and platform.system() == 'Darwin':
            text = OBJC_HARNESS % {'methods': '\n'.join(methods)}
            if compile_run(['clang', '-fobjc-arc', '-w', '-framework', 'Cocoa'], 'objc_harness.m', text, tmp) != 0:
                failures.append('macOS harness')

    print('\n%s' % ('FAILED: %d check(s)' % len(failures) if failures
                    else 'ok - with the option on, the local documents open at quit are reopened at the next start'))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())

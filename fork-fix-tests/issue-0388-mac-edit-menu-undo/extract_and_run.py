#!/usr/bin/env python3
"""
#388 - "Undo/Redo commands in Edit menu do not work on macOS". Edit > Undo and Edit > Redo
left the document unchanged (toolbar and Cmd+Z worked), and Redo was shown as Cmd+Y where
macOS menus use Shift+Cmd+Z.

Main.storyboard (desktop-apps) sent undo:/redo: to the first responder, i.e. Chromium's
RenderWidgetHostViewCocoa, whose undo is the browser's own editing undo. The editor draws the
document on a canvas and types through a hidden text area with no native history, so nothing
happened. The fix routes the items to AppDelegate onMenuUndo:/onMenuRedo:, which send
"edit:undo"/"edit:redo" to an editor that has the focus (anything else still gets undo:/redo:
through the responder chain); web-apps Desktop.js clicks the header Undo/Redo button, or, when
the focus is in a text field or a plugin frame, answers "edit:native" so ASCEventsController
runs the browser view's undo:/redo: there, as before.

What runs here, all lifted from the real sources:
  1. Main.storyboard is parsed: the Undo/Redo items' action selector, their target (must be
     the AppDelegate object) and Redo's key equivalent (uppercase Z = Shift+Cmd+Z).
  2. AppDelegate.mm's onMenuUndo:, onMenuRedo: and editorViewForEditCommand are brace-matched
     out and compiled as Objective-C++ into a stub AppDelegate (stub NSCefView/NSCefData,
     NSApp redirected to a recording stub by a macro) and driven: editor with focus inside,
     focus outside the view, a portal (non-editor) view.
  3. The "edit:native" branch of ASCEventsController.mm is compiled the same way.
  4. window.on_native_message from web-apps Desktop.js is run in node with stub native /
     titlebuttons / document.activeElement.

NOT claimed: real menu dispatch, the CEF round trip and the editors' undo itself - those were
checked in the cw clone of the test app (menu item performed in-process: document text undone
and redone, a text field and a frame undone natively, the cell editor undone; Cmd+Z via CDP
still undoes exactly one step).

BASELINE=1 reads the sources at BASE_REF (desktop-apps) and WEBAPPS_BASE_REF (web-apps), the
parents of the fix; there every part fails.
RD_REPO overrides the desktop-apps checkout (default ../../desktop-apps from this file),
RD_WEBAPPS the web-apps checkout (default ../../web-apps). macOS (clang) and node needed.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps'))
WEBAPPS = os.environ.get('RD_WEBAPPS', os.path.join(HERE, '..', '..', 'web-apps'))
# Pinned to the parents of the commits that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '674be1df2^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', '896bea2db7^')


def read(repo, ref, rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


def brace_match(src, at, what):
    depth = 0
    for i in range(src.index('{', at), len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces extracting %s' % what)


failures = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else '\n     ' + detail))
    if not ok:
        failures.append(name)


# --- 1. the storyboard ---
board = read(REPO, BASE_REF, 'macos/ONLYOFFICE/Base.lproj/Main.storyboard')
root = ET.fromstring(board)
delegate_ids = {o.get('id') for o in root.iter('customObject') if o.get('customClass') == 'AppDelegate'}
items = {}
for item in root.iter('menuItem'):
    if item.get('title') in ('Undo', 'Redo') and item.get('id') in ('dRJ-4n-Yzg', '6dh-zS-Vam'):
        action = item.find('connections/action')
        items[item.get('title')] = (item.get('keyEquivalent'), action.get('selector'), action.get('target'))
for title, sel in (('Undo', 'onMenuUndo:'), ('Redo', 'onMenuRedo:')):
    key, selector, target = items[title]
    check('storyboard: Edit > %s goes to AppDelegate %s' % (title, sel),
          selector == sel and target in delegate_ids,
          'action %s to %s (AppDelegate is %s)' % (selector, target, sorted(delegate_ids)))
check('storyboard: Redo is Shift+Cmd+Z', items['Redo'][0] == 'Z', 'key equivalent %r' % items['Redo'][0])

# --- 2./3. the Objective-C side ---
appdel = read(REPO, BASE_REF, 'macos/ONLYOFFICE/AppDelegate.mm')
events = read(REPO, BASE_REF, 'macos/ONLYOFFICE/Code/Controllers/Common/ASCEventsController.mm')
methods = []
for sig in ('- (IBAction)onMenuUndo:(NSMenuItem *)sender', '- (IBAction)onMenuRedo:(NSMenuItem *)sender',
            '- (NSCefView *)editorViewForEditCommand'):
    at = appdel.find(sig)
    if at != -1:
        methods.append(brace_match(appdel, at, sig))
native_at = events.find('} else if (cmd.compare(L"edit:native") == 0) {')
native_branch = brace_match(events, native_at + 2, 'edit:native') if native_at != -1 else None

if len(methods) != 3 or native_branch is None:
    check('AppDelegate onMenuUndo:/onMenuRedo:/editorViewForEditCommand and the edit:native branch exist',
          False, 'found %d of 3 methods, edit:native branch %s' % (len(methods), 'found' if native_branch else 'missing'))
else:
    harness = r'''
#import <Cocoa/Cocoa.h>
#include <string>
#include <cstdio>
enum CefViewWrapperType { cvwtSimple = 0, cvwtEditor = 1 };
static NSMutableArray *gLog;

@interface NSCefData : NSObject
@property (nonatomic) CefViewWrapperType type;
- (BOOL)isViewType:(CefViewWrapperType)viewType;
@end
@implementation NSCefData
- (BOOL)isViewType:(CefViewWrapperType)viewType { return viewType == self.type; }
@end

@interface NSCefView : NSView
@property (nonatomic, strong) NSCefData *data;
- (void)sendCommand:(NSString *)command withParam:(NSString *)param;
@end
@implementation NSCefView
- (void)sendCommand:(NSString *)command withParam:(NSString *)param { [gLog addObject:[@"js " stringByAppendingString:command]]; }
@end

/* stands in for NSApp: a key window whose first responder the test chooses, and a recorder */
@interface StubWindow : NSObject
@property (nonatomic, strong) id firstResponder;
@end
@implementation StubWindow @end
@interface StubApp : NSObject
@property (nonatomic, strong) StubWindow *keyWindow;
@end
@implementation StubApp
- (BOOL)sendAction:(SEL)a to:(id)t from:(id)s { [gLog addObject:[NSString stringWithFormat:@"native %@", NSStringFromSelector(a)]]; return YES; }
- (id)targetForAction:(SEL)a { return nil; }
@end
static StubApp *gStubApp;
#define NSApp gStubApp

@interface AppDelegate : NSObject
@property (nonatomic, strong) NSCefView *keyCef;
@end
@implementation AppDelegate
- (NSCefView *)cefViewFromKeyWindow { return self.keyCef; }
@@METHODS@@
@end

static void editNative(const std::wstring &cmd, const std::wstring &param) {
    if (false) {
    } @@NATIVE@@
}

static NSString *run(CefViewWrapperType type, BOOL focusInside, BOOL redo) {
    gLog = [NSMutableArray array];
    AppDelegate *d = [AppDelegate new];
    d.keyCef = [[NSCefView alloc] initWithFrame:NSMakeRect(0, 0, 10, 10)];
    d.keyCef.data = [NSCefData new];
    d.keyCef.data.type = type;
    NSView *browser = [[NSView alloc] initWithFrame:NSZeroRect];   /* the CEF view inside */
    [d.keyCef addSubview:browser];
    gStubApp.keyWindow.firstResponder = focusInside ? browser : [[NSTextField alloc] initWithFrame:NSZeroRect];
    if (redo) [d onMenuRedo:nil]; else [d onMenuUndo:nil];
    return [gLog componentsJoinedByString:@","];
}

int main() {
    @autoreleasepool {
        gStubApp = [StubApp new];
        gStubApp.keyWindow = [StubWindow new];
        NSMutableDictionary *r = [NSMutableDictionary dictionary];
        r[@"editor_undo"] = run(cvwtEditor, YES, NO);
        r[@"editor_redo"] = run(cvwtEditor, YES, YES);
        r[@"editor_native_field"] = run(cvwtEditor, NO, NO);
        r[@"portal_undo"] = run(cvwtSimple, YES, NO);
        gLog = [NSMutableArray array]; editNative(L"edit:native", L"undo"); r[@"edit_native_undo"] = [gLog componentsJoinedByString:@","];
        gLog = [NSMutableArray array]; editNative(L"edit:native", L"redo"); r[@"edit_native_redo"] = [gLog componentsJoinedByString:@","];
        NSData *j = [NSJSONSerialization dataWithJSONObject:r options:0 error:nil];
        printf("%s\n", [[[NSString alloc] initWithData:j encoding:NSUTF8StringEncoding] UTF8String]);
    }
    return 0;
}
'''
    src = harness.replace('@@METHODS@@', '\n'.join(methods)).replace('@@NATIVE@@', native_branch)
    with tempfile.TemporaryDirectory() as tmp:
        mm, exe = os.path.join(tmp, 'h.mm'), os.path.join(tmp, 'h')
        open(mm, 'w').write(src)
        cc = subprocess.run(['clang++', '-std=c++17', '-fobjc-arc', '-w', '-framework', 'Cocoa', mm, '-o', exe],
                            capture_output=True, text=True)
        if cc.returncode:
            print(cc.stderr[-3000:])
            raise SystemExit('harness did not compile')
        res = json.loads(subprocess.run([exe], capture_output=True, text=True, check=True).stdout)
    check('menu Undo with the focus in an editor sends edit:undo to it', res['editor_undo'] == 'js edit:undo', res['editor_undo'])
    check('menu Redo with the focus in an editor sends edit:redo to it', res['editor_redo'] == 'js edit:redo', res['editor_redo'])
    check('focus outside the editor view keeps the native undo:', res['editor_native_field'] == 'native undo:', res['editor_native_field'])
    check('a portal (non-editor) view keeps the native undo:', res['portal_undo'] == 'native undo:', res['portal_undo'])
    check('edit:native undo runs the browser view undo:', res['edit_native_undo'] == 'native undo:', res['edit_native_undo'])
    check('edit:native redo runs the browser view redo:', res['edit_native_redo'] == 'native redo:', res['edit_native_redo'])

# --- 4. web-apps Desktop.js ---
desktop = read(WEBAPPS, WEBAPPS_BASE_REF, 'apps/common/main/lib/controller/Desktop.js')
marker = 'window.on_native_message = function (cmd, param) {'
at = desktop.find(marker)
fn = brace_match(desktop, at + len('window.on_native_message = '), 'on_native_message')
# a small driver: run the real handler for each case
driver = r'''
const FN = %s;
function run(cmd, active, modal) {
    const log = [];
    const btn = (name) => ({ click() { log.push('click ' + name); } });
    const native = { execCommand: (c, p) => log.push('native ' + c + ' ' + p) };
    const titlebuttons = { undo: { btn: btn('undo') }, redo: { btn: btn('redo') } };
    const Common = { Utils: { ModalWindow: { isVisible: () => modal } } };
    const document = { activeElement: active };
    const f = new Function('native', 'titlebuttons', 'Common', 'document', 'webapp', 'config',
        'return ' + FN)(native, titlebuttons, Common, document, {}, {});
    f(cmd, '');
    return log.join(',');
}
const area = { id: 'area_id', tagName: 'TEXTAREA', isContentEditable: false };
const field = { id: 'search', tagName: 'INPUT', isContentEditable: false };
const frame = { id: 'plugin', tagName: 'IFRAME', isContentEditable: false };
const body = { id: '', tagName: 'BODY', isContentEditable: false };
console.log(JSON.stringify({
    doc_undo: run('edit:undo', area, false), doc_redo: run('edit:redo', body, false),
    field_undo: run('edit:undo', field, false), frame_redo: run('edit:redo', frame, false),
    modal_undo: run('edit:undo', area, true),
}));
''' % json.dumps(fn)
node = subprocess.run(['node', '-e', driver], capture_output=True, text=True)
if node.returncode:
    print(node.stderr[-2000:])
    raise SystemExit('node driver failed')
w = json.loads(node.stdout)
check('Desktop.js: edit:undo with the editor focused clicks the header Undo', w['doc_undo'] == 'click undo', w['doc_undo'])
check('Desktop.js: edit:redo with nothing focused clicks the header Redo', w['doc_redo'] == 'click redo', w['doc_redo'])
check('Desktop.js: edit:undo in a text field hands back edit:native', w['field_undo'] == 'native edit:native undo', w['field_undo'])
check('Desktop.js: edit:redo in a plugin frame hands back edit:native', w['frame_redo'] == 'native edit:native redo', w['frame_redo'])
check('Desktop.js: nothing is undone behind a modal window', w['modal_undo'] == '', w['modal_undo'])

print('\n%d check(s) failed' % len(failures) if failures else '\nall checks passed')
sys.exit(1 if failures else 0)

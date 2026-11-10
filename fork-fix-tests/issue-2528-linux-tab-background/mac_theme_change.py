#!/usr/bin/env python3
"""
#2528 (macOS part) - after a runtime theme change, tabs that were already open keep
the old theme's background.

Every NSCefView gets the theme's window background when it is created
(ASCCommonViewController openTab, AppDelegate's editor-window path, the start page).
A theme change - Settings, or the system appearance when the theme follows it -
reaches AppDelegate's onUIThemeChanged / onSystemThemeChanged, which only told the
pages "uitheme:changed". The views already open kept their old layer color: white or
light gray behind the page after switching to a dark theme, visible whenever a tab is
switched before Chromium has presented a frame.

What runs: this extracts the real onUIThemeChanged and onSystemThemeChanged from
macos/ONLYOFFICE/AppDelegate.mm, finds every `[self <selector>]` they send that
AppDelegate.mm itself defines (other than updateAppAppearance, which only sets
NSApp.appearance), extracts those methods by brace matching and compiles them against
stub AppKit/app classes (Foundation only). It then builds two main windows - start page
plus tabs, one tab whose view is not created yet - and a separate editor window, all
painted in the light theme's color, switches the theme to dark, sends what each handler
sends, and checks every open view now has the dark theme's background.

The handler wiring is checked structurally (which self methods the handler bodies call);
the update itself is the real code, run. NOT claimed: CEF's own browser background,
which is fixed at browser creation, and anything about what Chromium paints. It needs a
GUI check in the test app.

BASELINE=1 reads the source at BASE_REF, where the handlers update no view: must fail.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO_APPS', os.path.join(HERE, '..', '..', 'desktop-apps'))
REL = 'macos/ONLYOFFICE/AppDelegate.mm'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF_APPS', '4b4733b03^')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()


def matched(text, start):
    depth = 0
    for i in range(text.index('{', start), len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces')


def method(sel):
    m = re.search(r'^- \(void\)%s\b[^\n{]*\{' % re.escape(sel), src, re.M)
    return matched(src, m.start()) if m else None


handlers = {}
for h in ('onUIThemeChanged', 'onSystemThemeChanged'):
    body = method(h)
    assert body and 'updateAppAppearance' in body, '%s not found' % h
    handlers[h] = [s for s in re.findall(r'\[self (\w+)\]', body)
                   if s != 'updateAppAppearance' and method(s)]

called = sorted({s for sels in handlers.values() for s in sels})
methods = '\n'.join(method(s) for s in called)

STUBS = r'''
#import <Foundation/Foundation.h>
#include <cstdio>
static NSString * const windowBackgroundColor = @"window-background-color";
#define rootTabId @"1CEF624D-9FF3-432B-9967-61361B5BFE8B"
static unsigned gThemeBack = 0xF7F7F7;   // light theme

@interface NSColor : NSObject
@property unsigned rgb;
@end
@implementation NSColor
@end
@interface ASCThemesController : NSObject
+ (NSColor *)currentThemeColor:(NSString *)name;
@end
@implementation ASCThemesController
+ (NSColor *)currentThemeColor:(NSString *)name {
    NSColor * c = [NSColor new];
    c.rgb = [name isEqualToString:windowBackgroundColor] ? gThemeBack : 0x123456;
    return c;
}
@end
@interface NSView : NSObject
@end
@implementation NSView
@end
@interface NSCefView : NSView
@property NSColor * back;
- (void)setBackgroundColor:(NSColor *)color;
@end
@implementation NSCefView
- (void)setBackgroundColor:(NSColor *)color { self.back = color; }
@end
@interface ASCTabView : NSObject
@property NSString * uuid;
@end
@implementation ASCTabView
@end
@interface ASCTabsControl : NSObject
@property NSMutableArray<ASCTabView *> * tabs;
@end
@implementation ASCTabsControl
@end
@interface NSTabView : NSObject
@property NSMutableDictionary<NSString *, NSCefView *> * items;   // identifier -> view (NSNull: none yet)
- (NSInteger)indexOfTabViewItemWithIdentifier:(id)identifier;
@end
@implementation NSTabView
- (NSInteger)indexOfTabViewItemWithIdentifier:(id)identifier {
    return self.items[identifier] ? 0 : NSNotFound;
}
@end
@interface NSViewController : NSObject
@end
@implementation NSViewController
@end
@interface ASCCommonViewController : NSViewController
@property ASCTabsControl * tabsControl;
@property NSTabView * tabView;
- (NSCefView *)cefViewWithTab:(ASCTabView *)tab;
@end
@implementation ASCCommonViewController
// like the real one: tabViewItemAtIndex:NSNotFound raises
- (NSCefView *)cefViewWithTab:(ASCTabView *)tab {
    id v = self.tabView.items[tab ? tab.uuid : rootTabId];
    if (!v) @throw [NSException exceptionWithName:NSRangeException reason:@"tabViewItemAtIndex: NSNotFound" userInfo:nil];
    return [v isKindOfClass:[NSCefView class]] ? v : nil;
}
@end
@interface NSWindow : NSObject
@property NSViewController * contentViewController;
@end
@implementation NSWindow
@end
@interface ASCTitleWindow : NSWindow
@end
@implementation ASCTitleWindow
@end
@interface ASCEditorWindow : NSWindow
@property NSView * webView;
@end
@implementation ASCEditorWindow
@end
@interface FakeApp : NSObject
@property NSMutableArray<NSWindow *> * windows;
@end
@implementation FakeApp
@end
static FakeApp * gApp;
#define NSApp gApp

@interface AppDelegate : NSObject
@end
@implementation AppDelegate
'''

MAIN = r'''
@end

static NSMutableArray<NSCefView *> * gViews;
static NSCefView * view() {
    NSCefView * v = [NSCefView new];
    [v setBackgroundColor:[ASCThemesController currentThemeColor:windowBackgroundColor]];
    [gViews addObject:v];
    return v;
}
static ASCTitleWindow * mainWindow(int tabs) {
    ASCCommonViewController * c = [ASCCommonViewController new];
    c.tabsControl = [ASCTabsControl new]; c.tabsControl.tabs = [NSMutableArray new];
    c.tabView = [NSTabView new]; c.tabView.items = [NSMutableDictionary new];
    c.tabView.items[rootTabId] = view();
    for (int i = 0; i < tabs; i++) {
        ASCTabView * t = [ASCTabView new]; t.uuid = [NSString stringWithFormat:@"tab-%d", i];
        [c.tabsControl.tabs addObject:t];
        c.tabView.items[t.uuid] = view();
    }
    ASCTabView * opening = [ASCTabView new]; opening.uuid = @"opening";   // no NSCefView yet
    [c.tabsControl.tabs addObject:opening];
    c.tabView.items[opening.uuid] = (id)[NSNull null];
    ASCTitleWindow * w = [ASCTitleWindow new]; w.contentViewController = c;
    return w;
}

int main(int argc, char ** argv) {
    int fails = 0;
    @autoreleasepool {
        NSString * handler = [NSString stringWithUTF8String:argv[1]];
        gViews = [NSMutableArray new];
        gApp = [FakeApp new]; gApp.windows = [NSMutableArray new];
        [gApp.windows addObject:mainWindow(3)];
        [gApp.windows addObject:mainWindow(1)];
        ASCEditorWindow * ew = [ASCEditorWindow new]; ew.webView = view();
        [gApp.windows addObject:ew];

        gThemeBack = 0x404040;   // switch to the dark theme
        AppDelegate * app = [AppDelegate new];
        @try {
            for (int i = 2; i < argc; i++)
                [app performSelector:NSSelectorFromString([NSString stringWithUTF8String:argv[i]])];
        } @catch (NSException * e) {
            std::printf("FAIL %s: threw %s\n", handler.UTF8String, e.reason.UTF8String);
            return 1;
        }
        int stale = 0;
        for (NSCefView * v in gViews)
            if (v.back.rgb != gThemeBack) stale++;
        std::printf("%s %s: %d of %d open views still have the old theme background (0xf7f7f7)\n",
                    stale ? "FAIL" : "ok  ", handler.UTF8String, stale, (int)gViews.count);
        fails += stale ? 1 : 0;
    }
    return fails;
}
'''

with tempfile.TemporaryDirectory() as tmp:
    mm = os.path.join(tmp, 'harness.mm')
    exe = os.path.join(tmp, 'harness')
    open(mm, 'w').write(STUBS + methods + MAIN)
    r = subprocess.run(['xcrun', 'clang++', '-x', 'objective-c++', '-fobjc-arc', '-w', mm,
                        '-framework', 'Foundation', '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr)
        sys.exit(2)
    rc = 0
    for h in ('onUIThemeChanged', 'onSystemThemeChanged'):
        r = subprocess.run([exe, h] + handlers[h], capture_output=True, text=True)
        sys.stdout.write(r.stdout + r.stderr)
        rc |= r.returncode
    print('PASS' if rc == 0 else
          'FAIL (#2528: a theme change leaves open tabs with the old theme background on macOS)')
    sys.exit(1 if rc else 0)

#!/usr/bin/env python3
"""
#766 - "Use middle mouse button for closing tabs".

The feature itself is already in our 9.4 code on every platform (upstream bug
51040): win-linux CTabBar::eventFilter closes the tab under a Qt::MiddleButton
release, and macOS ASCTabsControl closes the tab under -otherMouseDown:.

What was wrong on macOS: AppKit sends -otherMouseDown: for EVERY button other
than left and right - the middle button is buttonNumber 2, but the back/forward
side buttons of a five-button mouse are 3 and 4. The handler never looked at the
button, so pressing "back" with the pointer over a tab closed that tab (and, with
unsaved changes, put up the save prompt). Now only buttonNumber 2 closes; other
buttons go on to super as AppKit expects.

This compiles the real -otherMouseDown: method, lifted by brace matching out of
ASCTabsControl.m, into a stand-in NSView subclass that has the three things the
method touches (tabs, tabsView, tabDidClose:), and feeds it real NSEvents built
from CGEvents with button numbers 2, 3 and 4.

NOT claimed: the win-linux behaviour (unchanged, Qt::MiddleButton only); that
the tab strip receives otherMouseDown in the running app (checked by hand in the
test app, see the report).

BASELINE=1 reads ASCTabsControl.m from BASE_REF (the parent of the fix): the
side buttons close the tab there, so the run fails.
"""
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
REL = 'macos/ONLYOFFICE/Code/Controls/ASCTabs/ASCTabsControl.m'
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '8c8ec5f91b^')

if platform.system() != 'Darwin':
    print('skipped: macOS only (AppKit)')
    sys.exit(0)

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()


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
    raise SystemExit('unbalanced braces extracting from %s' % REL)


at = source.find('- (void)otherMouseDown:(NSEvent *)event')
if at == -1:
    raise SystemExit('-otherMouseDown: not found in %s - the extractor needs updating' % REL)
method = brace_match(source, at)

harness = r'''
#import <Cocoa/Cocoa.h>
#include <stdio.h>

@interface FakeTab : NSObject
@property NSRect frame;
@end
@implementation FakeTab
@end
#define ASCTabView FakeTab

/* Stand-in for ASCTabsControl: only what -otherMouseDown: touches. */
@interface FakeTabsControl : NSView
@property (nonatomic) NSMutableArray *tabs;
@property (nonatomic) NSView *tabsView;
@property (nonatomic) int closed;
@property (nonatomic) int passedOn;
- (void)tabDidClose:(FakeTab *)tab;
@end

@interface FakeTabsView : NSView
@end
@implementation FakeTabsView
- (NSPoint)convertPoint:(NSPoint)p fromView:(NSView *)v { return p; }
@end

@implementation FakeTabsControl
- (void)tabDidClose:(FakeTab *)tab { self.closed++; }
- (void)otherMouseDownSuper { self.passedOn++; }
%(method)s
@end

/* [super otherMouseDown:] lands in NSView's implementation, which forwards to
   the next responder; give it one that counts. */
@interface Counter : NSResponder
@property (nonatomic, assign) FakeTabsControl *owner;
@end
@implementation Counter
- (void)otherMouseDown:(NSEvent *)e { [self.owner otherMouseDownSuper]; }
@end

static int failures = 0;

static void press(int button, BOOL wantClose, const char *what) {
    @autoreleasepool {
        FakeTabsControl *c = [[FakeTabsControl alloc] initWithFrame:NSMakeRect(0, 0, 800, 30)];
        Counter *next = [Counter new];
        next.owner = c;
        [c setNextResponder:next];
        c.tabsView = [[FakeTabsView alloc] initWithFrame:NSZeroRect];
        FakeTab *t = [FakeTab new];
        t.frame = NSMakeRect(-1e6, -1e6, 2e6, 2e6);   /* the pointer is over it, wherever it is */
        c.tabs = [NSMutableArray arrayWithObject:t];

        CGEventRef cg = CGEventCreateMouseEvent(NULL, kCGEventOtherMouseDown, CGPointMake(100, 10), (CGMouseButton)button);
        NSEvent *ev = [NSEvent eventWithCGEvent:cg];
        CFRelease(cg);
        [c otherMouseDown:ev];

        BOOL closed = c.closed > 0;
        printf("  button %%d (%%-24s) buttonNumber=%%ld  tab closed=%%-3s  %%s\n", button, what,
               (long)ev.buttonNumber, closed ? "yes" : "no", closed == wantClose ? "ok" : "FAILED");
        if (closed != wantClose) failures++;
    }
}

int main(void) {
    press(2, YES, "middle");
    press(3, NO,  "side button: back");
    press(4, NO,  "side button: forward");
    printf("\n%%s\n", failures ? "FAILED"
        : "ok - only the middle button closes the tab under the pointer");
    return failures ? 1 : 0;
}
''' % {'method': method}

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'harness.m')
    exe = os.path.join(tmp, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang', '-fobjc-arc', '-w', '-o', exe, src, '-framework', 'Cocoa'],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    print('#766 %s: %s' % ('BASELINE ' + BASE_REF if os.environ.get('BASELINE') else 'source', REPO))
    sys.stdout.flush()
    sys.exit(subprocess.run([exe]).returncode)

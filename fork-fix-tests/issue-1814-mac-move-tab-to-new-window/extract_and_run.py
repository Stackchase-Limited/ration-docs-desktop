#!/usr/bin/env python3
"""
#1814 - "Enable multi-window support for macOS": the reporter says the macOS app
has one window only, while Windows/Linux can show documents in windows of their own.

What 9.4 already has on macOS: Settings > "Open file: in window" opens every
document in its own editor window (AppDelegate preferOpenEditorWindow, user setting
editor-window-mode - the same setting as on Windows/Linux), and a document tab can
be dragged out of the tab bar into a window of its own and dropped back
(ASCTabsControl -> ASCTitleBarController tabs:didDetachTab: -> AppDelegate
dragDetachedTab:). What was missing is the macOS way to do the second without a
drag: Safari/Finder's Window > "Move Tab to New Window".

Now Window > "Move Tab to New Window" (AppDelegate onMenuMoveTabToNewWindow:)
takes the current document tab of the main window - the frontmost app window
(effectiveKeyWindow), so it works when the app is not in front of a terminal
too - and does what the drag does: detaches the view from the tab (params
"detached", so the close bookkeeping of #1847 is skipped), removes the tab and
shows the same view in a new editor window (presentDetachedEditor:inWindowWithFrame:,
now shared with the drag), offset from the main window like "Open file: in window"
and zoomed when the main window is. Enabled only for a document tab of the main
window (not the start page, not an editor window).

What this checks: the storyboard item (visible, wired to AppDelegate); that the
menu action performs the same detach statements as the tab-bar drag (lifted from
ASCTitleBarController.mm and compared statement by statement), that both the drag
and the menu present the view through the one shared method, and the menu
validation. The behaviour was run by hand in an app clone with a relinked
executable (lldb, delayed perform of the menu item): before, windows
[ASCTitleWindow] with tabs [same.docx, one.docx]; after, windows [ASCTitleWindow,
ASCEditorWindow "one.docx"], tabs [same.docx], the same 2 CDP pages (the view
moved, not reloaded); with the editor window frontmost the item is disabled.

NOT claimed: the same document open in two windows at once (the reporter's use
case) - the app opens one view per file on every platform; not done (triage).
Dropping the window back into the tab bar is the existing drag code, unchanged.

BASELINE=1 reads the sources from BASE_REF (the parent of the fix) and fails.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', '607339b530^')
BASELINE = bool(os.environ.get('BASELINE'))
APPDEL = 'macos/ONLYOFFICE/AppDelegate.mm'
TITLEBAR = 'macos/ONLYOFFICE/Code/Controllers/MainWindow/ASCTitleBarController.mm'
STORY = 'macos/ONLYOFFICE/Base.lproj/Main.storyboard'
failures = []


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def extract(src, anchor):
    at = src.find(anchor)
    if at == -1:
        return ''
    depth = 0
    for i in range(src.index('{', at), len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]


def statements(body):
    body = re.sub(r'//[^\n]*', '', body)
    out = [re.sub(r'\s+', ' ', s).strip() for s in body.split(';')]
    return [re.sub(r'^.*[{}]\s*', '', s) for s in out if s]


def check(ok, what):
    print('  %-76s %s' % (what, 'ok' if ok else 'FAILED'))
    if not ok:
        failures.append(what)


print('#1814 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO))
app = read(APPDEL)
bar = read(TITLEBAR)
root = ET.fromstring(read(STORY))
delegate_id = next(o.get('id') for o in root.iter('customObject') if o.get('customClass') == 'AppDelegate')

print('storyboard:')
window_menu = next(m for m in root.iter('menu') if m.get('systemMenu') == 'window')
item = next((i for i in window_menu.iter('menuItem') if i.get('title') == 'Move Tab to New Window'), None)
act = item.find('./connections/action') if item is not None else None
check(item is not None and item.get('hidden') != 'YES', 'Window > Move Tab to New Window exists and is visible')
check(act is not None and act.get('selector') == 'onMenuMoveTabToNewWindow:' and act.get('target') == delegate_id,
      'it sends onMenuMoveTabToNewWindow: to AppDelegate')

print('AppDelegate.mm:')
menu = extract(app, '- (IBAction)onMenuMoveTabToNewWindow:')
pick = extract(app, '- (ASCTabView *)tabToMoveToNewWindow')
drag = extract(app, '- (void)dragDetachedTab:')
present = extract(app, '- (ASCEditorWindow *)presentDetachedEditor:')
detach = extract(bar, '- (BOOL)tabs:(ASCTabsControl *)control didDetachTab:')
check(bool(menu and pick and present), 'menu action, tab choice and shared presenter exist')

# the drag's detach statements, from "[webView removeFromSuperview]" to "webView.data.path = ..."
d = statements(detach)
start = next((i for i, s in enumerate(d) if s.startswith('[webView removeFromSuperview]')), None)
end = next((i for i, s in enumerate(d) if s.startswith('webView.data.path')), None)
drag_steps = [s.replace('[control ', '[controller.tabsControl ') for s in d[start:end + 1]] if start is not None and end is not None else []
m = statements(menu)
pos = [m.index(s) if s in m else -1 for s in drag_steps]
check(bool(drag_steps) and -1 not in pos and pos == sorted(pos),
      'menu does the drag\'s detach steps in order (%d statements)' % len(drag_steps))
check('presentDetachedEditor:webView' in re.sub(r'\s+', '', menu) and 'presentDetachedEditor:webView' in re.sub(r'\s+', '', drag),
      'menu and drag show the view through the same presenter')
check('performWindowDragWithEvent:' in drag and 'performWindowDragWithEvent:' not in menu,
      'only the drag starts a window drag')
check('isViewType:cvwtEditor' in pick and 'effectiveKeyWindow' in pick and 'mainWindowController' in pick,
      'only a document tab of the frontmost main window is moved')
vm = extract(app, '- (BOOL)validateMenuItem:')
check('@selector(onMenuMoveTabToNewWindow:)' in vm and 'tabToMoveToNewWindow' in vm, 'the item is enabled only when there is such a tab')

print('\n%s' % ('ok - Window > Move Tab to New Window moves the current document tab into its own window' if not failures
                else 'FAILED - %d check(s): %s' % (len(failures), '; '.join(failures))))
sys.exit(0 if not failures else 1)

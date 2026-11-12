#!/usr/bin/env python3
"""
#858 - "Ability to switch to full screen (F11)". On macOS the platform shortcut is
Ctrl+Cmd+F (Window > Enter Full Screen); the report is about Windows/Linux F11.

What we found on macOS: the windows are full-screen capable (fullScreenPrimary;
the green button works) but Ctrl+Cmd+F did nothing. In AppKit that shortcut is
not built into NSWindow - it belongs to an "Enter Full Screen" menu item with
the toggleFullScreen: action, which AppKit only inserts on its own into a
visible View menu. Our View menu is hidden and the Window menu had no such item.
Checked in the running test app (lldb): -[NSMenu performKeyEquivalent:] on the
main menu returned NO for a Ctrl+Cmd+F key event (YES for Cmd+M, which
minimised the window), the window stayed out of full screen after the event,
while -[NSWindow toggleFullScreen:] on the same window entered and left it.

Now Main.storyboard has Window > "Enter Full Screen" (Ctrl+Cmd+F,
toggleFullScreen: sent to the first responder, so it acts on whichever window is
key - the main window or a separate editor window; AppKit retitles it "Exit Full
Screen" while in full screen).

This test parses the real Main.storyboard and checks that a menu item with that
key equivalent and action exists, is not hidden, and is not inside a hidden
menu (a hidden item takes no part in key-equivalent matching).

NOT claimed: Windows/Linux F11 (not changed - see the report); the behaviour of
the running app is checked by hand (lldb), not by this test.

BASELINE=1 reads the storyboard from BASE_REF (the parent of the fix): no such
item, so it fails.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
REL = 'macos/ONLYOFFICE/Base.lproj/Main.storyboard'
BASE_REF = os.environ.get('BASE_REF', '483116cf19^')

if os.environ.get('BASELINE'):
    text = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                          capture_output=True, text=True, check=True).stdout
else:
    text = open(os.path.join(REPO, REL), encoding='utf-8').read()

root = ET.fromstring(text)
first_responder = [o.get('id') for o in root.iter('customObject') if o.get('sceneMemberID') == 'firstResponder']
main_menu = next(m for m in root.iter('menu') if m.get('key') == 'mainMenu')
print('#858 %s: %s' % ('BASELINE ' + BASE_REF if os.environ.get('BASELINE') else 'source', REPO))


def walk(menu, path, hidden):
    for item in menu.findall('./items/menuItem'):
        h = hidden or item.get('hidden') == 'YES'
        title = item.get('title') or ''
        yield item, path + [title], h
        sub = item.find('./menu')
        if sub is not None:
            yield from walk(sub, path + [title], h)


found = []
for item, path, hidden in walk(main_menu, [], False):
    act = item.find('./connections/action')
    if act is None or act.get('selector') != 'toggleFullScreen:':
        continue
    mask = item.find('./modifierMask')
    mods = sorted(k for k, v in (mask.attrib.items() if mask is not None else [('command', 'YES')])
                  if v == 'YES' and k != 'key')
    print('  %-40s key=%r mods=%s hidden=%s target-first-responder=%s' % (
        ' > '.join(path), item.get('keyEquivalent'), '+'.join(mods), hidden, act.get('target') in first_responder))
    found.append(item.get('keyEquivalent') == 'f' and mods == ['command', 'control'] and not hidden
                 and act.get('target') in first_responder)

ok = any(found)
print('\n%s' % ('ok - Ctrl+Cmd+F is bound to toggleFullScreen: in a visible menu' if ok
                else 'FAILED - no visible menu item binds Ctrl+Cmd+F to toggleFullScreen:'))
sys.exit(0 if ok else 1)

#!/usr/bin/env python3
"""
#69 - "Support menubar on macOS": the reporter wants the Settings in the menu bar
and "the last recently opened files in a submenu of File".

What 9.4 had: Settings is already there (app menu > Preferences..., Cmd+, opens
the start page settings). File > "Open Recent" existed in Main.storyboard but was
hidden, and it was AppKit's recent-documents menu (systemMenu="recentDocuments"),
which only lists what NSDocumentController is told about - nothing in the app
ever told it, so it would have been empty anyway.

Now File > Open Recent is visible and AppDelegate fills it each time it opens
(NSMenuDelegate menuNeedsUpdate:) from the start page's own Recent list - the
library keeps it in recents.xml next to the recovery folder and rewrites it on
every change: local documents only (cloud entries have a url), newest first, at
most 10, files that no longer exist left out, same-named files followed by
their folder name, "No Recent Documents" (disabled) when there is nothing.
Choosing one posts the same CEFEventNameCreateTab / ASCTabActionOpenLocalFile
request as opening the file from Finder (an open copy is brought to the front).

What this runs: the real -recentLocalDocuments:, -menuNeedsUpdate: and
-onMenuOpenRecent: lifted out of AppDelegate.mm by brace matching and compiled
into a stand-in class with a stand-in +[ASCHelper recoveryDataPath], against a
real recents.xml (with BOM, as the library writes it) and real files; the
notification is observed. The storyboard wiring (visible item, not AppKit's
system menu, delegate and outlet to AppDelegate) is checked by parsing
Main.storyboard.

Checked by hand in an app clone with a relinked executable (lldb): the
submenu listed one.docx, "same.docx - b", "same.docx - a" (a deleted file left out),
choosing a closed one opened it, choosing an open one opened nothing new.

NOT claimed: toolbar commands in the menu bar like MS Office (not done - see
the triage note); "Clear Menu" (not offered: the list belongs to the start page,
which can clear it).

BASELINE=1 reads the sources from BASE_REF (the parent of the fix) and fails.
"""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-apps')))
BASE_REF = os.environ.get('BASE_REF', '6aa7e7249c^')
BASELINE = bool(os.environ.get('BASELINE'))
APPDEL = 'macos/ONLYOFFICE/AppDelegate.mm'
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
        return None
    depth = 0
    for i in range(src.index('{', at), len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]


def check(ok, what):
    print('  %-74s %s' % (what, 'ok' if ok else 'FAILED'))
    if not ok:
        failures.append(what)


HARNESS = r'''
#import <Cocoa/Cocoa.h>
typedef NS_ENUM(NSInteger, FakeAction) { ASCTabActionOpenLocalFile = 7 };
static NSString * const CEFEventNameCreateTab = @"CEF_createTab";
static NSString * g_recovery;
@interface ASCHelper : NSObject
+ (NSString *)recoveryDataPath;
@end
@implementation ASCHelper
+ (NSString *)recoveryDataPath { return g_recovery; }
@end
@interface FakeDelegate : NSObject <NSMenuDelegate>
@property (weak) NSMenu *openRecentMenu;
- (NSArray<NSString *> *)recentLocalDocuments:(NSUInteger)limit;
@end
@implementation FakeDelegate
%(methods)s
@end

int main(int argc, char ** argv) {
  @autoreleasepool {
    NSString * root = [NSString stringWithUTF8String:argv[1]];
    g_recovery = [root stringByAppendingPathComponent:@"recovery"];
    NSFileManager * fm = [NSFileManager defaultManager];
    NSString * docs = [root stringByAppendingPathComponent:@"docs"];
    for (NSString * d in @[@"a", @"b"])
      [fm createDirectoryAtPath:[docs stringByAppendingPathComponent:d] withIntermediateDirectories:YES attributes:nil error:nil];
    NSArray * existing = @[@"one.docx", @"a/same.docx", @"b/same.docx"];
    for (NSString * f in existing) [@"x" writeToFile:[docs stringByAppendingPathComponent:f] atomically:NO encoding:NSUTF8StringEncoding error:nil];
    for (int i = 0; i < 12; i++) [@"x" writeToFile:[docs stringByAppendingPathComponent:[NSString stringWithFormat:@"n%%d.xlsx", i]] atomically:NO encoding:NSUTF8StringEncoding error:nil];

    NSMutableString * xml = [NSMutableString stringWithString:@"﻿<?xml version=\"1.0\" encoding=\"utf-8\"?><recents>"];
    void (^add)(NSString *, NSString *) = ^(NSString * p, NSString * url) {
      [xml appendFormat:@"<file path=\"%%@\" type=\"65\" date=\"12.11.2026 17:29\" url=\"%%@\" parent=\"\" />", p, url];
    };
    add([docs stringByAppendingPathComponent:@"one.docx"], @"");
    add([docs stringByAppendingPathComponent:@"gone.docx"], @"");                 // deleted
    add([docs stringByAppendingPathComponent:@"b/same.docx"], @"");
    add(@"/cloud/doc.docx", @"https://portal.example/doc?id=1");                  // cloud entry
    add(docs, @"");                                                                // a folder
    add([docs stringByAppendingPathComponent:@"a/same.docx"], @"");
    for (int i = 0; i < 12; i++) add([docs stringByAppendingPathComponent:[NSString stringWithFormat:@"n%%d.xlsx", i]], @"");
    [xml appendString:@"</recents>"];

    FakeDelegate * del = [FakeDelegate new];
    NSMenu * menu = [[NSMenu alloc] initWithTitle:@"Open Recent"];
    del.openRecentMenu = menu;

    [del menuNeedsUpdate:menu];
    printf("no recents.xml: %%ld item(s), first \"%%s\" enabled=%%d\n", (long)menu.numberOfItems,
           menu.numberOfItems ? [[menu itemAtIndex:0].title UTF8String] : "", menu.numberOfItems ? [menu itemAtIndex:0].enabled : -1);

    [fm createDirectoryAtPath:g_recovery withIntermediateDirectories:YES attributes:nil error:nil];
    [xml writeToFile:[root stringByAppendingPathComponent:@"recents.xml"] atomically:NO encoding:NSUTF8StringEncoding error:nil];
    [del menuNeedsUpdate:menu];
    printf("items: %%ld\n", (long)menu.numberOfItems);
    for (NSMenuItem * it in menu.itemArray)
      printf("  %%s | %%s | target=%%d action=%%s\n", [it.title UTF8String], [[it.toolTip stringByReplacingOccurrencesOfString:root withString:@""] UTF8String],
             it.target == del, sel_getName(it.action));

    __block NSDictionary * posted = nil;
    [[NSNotificationCenter defaultCenter] addObserverForName:CEFEventNameCreateTab object:nil queue:nil usingBlock:^(NSNotification * n) { posted = n.userInfo; }];
    NSMenuItem * first = [menu itemAtIndex:0];
    [first.target performSelector:first.action withObject:first];
    printf("posted: action=%%ld path=%%s active=%%d\n", (long)[posted[@"action"] integerValue],
           [[posted[@"path"] stringByReplacingOccurrencesOfString:root withString:@""] UTF8String], [posted[@"active"] boolValue]);
  }
  return 0;
}
'''


def main():
    print('#69 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO))
    src = read(APPDEL)
    story = read(STORY)

    print('storyboard:')
    root = ET.fromstring(story)
    delegate_id = next((o.get('id') for o in root.iter('customObject') if o.get('customClass') == 'AppDelegate'), None)
    item = next((i for i in root.iter('menuItem') if i.get('title') == 'Open Recent'), None)
    sub = item.find('./menu') if item is not None else None
    check(item is not None and item.get('hidden') != 'YES', 'File > Open Recent is visible')
    check(sub is not None and sub.get('systemMenu') is None, "its submenu is not AppKit's recent-documents menu")
    outlets = [(o.get('property'), o.get('destination')) for o in sub.iter('outlet')] if sub is not None else []
    check(('delegate', delegate_id) in outlets, 'the submenu delegate is AppDelegate')
    app_outlets = [(o.get('property'), o.get('destination')) for c in root.iter('customObject')
                   if c.get('id') == delegate_id for o in c.iter('outlet')]
    check(sub is not None and ('openRecentMenu', sub.get('id')) in app_outlets, 'AppDelegate.openRecentMenu is that submenu')

    print('AppDelegate.mm:')
    methods = [extract(src, a) for a in ('- (NSArray<NSString *> *)recentLocalDocuments:',
                                         '- (void)menuNeedsUpdate:(NSMenu *)menu',
                                         '- (IBAction)onMenuOpenRecent:')]
    check(all(methods), 'recentLocalDocuments:, menuNeedsUpdate:, onMenuOpenRecent: exist')
    vm = extract(src, '- (BOOL)validateMenuItem:')
    check(vm is not None and '@selector(onMenuOpenRecent:)' in vm, 'validateMenuItem: enables the recent items')
    if not all(methods):
        return
    with tempfile.TemporaryDirectory() as tmp:
        text = HARNESS % {'methods': '\n'.join(methods)}
        open(os.path.join(tmp, 'h.m'), 'w').write(text)
        c = subprocess.run(['clang', '-fobjc-arc', '-w', '-framework', 'Cocoa', '-o', os.path.join(tmp, 'h'),
                            os.path.join(tmp, 'h.m')], capture_output=True, text=True)
        if c.returncode:
            sys.stderr.write(c.stderr)
            check(False, 'harness compiles')
            return
        os.makedirs(os.path.join(tmp, 'root'), exist_ok=True)
        out = subprocess.run([os.path.join(tmp, 'h'), os.path.join(tmp, 'root')], capture_output=True, text=True).stdout
        sys.stdout.write(out)
        lines = out.splitlines()
        check('no recents.xml: 1 item(s), first "No Recent Documents" enabled=0' in lines, 'empty list: one disabled "No Recent Documents"')
        items = [l.strip().split(' | ') for l in lines if l.startswith('  ')]
        check(len(items) == 10, 'at most 10 entries')
        titles = [i[0] for i in items]
        check(titles[:3] == ['one.docx', 'same.docx — b', 'same.docx — a'],
              'newest first; same-named files show their folder')
        check(not any('gone' in i[1] or 'cloud' in i[1] for i in items) and '/docs' not in [i[1] for i in items],
              'deleted file, cloud entry and folder left out')
        check(all(i[2] == 'target=1 action=onMenuOpenRecent:' for i in items), 'each entry calls onMenuOpenRecent:')
        check('posted: action=7 path=/docs/one.docx active=1' in lines, 'choosing one opens it like a Finder open')


main()
print('\n%s' % ('ok - File > Open Recent lists and opens the recent local documents' if not failures
                else 'FAILED - %d check(s): %s' % (len(failures), '; '.join(failures))))
sys.exit(0 if not failures else 1)

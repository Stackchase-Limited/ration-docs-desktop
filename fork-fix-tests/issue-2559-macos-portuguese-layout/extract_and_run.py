#!/usr/bin/env python3
"""
#2559 - "Portuguese (Portugal) keyboard layout is detected as Portugues - Brasil
(pt-BR)" (reported on Linux, Hyprland, xkb layout `pt`, ONLYOFFICE 10.0).

Linux, the reporter's platform, is already right in our tree: the xkb description
"Portuguese" maps to pt_PT 0x0816 since desktop-sdk 58801fea (#2503; its test
issue-2503-xkb-portuguese-langid covers it). Checking the other platforms found
the same defect on macOS, which is what this test is about.

Bug (macOS): with "Spelling language detection" on Auto, text typed with the
Portuguese keyboard layout (com.apple.keylayout.Portuguese) was stamped
Portuguese (Brazil), 1046, and spell-checked with pt_BR. The same happened to
every Apple layout whose region macOS drops: British -> en_US, Australian ->
en_US, Canadian -> en_US, Swiss German -> de_DE, Austrian -> de_DE, and the
Serbian layouts got the neutral sr-Latn 0x701a / sr 0x7c1a, which have no
dictionary at all.

Cause: desktop-sdk mac_keyboardlayout.mm, GetKeyboardLayout(). It takes the
first entry of the input source's kTISPropertyInputSourceLanguages. macOS gives
the Portuguese layout and all three Brazilian layouts the same bare "pt" (no
region), and a language without a region gets one from ICU's likely subtags,
which pick the most populous country: pt -> pt_BR, en -> en_US.

Fix: a small table from Apple's input source id to region (and script, for
Serbian Cyrillic) for the layouts whose regional LCID has a dictionary, plus
the rule that a "pt" source whose id does not name Brazil (Brazil/Brasil/ABNT)
is pt_PT. Layouts whose language already carries a region are untouched.

What runs here: the REAL mac_keyboardlayout.mm, compiled whole (Objective-C++,
no ARC, as qmake builds it) against the ICU 74 in core/Common/3dParty/icu.
The only substitution is TISCopyCurrentKeyboardInputSource, renamed by a -D
macro to a driver function that returns the REAL installed input source with a
given id from TISCreateInputSourceList - so the languages array is whatever
this Mac's Text Input Sources report. Nothing in the system keyboard settings
is read as "current" or changed.

BASELINE=1 reads mac_keyboardlayout.mm from BASE_REF (default: the parent of
the commit that landed this fix) and MUST FAIL on every [reported] case.
The integrator re-pins BASE_REF after cherry-picking. Never point it at HEAD.

Deliberately NOT remapped (and asserted unchanged): Canadian-CSA,
CanadianFrench-PC, SwissFrench and Irish. fr_CA, fr_CH and en_IE have no
dictionary and sdkjs does not fall back to fr_FR / en_US (HaveDictionary is an
exact LCID lookup), so the right tag would switch spell checking off. Not
covered: Belgian ("nl" -> nl_NL), LatinAmerican ("es" -> es_ES) and third-party
layouts. Windows is not affected (the HKL low word is
the input language's LANGID, 0x0816 for Portuguese (Portugal)). macOS only;
elsewhere the test prints SKIP and exits 0.
Environment: RD_REPO (desktop-sdk checkout, default ../../desktop-sdk),
RD_ICU (an ICU build dir with include/ and libicuuc.a/libicudata.a).
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
MM = 'ChromiumBasedEditors/lib/src/mac_keyboardlayout.mm'
HDR = 'ChromiumBasedEditors/lib/src/mac_keyboardlayout.h'
BASE_REF = os.environ.get('BASE_REF', 'e9bf91ed^')
BASELINE = bool(os.environ.get('BASELINE'))
ICU_ROOT = os.path.normpath(os.path.join(HERE, '..', '..', 'core', 'Common', '3dParty', 'icu'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


def find_icu():
    if os.environ.get('RD_ICU'):
        return os.environ['RD_ICU']
    d = os.path.join(ICU_ROOT, 'mac_arm64' if platform.machine() == 'arm64' else 'mac_64', 'build')
    if os.path.exists(os.path.join(d, 'libicuuc.a')):
        return d
    raise SystemExit('no ICU build found under %s (set RD_ICU)' % ICU_ROOT)


# input source id -> expected LANGID
CASES = [
    ('com.apple.keylayout.Portuguese',        0x0816, True),   # the report, on macOS
    # the same defect - macOS gives the language only, the region is lost
    ('com.apple.keylayout.British',           0x0809, True),   # en_GB, not en_US
    ('com.apple.keylayout.British-PC',        0x0809, True),
    ('com.apple.keylayout.Australian',        0x0c09, True),   # en_AU
    ('com.apple.keylayout.Canadian',          0x1009, True),   # en_CA
    ('com.apple.keylayout.SwissGerman',       0x0807, True),   # de_CH
    ('com.apple.keylayout.Austrian',          0x0c07, True),   # de_AT
    ('com.apple.keylayout.Serbian-Latin',     0x241a, True),   # sr_Latn_RS, was neutral sr-Latn 0x701a
    ('com.apple.keylayout.Serbian',           0x281a, True),   # sr_Cyrl_RS, was neutral sr 0x7c1a
    # controls: unchanged by the fix
    ('com.apple.keylayout.Brazilian',         0x0416, False),
    ('com.apple.keylayout.Brazilian-ABNT2',   0x0416, False),
    ('com.apple.keylayout.Brazilian-Pro',     0x0416, False),
    ('com.apple.keylayout.US',                0x0409, False),
    ('com.apple.keylayout.ABC',               0x0409, False),
    ('com.apple.keylayout.German',            0x0407, False),
    ('com.apple.keylayout.French',            0x040c, False),
    ('com.apple.keylayout.Spanish',           0x0c0a, False),
    ('com.apple.keylayout.Russian',           0x0419, False),
    # deliberately NOT remapped: fr_CA, fr_CH and en_IE have no dictionary, so the
    # layout keeps the likely-subtags result (fr_FR / en_US) and stays spell-checked
    ('com.apple.keylayout.Canadian-CSA',      0x040c, False),
    ('com.apple.keylayout.CanadianFrench-PC', 0x040c, False),
    ('com.apple.keylayout.SwissFrench',       0x040c, False),
    ('com.apple.keylayout.Irish',             0x0409, False),
    ('com.apple.keylayout.IrishExtended',     0x083c, False),  # "ga" -> ga_IE already
]

DRIVER = r'''
#import <Cocoa/Cocoa.h>
#import <Carbon/Carbon.h>
#include <stdio.h>
#include "mac_keyboardlayout.h"

static NSString *g_wanted = nil;

// Stands in for TISCopyCurrentKeyboardInputSource (renamed by -D): the real
// installed source with the wanted id, retained as the Copy rule requires.
extern "C" TISInputSourceRef rd_current_source(void)
{
    NSDictionary *filter = @{ (__bridge NSString *)kTISPropertyInputSourceID : g_wanted };
    CFArrayRef list = TISCreateInputSourceList((__bridge CFDictionaryRef)filter, true);
    TISInputSourceRef src = NULL;
    if (list && CFArrayGetCount(list) > 0) {
        src = (TISInputSourceRef)CFArrayGetValueAtIndex(list, 0);
        CFRetain(src);
    }
    if (list) CFRelease(list);
    return src;
}

int main(int argc, char **argv)
{
    @autoreleasepool {
        for (int i = 1; i < argc; ++i) {
            g_wanted = [NSString stringWithUTF8String:argv[i]];
            printf("%s|%d\n", argv[i], (int)GetKeyboardLayout());
        }
    }
    return 0;
}
'''


def main():
    if sys.platform != 'darwin':
        print('SKIP #2559: the defect and the code under test are macOS only')
        return 0

    icu = find_icu()
    work = tempfile.mkdtemp(prefix='rd2559-')
    try:
        with open(os.path.join(work, 'mac_keyboardlayout.mm'), 'w') as f:
            f.write(read(MM))
        with open(os.path.join(work, 'mac_keyboardlayout.h'), 'w') as f:
            f.write(read(HDR))
        with open(os.path.join(work, 'driver.mm'), 'w') as f:
            f.write(DRIVER)
        exe = os.path.join(work, 't')
        subprocess.run(['clang++', '-std=c++17', '-w', '-x', 'objective-c++',
                        '-DTISCopyCurrentKeyboardInputSource=rd_current_source',
                        '-I' + work, '-I' + os.path.join(icu, 'include'),
                        os.path.join(work, 'mac_keyboardlayout.mm'), os.path.join(work, 'driver.mm'),
                        '-x', 'none', os.path.join(icu, 'libicuuc.a'), os.path.join(icu, 'libicudata.a'),
                        '-framework', 'Cocoa', '-framework', 'Carbon', '-o', exe], check=True)
        out = subprocess.run([exe] + [c[0] for c in CASES], capture_output=True, text=True, check=True).stdout
        got = dict((l.split('|')[0], int(l.split('|')[1])) for l in out.strip().splitlines())

        fails = 0
        for sid, lid, reported in CASES:
            g = got[sid]
            if g == 0 and not reported:
                print('  skip  %-36s (not installed on this Mac)' % sid)
                continue
            ok = g == lid
            fails += 0 if ok else 1
            print('  %s  %-36s -> 0x%04x   (want 0x%04x)%s' % (
                'ok  ' if ok else 'FAIL', sid, g, lid, '  [reported]' if reported else ''))
        if BASELINE:
            print('BASELINE (%s): every [reported] case must FAIL' % BASE_REF)
        print('%s #2559 (%d failed)' % ('FAIL' if fails else 'PASS', fails))
        return 1 if fails else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())

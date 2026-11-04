#!/usr/bin/env python3
"""
#2503 - "Document language switches to Portuguese while typing in English"
(Linux, KDE Wayland / Hyprland, xkb layout `pt`).

Bug: with "Spelling language detection" on Auto, every word typed is stamped
with the keyboard's language - by design - but a Portugal keyboard was reported
as Portuguese (Brazil): the reporter's document holds runs tagged pt-BR although
the active keymap is xkb's "Portuguese" (`pt`).

Cause: desktop-sdk keyboardlayout.cpp, layoutNameToLocaleName(). On Linux the
active layout's xkb *description* is turned into a locale. A description that
names only a language gets its region from ICU's likely subtags, which pick the
most populous country: pt -> pt_BR (0x0416). xkb's bare "Portuguese" is the pt
layout (Portugal); Brazil is the separate "Portuguese (Brazil)". The same
function also took xkb's "UK" ("English (UK)") verbatim as a region; ICU has no
LCID for en_UK and answers the neutral 0x0009, which has no dictionary.

Fix: map a bare "pt" to PT and the region "UK" to GB before building the locale.

What runs here: the REAL trim / layoutNameToLocaleName / layoutNameToLangId,
extracted from keyboardlayout.cpp by brace matching, compiled against the ICU 74
that ships in core/Common/3dParty/icu (no ICU logic is copied). The xkb/X11
part (reading which layout is active) is not compiled: it only supplies the
description string, which is what the cases below feed in.

BASELINE=1 reads keyboardlayout.cpp from BASE_REF (default: the parent of the
commit that landed this fix) and MUST FAIL on "Portuguese" and "English (UK)".
The integrator re-pins BASE_REF after cherry-picking. Never point it at HEAD.

NOT claimed: that the retag-as-you-type behaviour is changed (it is not; turning
the detection setting off is what stops it, see #2543), and nothing here runs a
real X server - the description strings are xkb's, taken from evdev.xml.
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
CPP = 'ChromiumBasedEditors/lib/src/keyboardlayout.cpp'
BASE_REF = os.environ.get('BASE_REF', '58801fea^')
BASELINE = bool(os.environ.get('BASELINE'))
ICU_ROOT = os.path.normpath(os.path.join(HERE, '..', '..', 'core', 'Common', '3dParty', 'icu'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


def brace_match(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces')


def extract(src, signature):
    at = src.find(signature)
    if at == -1:
        raise SystemExit('%s not found - the extractor needs updating' % signature)
    return brace_match(src, at)


def find_icu():
    if os.environ.get('RD_ICU'):
        return os.environ['RD_ICU']
    machine = platform.machine()
    if sys.platform == 'darwin':
        cands = ['mac_arm64' if machine == 'arm64' else 'mac_64']
    else:
        cands = ['linux_arm64' if machine in ('aarch64', 'arm64') else 'linux_64']
    for c in cands:
        d = os.path.join(ICU_ROOT, c, 'build')
        if os.path.exists(os.path.join(d, 'libicuuc.a')):
            return d
    raise SystemExit('no ICU build found under %s (set RD_ICU)' % ICU_ROOT)


# xkb description -> (expected locale, expected LANGID)
CASES = [
    ('Portuguese',            'pt_PT', 0x0816, True),   # the report: pt layout, Portugal
    ('English (UK)',          'en_GB', 0x0809, True),   # "UK" is not an ISO region
    # controls: unchanged by the fix
    ('Portuguese (Brazil)',   'pt_BR', 0x0416, False),
    ('English (US)',          'en_US', 0x0409, False),
    ('German',                'de_DE', 0x0407, False),
    ('German (Switzerland)',  'de_CH', 0x0807, False),
    ('French',                'fr_FR', 0x040c, False),
    ('Spanish',               'es_ES', 0x0c0a, False),
    ('Russian',               'ru_RU', 0x0419, False),
    ('Ukrainian',             'uk_UA', 0x0422, False),
]


def main():
    src = read(CPP)
    funcs = '\n'.join(extract(src, s) for s in (
        'static std::string trim(',
        'static std::string layoutNameToLocaleName(',
        'static uint16_t layoutNameToLangId(',
    ))
    calls = '\n'.join('\tshow("%s");' % c[0] for c in CASES)
    program = r'''
#include <string>
#include <list>
#include <sstream>
#include <algorithm>
#include <cctype>
#include <cstdio>
#include "unicode/locid.h"
#include "unicode/uloc.h"
#define LANGIDFROMLCID(lcid) ((uint16_t)(lcid))
%s
static void show(const char* n) { printf("%%s|%%s|%%d\n", n, layoutNameToLocaleName(n).c_str(), (int)layoutNameToLangId(n)); }
int main() {
%s
	return 0;
}
''' % (funcs, calls)

    icu = find_icu()
    work = tempfile.mkdtemp(prefix='rd2503-')
    try:
        cpp = os.path.join(work, 't.cpp')
        exe = os.path.join(work, 't')
        with open(cpp, 'w') as f:
            f.write(program)
        subprocess.run(['c++', '-std=c++17', '-w', '-I' + os.path.join(icu, 'include'), cpp,
                        os.path.join(icu, 'libicuuc.a'), os.path.join(icu, 'libicudata.a'),
                        '-o', exe] + ([] if sys.platform == 'darwin' else ['-lpthread', '-ldl']), check=True)
        out = subprocess.run([exe], capture_output=True, text=True, check=True).stdout
        got = {}
        for line in out.strip().splitlines():
            name, loc, lid = line.split('|')
            got[name] = (loc, int(lid))

        fails = 0
        for name, loc, lid, reported in CASES:
            g = got[name]
            ok = g == (loc, lid)
            fails += 0 if ok else 1
            print('  %s  %-22s -> %-6s 0x%04x   (want %s 0x%04x)%s' % (
                'ok  ' if ok else 'FAIL', name, g[0], g[1], loc, lid, '  [reported]' if reported else ''))
        if BASELINE:
            print('BASELINE (%s): "Portuguese" and "English (UK)" must FAIL' % BASE_REF)
        print('%s #2503 (%d failed)' % ('FAIL' if fails else 'PASS', fails))
        return 1 if fails else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())

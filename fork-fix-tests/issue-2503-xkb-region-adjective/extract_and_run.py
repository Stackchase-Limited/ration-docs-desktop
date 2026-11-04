#!/usr/bin/env python3
"""
#2503 (follow-up) - an xkb layout whose region is written as an adjective is
reported as the wrong country: "English (Australian)" -> en_US.

Cause: desktop-sdk keyboardlayout.cpp, layoutNameToLocaleName(). The bracketed
parts of the xkb description are matched against ICU's English country display
names with name.find(part) - the part must be a substring of the country name.
"Australian" is not a substring of "Australia", so no region was found and the
likely-subtags fallback picked en_US. xkeyboard-config described the au layout
as "English (Australian)" from at least 2.10 up to 2.38 (2.41 and later say
"English (Australia)").

Fix: region matching also accepts the regular English adjective forms of a
one-word country name (a lambda in that function): +n (Australian), +ian
(Brazilian), +i (Iraqi), a/o/y -> an/ian (Canadian, Mexican, Hungarian),
-um -> an (Belgian) - and "Swiss" for Switzerland.

What runs here: the REAL trim / layoutNameToLocaleName /
layoutNameToLangId, extracted from keyboardlayout.cpp by brace matching and
compiled against the ICU 74 bundled in core/Common/3dParty/icu. Cases:
  - real xkb descriptions (base.xml of xkeyboard-config 2.10.1 .. master),
    including the reported one and controls that must not move, among them
    parts that are adjectives but NOT regions ("Polish (British keyboard)",
    "Kazakh (with Russian)", "Russian (Polish)");
  - adjective forms not currently in xkb ([form]), to show the rule is general
    rather than an Australia special case.
Measured while writing the fix (not re-run here, needs the registries): over all
953 distinct layout/variant descriptions of xkeyboard-config 2.10.1, 2.20,
2.23.1, 2.29, 2.33, 2.38, 2.41 and master, the only result that changes is
"English (Australian)" en_US -> en_AU.

BASELINE=1 reads keyboardlayout.cpp from BASE_REF (default: the parent of the
fix commit) and MUST FAIL on the reported case and the [form] cases.
The integrator re-pins BASE_REF after cherry-picking. Never point it at HEAD.

NOT claimed: top-level descriptions that are a country adjective in the
LANGUAGE slot ("Belgian", "Canadian (CSA)", "Indian", "Iraqi") still give no
language - which language a Belgian keyboard types is not in the name; nothing
here runs a real X server.
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
BASE_REF = os.environ.get('BASE_REF', 'c430d3b140^')
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


# xkb description -> (expected locale, expected LANGID, fixed by this change)
CASES = [
    ('English (Australian)',        'en_AU', 0x0c09, True),   # the report; xkb <= 2.38
    # adjective forms, not in xkb today: the rule is general
    ('English (Canadian)',          'en_CA', 0x1009, True),   # [form]
    ('French (Canadian)',           'fr_CA', 0x0c0c, True),   # [form]
    ('German (Swiss)',              'de_CH', 0x0807, True),   # [form]
    ('French (Belgian)',            'fr_BE', 0x080c, True),   # [form]
    ('Portuguese (Brazilian)',      'pt_BR', 0x0416, True),   # [form]
    ('German (Austrian)',           'de_AT', 0x0c07, True),   # [form]
    ('Arabic (Iraqi)',              'ar_IQ', 0x0801, True),   # [form]
    ('Spanish (Mexican)',           'es_MX', 0x080a, True),   # [form]
    # controls, real xkb descriptions: unchanged
    ('English (Australia)',         'en_AU', 0x0c09, False),  # xkb >= 2.41
    ('English (Canada)',            'en_CA', 0x1009, False),
    ('French (Canada)',             'fr_CA', 0x0c0c, False),
    ('German (Switzerland)',        'de_CH', 0x0807, False),
    ('French (Switzerland)',        'fr_CH', 0x100c, False),
    ('German (Austria)',            'de_AT', 0x0c07, False),
    ('Portuguese (Brazil)',         'pt_BR', 0x0416, False),
    ('Arabic (Iraq)',               'ar_IQ', 0x0801, False),
    ('English (UK)',                'en_GB', 0x0809, False),
    ('English (US)',                'en_US', 0x0409, False),
    ('Portuguese',                  'pt_PT', 0x0816, False),
    ('Polish (British keyboard)',   'pl_PL', 0x0415, False),  # adjective, but not a region
    ('Kazakh (with Russian)',       'kk_KZ', 0x043f, False),
    ('Russian (Polish)',            'ru_RU', 0x0419, False),
    ('Spanish (Latin American)',    'es_ES', 0x0c0a, False),
    ('English (Macintosh)',         'en_US', 0x0409, False),
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
                'ok  ' if ok else 'FAIL', name, g[0], g[1], loc, lid, '  [fixed here]' if reported else ''))
        if BASELINE:
            print('BASELINE (%s): "English (Australian)" and the [form] cases must FAIL' % BASE_REF)
        print('%s #2503 region adjective (%d failed)' % ('FAIL' if fails else 'PASS', fails))
        return 1 if fails else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())

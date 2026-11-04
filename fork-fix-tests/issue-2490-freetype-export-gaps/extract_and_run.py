#!/usr/bin/env python3
r"""
#2490 - segfault in the GTK file chooser when a file/folder name contains an emoji.

Same defect as #2136, already fixed in core 382bf81452: libgraphics.so compiles
FreeType 2.10.4 into itself and FT_EXPORT gives its API visibility("default")
(freetype-2.10.4/include/freetype/config/public-macros.h:77) despite the
-fvisibility=hidden that base.pri's config_hidden_symbols adds, so cairo/pango
bound their FT_* calls to our copy. graphics.version localises FT_*, ft_*, hb_*,
_hb_*, Brotli* on Linux.

What was still open: `FT_*` is a glob and FreeType also FT_EXPORTs names that
do not start with "FT_" - the cache API FTC_* and TT_New_Context / TT_RunIns.
Those stayed in the process-wide scope. Nothing in the GTK stack is known to call
them, so this is the same mechanism with a smaller target, closed for good
measure; the reporter's crash itself is the FT_* part #2136 already handled.

How this is checked without an ELF toolchain (none on the dev Macs):
  * the REAL exported symbol set is taken from the in-tree macOS build of
    libgraphics (core/build/lib/mac_arm64/graphics.framework). Both platforms
    compile with -fvisibility=hidden, so what macOS exports is exactly the set
    with explicit default visibility - i.e. what ELF exports before the version
    script is applied. (Static archives - heif, de265, x265 - also show up on
    macOS but are hidden on Linux by -Wl,--exclude-libs,ALL; they are not
    checked here.)
  * the REAL graphics.version is parsed and its `local:` patterns are applied
    with fnmatch, which is the glob semantics GNU ld / lld use for version
    script patterns;
  * a name counts as FreeType's when it occurs in the bundled freetype-2.10.4
    tree.
Every FreeType name in the exported set must be matched by a local pattern.
It also checks graphics.pro still passes the script on Linux.

NOT verified: an actual Linux link, `nm -D` on a real libgraphics.so, or the
crash itself (needs a Linux GTK session with an emoji folder).

  RD_REPO     core checkout (default ../../core)
  RD_GRAPHICS path to a built graphics binary (default the in-tree mac_arm64 one;
              falls back to ../../core/build/... when RD_REPO is a worktree)
  BASELINE=1  read graphics.version / graphics.pro from BASE_REF; must FAIL there.
Exit 0 pass, 1 fail, 77 no built libgraphics to read.
"""
import fnmatch
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN_CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
CORE = os.environ.get('RD_REPO') or MAIN_CORE
BASE_REF = os.environ.get('BASE_REF', '003448ba5a^')
BASELINE = bool(os.environ.get('BASELINE'))

VERSION = 'DesktopEditor/graphics/pro/graphics.version'
PRO = 'DesktopEditor/graphics/pro/graphics.pro'
FT_TREE = 'DesktopEditor/freetype-2.10.4'


def source(rel):
    if BASELINE:
        r = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                           capture_output=True, check=True)
        return r.stdout.decode('utf-8')
    with open(os.path.join(CORE, rel), encoding='utf-8') as f:
        return f.read()


def find_binary():
    if os.environ.get('RD_GRAPHICS'):
        return os.environ['RD_GRAPHICS']
    for root in (CORE, MAIN_CORE):
        p = os.path.join(root, 'build', 'lib', 'mac_arm64', 'graphics.framework', 'graphics')
        if os.path.exists(p):
            return p
    return None


binary = find_binary()
if not binary:
    sys.stderr.write('no built libgraphics to read - skipping\n')
    sys.exit(77)

print('%s (%s)' % (CORE, ('BASELINE ' + BASE_REF) if BASELINE else 'working tree'))
print('exported symbols from %s' % binary)

failures = 0

# ---- the script is still applied on Linux ------------------------------------
pro = source(PRO)
applied = re.search(r'core_linux:graphics_dynamic_library\s*\{[^}]*--version-script,\$\$PWD/graphics\.version', pro)
print('  %-70s %s' % ('graphics.pro passes graphics.version to the Linux link', 'ok' if applied else 'FAILED'))
failures += not applied

# ---- the real local: patterns -------------------------------------------------
script = re.sub(r'/\*.*?\*/', '', source(VERSION), flags=re.S)
m = re.search(r'local\s*:(.*?)(?:global\s*:|\}\s*;)', script, re.S)
if not m:
    raise SystemExit('no local: block in %s' % VERSION)
patterns = [p.strip() for p in m.group(1).split(';') if p.strip()]
print('  local patterns: %s' % ' '.join(patterns))

# ---- the real exported set (C names only; macOS prefixes a '_') --------------
nm = subprocess.run(['nm', '-gU', binary], capture_output=True, text=True, check=True).stdout
exported = sorted({l.split()[-1][1:] for l in nm.splitlines()
                   if l.split() and l.split()[-1].startswith('_') and not l.split()[-1].startswith('__Z')})

# ---- which of them are FreeType's ---------------------------------------------
ft_root = os.path.join(MAIN_CORE if BASELINE else CORE, FT_TREE)
ft_text = []
for d, _, files in os.walk(ft_root):
    for f in files:
        if f.endswith(('.c', '.h')):
            with open(os.path.join(d, f), encoding='latin-1') as fh:
                ft_text.append(fh.read())
ft_text = '\n'.join(ft_text)
ft_names = [s for s in exported if re.search(r'\b%s\s*\(' % re.escape(s), ft_text)]

leaked = [s for s in ft_names if not any(fnmatch.fnmatchcase(s, p) for p in patterns)]
print('  FreeType names exported before the script: %d' % len(ft_names))
for s in leaked:
    print('    still global on Linux: %s' % s)
ok = bool(ft_names) and not leaked
print('  %-70s %s' % ('every exported FreeType name is localised by graphics.version',
                      'ok' if ok else 'FAILED'))
failures += not ok

print('\n%s' % ('FAILED - bundled FreeType names would still be exported from libgraphics.so'
                if failures else 'ok - no bundled FreeType name is left in the global scope'))
sys.exit(1 if failures else 0)

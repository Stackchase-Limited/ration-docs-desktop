#!/usr/bin/env python3
"""
#1433 - "linux appimage format cannot launch": GLib-GIO-ERROR "Settings schema
'org.gnome.desktop.interface' is not installed", then trace trap.

Our tree builds no AppImage (that is a separate upstream repository), and the schema
in the report is not one our code reads. But our code has the same crash:
desktop-apps win-linux/src/components/cnotification.cpp isNotificationsEnabled()
called g_settings_new("org.gnome.desktop.notifications") on GNOME and
g_settings_new("org.cinnamon.desktop.notifications") on Cinnamon, which abort the
process when the schema (or the key) is not installed. XDG_CURRENT_DESKTOP is
inherited, the schemas are not: an AppImage, a toolbox/distrobox container on a
GNOME host, a minimal install. It also g_object_unref()'d a GVariant.

This extracts the REAL isNotificationsEnabled (and readBoolSetting when present)
by brace matching, compiles it against glib/gio and Qt5 DBus in the
rd-linux-verify:24.04 image with WindowHelper stubbed to GNOME / CINNAMON, and runs:
  1. no schemas at all (GSETTINGS_SCHEMA_DIR = empty folder)  -> must not abort,
     and reports notifications enabled;
  2. the schema without the key                               -> same;
  3. the schema with show-banners=false / display-notifications=false (memory
     backend default)                                          -> reports disabled,
     i.e. the setting is still honoured.

NOT claimed: which component aborts in the upstream AppImage (Chromium's or Qt's
GTK code reading org.gnome.desktop.interface is likely; not in our sources), or
the notification UI itself.

  RD_REPO=<desktop-apps> (default ../../desktop-apps)
  BASELINE=1 [BASE_REF=<ref>]  - must fail. Needs docker + rd-linux-verify:24.04 (77 if absent).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/components/cnotification.cpp'
BASE_REF = os.environ.get('BASE_REF', 'a314de8d2^')
IMAGE = os.environ.get('RD_LINUX_IMAGE', 'rd-linux-verify:24.04')


def block(text, name):
    m = re.search(r'^static [\w \*]+\b%s\s*\(' % re.escape(name), text, re.M)
    if not m:
        return None
    i = text.index('{', m.end())
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[m.start():j + 1]
    raise SystemExit('unbalanced braces in ' + name)


HARNESS = r'''
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusMessage>
#include <QDBusVariant>
#include <QVariant>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#undef signals
#include <gio/gio.h>
namespace WindowHelper {
    enum { UNITY, GNOME, KDE, XFCE, CINNAMON, OTHER };
    static int env = GNOME;
    static int getEnvInfo() { return env; }
}
%(helper)s
%(fn)s
int main(int argc, char **argv) {
    WindowHelper::env = strcmp(argv[1], "cinnamon") == 0 ? WindowHelper::CINNAMON : WindowHelper::GNOME;
    printf("result=%%d\n", (int)isNotificationsEnabled());
    return 0;
}
'''

SCHEMAS = {
    'full': '''<schemalist>
 <schema id="org.gnome.desktop.notifications" path="/org/gnome/desktop/notifications/">
  <key name="show-banners" type="b"><default>false</default></key></schema>
 <schema id="org.cinnamon.desktop.notifications" path="/org/cinnamon/desktop/notifications/">
  <key name="display-notifications" type="b"><default>false</default></key></schema>
</schemalist>''',
    'nokey': '''<schemalist>
 <schema id="org.gnome.desktop.notifications" path="/org/gnome/desktop/notifications/">
  <key name="something-else" type="b"><default>false</default></key></schema>
 <schema id="org.cinnamon.desktop.notifications" path="/org/cinnamon/desktop/notifications/">
  <key name="something-else" type="b"><default>false</default></key></schema>
</schemalist>''',
}

SCRIPT = r'''
cd /tmp
g++ -std=c++14 -fPIC -o h /work/h.cpp $(pkg-config --cflags --libs Qt5DBus Qt5Core gio-2.0) || exit 3
mkdir -p none
for v in full nokey; do mkdir -p $v && cp /work/$v.gschema.xml $v/rd.gschema.xml && glib-compile-schemas $v || exit 4; done
for v in none nokey full; do for d in gnome cinnamon; do
  out=$(GSETTINGS_SCHEMA_DIR=/tmp/$v GSETTINGS_BACKEND=memory XDG_DATA_DIRS=/nonexistent ./h $d 2>&1); rc=$?
  echo "$v $d rc=$rc $(echo "$out" | grep -o 'result=[01]' | head -1)"
done; done
'''


def main():
    if not shutil.which('docker') or subprocess.run(['docker', 'image', 'inspect', IMAGE], capture_output=True).returncode:
        print('SKIP docker or %s not available' % IMAGE); return 77
    if os.environ.get('BASELINE'):
        src = subprocess.run(['git', '-C', REPO, 'show', BASE_REF + ':' + REL], capture_output=True, text=True, check=True).stdout
    else:
        src = open(os.path.join(REPO, REL), encoding='utf-8').read()
    fn = block(src, 'isNotificationsEnabled')
    if not fn:
        raise SystemExit('isNotificationsEnabled not found - the extractor needs updating')
    helper = block(src, 'readBoolSetting') or ''
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, 'h.cpp'), 'w').write(HARNESS % {'fn': fn, 'helper': helper})
        for k, v in SCHEMAS.items():
            open(os.path.join(d, k + '.gschema.xml'), 'w').write(v)
        open(os.path.join(d, 'run.sh'), 'w').write(SCRIPT)
        r = subprocess.run(['docker', 'run', '--rm', '-v', d + ':/work:ro', IMAGE, 'sh', '/work/run.sh'],
                           capture_output=True, text=True, timeout=600)
    if r.returncode:
        print(r.stdout + r.stderr); print('FAILED - harness did not build'); return 1
    rows = {tuple(l.split()[:2]): l for l in r.stdout.splitlines() if 'rc=' in l}
    fails = 0
    for (v, de), want in (((s, e), w) for s, w in (('none', 1), ('nokey', 1), ('full', 0)) for e in ('gnome', 'cinnamon')):
        line = rows.get((v, de), '')
        ok = 'rc=0' in line and ('result=%d' % want) in line
        what = {'none': 'schema not installed', 'nokey': 'schema without the key', 'full': 'setting off'}[v]
        print('  %-9s %-24s %-28s %s' % (de, what, line.split(' ', 2)[-1] if line else '?', 'ok' if ok else 'FAILED'))
        fails += 0 if ok else 1
    print('FAILED' if fails else 'ok - a missing GSettings schema no longer kills the app; the setting is still read')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

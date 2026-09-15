#!/usr/bin/env python3
"""
#2216 - GTK dialogs stopped following the desktop's theme in 9.2.0.

cthemes.cpp applyGtkTheme used to set GTK_THEME and gtk-theme-name to Adwaita
unconditionally (added by f59a46a0b, 2025-09-09), which replaces whatever GTK
theme the user runs - Breeze, Yaru, Arc - with Adwaita for every GTK window the
application opens.

The case it was written for is real and is described in gtkutils.cpp's
sync_color_scheme: inside a Flatpak sandbox, and on desktops publishing no GTK
preference at all (KDE among them), GTK resolves to plain light Adwaita, so a user
who had chosen a dark editor theme still got a white Save As window. The fix keeps
that, and only overrides when GTK resolved to Adwaita anyway - the "no theme
configured" case - leaving a user's own theme alone and letting
gtk-application-prefer-dark-theme ask it for its dark variant instead.

This extracts the real userHasOwnGtkTheme by brace matching and links it against
the real GLib, so g_strcmp0 is the actual function and not a stand-in.

BASELINE=1 runs against HEAD, where the predicate does not exist - the override
was unconditional, which is the defect.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/cthemes.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '325ecd480a^')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()

at = source.find('static bool userHasOwnGtkTheme(')
if at == -1:
    sys.stderr.write(
        'userHasOwnGtkTheme not found - applyGtkTheme still forces Adwaita over the '
        "user's own GTK theme unconditionally (#2216)\n")
    sys.exit(1)
open_brace = source.index('{', at)
depth = 0
for i in range(open_brace, len(source)):
    if source[i] == '{':
        depth += 1
    elif source[i] == '}':
        depth -= 1
        if depth == 0:
            end = i
            break
fn = source[at:end + 1]

harness = r'''
#include <glib.h>
#include <stdio.h>

%s

static int failures = 0;
static void check(const char *current, bool want, const char *why) {
    bool got = userHasOwnGtkTheme(current, "Adwaita", "Adwaita-dark");
    printf("  gtk-theme-name=%%-18s left alone=%%-5s  %%-34s %%s\n",
           current ? (*current ? current : "\"\"") : "(null)",
           got ? "yes" : "no", why, got == want ? "ok" : "FAILED");
    if (got != want) failures++;
}

int main() {
    /* A user with a real theme: we must not touch it. */
    check("Breeze",       true,  "the user's own theme");
    check("Yaru-dark",    true,  "the user's own theme");
    check("Arc-Darker",   true,  "the user's own theme");
    check("Adwaita-Blue", true,  "a different theme, not ours");

    /* Nothing configured, or already Adwaita: overriding takes nothing away. */
    check("Adwaita",      false, "GTK's default - safe to name dark");
    check("Adwaita-dark", false, "already ours");
    check("",             false, "unset");
    check(NULL,           false, "unset");

    printf("\n%%s\n", failures ? "FAILED"
        : "ok - a user's GTK theme survives; only GTK's own default is overridden");
    return failures ? 1 : 0;
}
''' % fn

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(src, 'w').write(harness)
    cflags = subprocess.run(['pkg-config', '--cflags', '--libs', 'glib-2.0'],
                            capture_output=True, text=True)
    if cflags.returncode != 0:
        sys.stderr.write('glib-2.0 not found via pkg-config\n')
        sys.exit(2)
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-o', exe, src]
                       + cflags.stdout.split(), capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)

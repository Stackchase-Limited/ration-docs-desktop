#!/usr/bin/env python3
"""
#2229 - the window edge is almost invisible in Modern Light, so overlapping documents
run together.

Two halves, and only one of them is ours to fix.

Native drop shadows are not: the shell draws its own frameless window
(CWindowBase::applyTheme -> setWindowColors, cwindowbase.cpp:139-145) and a shadow
around it would have to come from the compositor, which on Wayland means the Qt Wayland
port already concluded for #2287/#2285. Nothing to do here.

The border is. It is one value per theme, `window-border`, read into ecrWindowBorder by
cthemes.cpp:87 and painted against `window-background`. In Modern Light that pairing was
#d9d9d9 on #eaeaea: a contrast ratio of 1.17:1, which is why the reporter had to look
closely to see whether there was a border at all. WCAG 2.1 SC 1.4.11 asks 3:1 of the
visual information needed to identify a user interface component, and a window boundary
is exactly that, so this is a measurable threshold rather than a matter of taste - which
is the only reason it is being treated as a defect and not a design preference.

The test reads the shipped theme files and computes the real WCAG relative-luminance
ratio over them. No colour is written down here; the themes are the artifact under test.

BASELINE=1 reads the same files from before the fix, where five of the seven themes are
under 3:1 and the two Modern light ones are close to invisible.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
STYLE_DIR = 'win-linux/res/styles'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '1509c6228e^')
BASELINE = bool(os.environ.get('BASELINE'))

MINIMUM = 3.0  # WCAG 2.1 SC 1.4.11, non-text contrast


def theme_files():
    out = subprocess.run(['git', '-C', REPO, 'ls-files', STYLE_DIR + '/theme-*.json'],
                         capture_output=True, text=True, check=True).stdout
    names = [n for n in out.splitlines() if n.strip()]
    if not names:
        raise SystemExit('no theme files found under %s' % STYLE_DIR)
    return sorted(names)


def read(rel):
    if BASELINE:
        text = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    else:
        text = open(os.path.join(REPO, rel), encoding='utf-8').read()
    return json.loads(text)


def channel(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour):
    h = hex_colour.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        raise SystemExit('not a hex colour: %r' % hex_colour)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


print('reading %s from %s\n' % (STYLE_DIR, ('%s (BASELINE)' % BASE_REF) if BASELINE
                                else 'the working tree'))

failures = 0
for rel in theme_files():
    values = read(rel).get('values', {})
    border = values.get('window-border')
    background = values.get('window-background')
    if not border or not background:
        print('  %-26s window-border / window-background missing   FAILED'
              % os.path.basename(rel))
        failures += 1
        continue

    ratio = contrast(border, background)
    ok = ratio >= MINIMUM
    print('  %-26s border %-9s on %-9s  %.2f:1  %s'
          % (os.path.basename(rel), border, background, ratio,
             'ok' if ok else 'FAILED - below %.1f:1' % MINIMUM))
    if not ok:
        failures += 1

print('\n%s' % ('FAILED' if failures else
                'ok - every theme draws a window edge that clears %.1f:1' % MINIMUM))
sys.exit(1 if failures else 0)

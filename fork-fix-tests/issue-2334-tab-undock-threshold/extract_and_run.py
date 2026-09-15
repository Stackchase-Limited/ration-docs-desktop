#!/usr/bin/env python3
"""
#2334 - dragging a tab tears it into its own window at the slightest wobble.

CTabBar::eventFilter turned a tab drag into an undock the moment the pointer left
the tab strip's rectangle - in any direction, by any distance:

    if (!d->tabArea->rect().contains(me->pos())) { ... emit tabUndock ... }

The strip is a thin horizontal band, so there is no vertical slack at all, and the
test also fires on horizontal overshoot, which is part of an ordinary reorder:
dragging the first tab past the left end of the strip is how you say "put this one
first". On Hyprland, where the reporter hit it, the result is a new window that the
application then offers no way to merge back.

The fix makes the gesture vertical and gives it a threshold of one strip height -
taken from the strip rather than from a constant because CTabBar keeps no scaling
factor of its own, and the strip is what grows with the DPI.

This runs the real condition from the real source: the `if (...)` text is lifted out
of ctabbar.cpp verbatim and compiled against tiny stand-ins for `d` and `me`, and the
helper it calls is extracted by brace matching. Nothing here is a copy of the logic.

BASELINE=1 re-reads ctabbar.cpp from git, where the condition is the bare
`!rect().contains(pos)` - and the run fails on every wobble and every overshoot.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/components/ctabbar.cpp'
BASE_REF = os.environ.get('BASE_REF', 'HEAD')

if os.environ.get('BASELINE'):
    source = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                            capture_output=True, text=True, check=True).stdout
else:
    source = open(os.path.join(REPO, REL), encoding='utf-8').read()


def brace_match(src, at):
    open_brace = src.index('{', at)
    depth = 0
    for i in range(open_brace, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces extracting from %s' % REL)


# The undock decision, exactly as the file spells it.
MARKER = '// bool undockDirectionIsValid'
at = source.find(MARKER)
if at == -1:
    raise SystemExit('the undock call site moved - %s no longer has %r' % (REL, MARKER))
line = source[source.index('\n', at) + 1:]
line = line[:line.index('\n')].strip()
if not line.startswith('if (') or not line.endswith('{'):
    raise SystemExit('unexpected undock call site: %r' % line)
cond = line[len('if ('):line.rindex(')')].replace('/*&& undockDirectionIsValid*/', '').strip()

# The helper it calls, if the fix is in.
helper = ''
at = source.find('static bool tabDragLeavesBar(')
if at != -1:
    helper = brace_match(source, at)

harness = r'''
#include <QRect>
#include <QPoint>
#include <stdio.h>

%(helper)s

/* Stand-ins for the two objects the condition names, so the condition below can be
   the file's own text. Neither carries any logic. */
struct FakeTabArea { QRect r; QRect rect() const { return r; } };
struct FakeD { FakeTabArea *tabArea; };
struct FakeMouse { QPoint p; QPoint pos() const { return p; } };

static FakeTabArea g_area;
static FakeD g_d = { &g_area };
static FakeD *d = &g_d;

static bool wouldUndock(const QRect &bar, const QPoint &pos) {
    g_area.r = bar;
    FakeMouse mouse; mouse.p = pos;
    FakeMouse *me = &mouse;
    (void)me;
    return (%(cond)s);
}

static int failures = 0;
static void check(const QRect &bar, const QPoint &pos, bool want, const char *why) {
    bool got = wouldUndock(bar, pos);
    printf("  bar %%dx%%d  pointer (%%4d,%%4d)  undocks=%%-5s  %%-44s %%s\n",
           bar.width(), bar.height(), pos.x(), pos.y(), got ? "yes" : "no", why,
           got == want ? "ok" : "FAILED");
    if (got != want) failures++;
}

int main() {
    /* A 32px tab strip, 800px wide: the ordinary case. */
    const QRect bar(0, 0, 800, 32);
    check(bar, QPoint(400,  16), false, "on the strip - a reorder");
    check(bar, QPoint(400,  -1), false, "one pixel above - a wobble");
    check(bar, QPoint(400,  32), false, "one pixel below - a wobble");
    check(bar, QPoint(400,  60), false, "most of a tab height below - still a drag");
    check(bar, QPoint(400,  64), true,  "a tab height below - meant it");
    check(bar, QPoint(400, 300), true,  "dragged into the document");
    check(bar, QPoint(400, -40), true,  "a tab height above - meant it");
    check(bar, QPoint(900,  16), false, "past the right end - reorder, not undock");
    check(bar, QPoint(-60,  16), false, "past the left end - reorder, not undock");
    check(bar, QPoint(-60,   0), false, "left end, top row - reorder, not undock");

    /* The same strip at 200%%: the threshold has to grow with it. */
    const QRect hidpi(0, 0, 1600, 64);
    check(hidpi, QPoint(800,  90), false, "hidpi: 27px below - a wobble");
    check(hidpi, QPoint(800, 128), true,  "hidpi: a tab height below - meant it");

    printf("\n%%s\n", failures ? "FAILED"
        : "ok - a tab undocks only when dragged clear of the strip, and never sideways");
    return failures ? 1 : 0;
}
''' % {'helper': helper, 'cond': cond}

print('condition under test: %s' % cond)
print('helper extracted:     %s\n' % ('yes' if helper else 'no - HEAD has none'))
sys.stdout.flush()

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'harness.cpp')
    exe = os.path.join(tmp, 'harness')
    open(src, 'w').write(harness)
    Q = '/opt/homebrew/opt/qt@5'
    c = subprocess.run(['clang++', '-std=c++14', '-Wall', '-o', exe, src,
                        '-I' + Q + '/lib/QtCore.framework/Headers',
                        '-F' + Q + '/lib', '-framework', 'QtCore'],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)

#!/usr/bin/env python3
"""
#2161 - Linux: a landscape spreadsheet prints with a ~3in left margin and the right
side cut off. The reporter's CUPS log is the whole diagnosis:

    media=Custom.279x216mm
    WARN: Could not determine the output page dimensions, falling back to US Letter
    WARN: Could not determine the width of the left/right/top/bottom margins

A plain US Letter sheet reached CUPS as *custom* media. gtkprintdialog.cpp resolved the
standard GTK paper name for the page and then threw it away:

    const QString paper_name = gtkPaperNameFromPageSize(page_size);
    GtkPaperSize *psize = gtk_paper_size_new_custom(paper_name.toUtf8().data(), ...);

gtk_paper_size_new_custom() always builds a custom size - is_custom is TRUE and
gtk_paper_size_get_ppd_name() returns NULL no matter what name you hand it - so the
CUPS backend had no media name to send and fell back to "Custom.<w>x<h>mm", which
carries no margins. In portrait CUPS' own fallback media is the same shape and the page
survives; in landscape the job is laid out 279x216 on a 216x279 fallback, and that 63mm
is the wide left margin and the lost right edge.

The lookup also only ever matched portrait: gtk_paper_size_get_paper_sizes() lists
portrait sizes, so a size already swapped for landscape upstream matched nothing at all
and went down the custom branch by a second route.

Nothing here is a restatement of that. gtkPaperNameFromPageSize() and the paper-size
construction are lifted from gtkprintdialog.cpp by brace matching and compiled against
the real GTK 3 and the real QtCore, so GtkPaperSize answers for itself.

BASELINE=1 re-reads the file from before the fix - where the construction is the inline
gtk_paper_size_new_custom() call - and every standard size comes back custom and
nameless, landscape ones with their dimensions still swapped.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.join(HERE, '..', '..', 'desktop-apps')
REL = 'win-linux/src/platform_linux/gtkprintdialog.cpp'
BASE_REF = os.environ.get('BASE_REF', 'HEAD')

QT = '/opt/homebrew/opt/qt@5'
PKG_CONFIG_PATH = ':'.join([
    '/opt/homebrew/opt/gtk+3/lib/pkgconfig',
    '/opt/homebrew/opt/libepoxy/lib/pkgconfig',
    '/opt/homebrew/lib/pkgconfig',
    '/opt/homebrew/share/pkgconfig',
    '/opt/homebrew/Library/Homebrew/os/mac/pkgconfig/15',
])

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


# The name lookup, unchanged by the fix and used by both sides.
at = source.find('auto gtkPaperNameFromPageSize(')
if at == -1:
    raise SystemExit('gtkPaperNameFromPageSize() is gone from %s' % REL)
name_lookup = brace_match(source, at)

# The construction: a real function after the fix, an inline block before it.
at = source.find('auto gtkPaperSizeFromPageSize(')
if at != -1:
    construction = brace_match(source, at)
    which = 'the gtkPaperSizeFromPageSize() helper'
else:
    MARKER = 'const QString paper_name = gtkPaperNameFromPageSize(page_size);'
    at = source.find(MARKER)
    if at == -1:
        raise SystemExit('neither the fixed helper nor the old inline construction is '
                         'in %s - the call site moved' % REL)
    end = source.index('unit);', at) + len('unit);')
    body = source[at:end]
    if 'gtk_paper_size_new_custom(' not in body:
        raise SystemExit('the old construction no longer calls gtk_paper_size_new_custom')
    # `ps` and `unit` are locals of exec(); stand them in so the block is the file's
    # own text. Neither stand-in carries any logic.
    construction = '''
struct FakePageSize {
    QString n;
    QString name() const { return n; }
};
auto gtkPaperSizeFromPageSize(const QSizeF &page_size, const QString &display_name)->GtkPaperSize*
{
    FakePageSize ps{display_name};
    GtkUnit unit = GTK_UNIT_MM;
    (void)ps; (void)unit;
%s
    return psize;
}
''' % body
    which = 'the pre-fix inline gtk_paper_size_new_custom() block'

print('extracted from %s: %s' % (REL, which))
sys.stdout.flush()

harness = r'''
#include <gtk/gtk.h>
#include <QSizeF>
#include <QString>
#include <stdio.h>

%(name_lookup)s

%(construction)s

static int failures = 0;

static void check(double w, double h, const char *display_name, const char *want_ppd,
                  double want_w, double want_h, const char *why)
{
    GtkPaperSize *psize = gtkPaperSizeFromPageSize(QSizeF(w, h), QString(display_name));
    const gboolean custom = gtk_paper_size_is_custom(psize);
    const char *ppd = gtk_paper_size_get_ppd_name(psize);
    const double got_w = gtk_paper_size_get_width(psize, GTK_UNIT_MM);
    const double got_h = gtk_paper_size_get_height(psize, GTK_UNIT_MM);

    bool ppd_ok = want_ppd ? (ppd && strcmp(ppd, want_ppd) == 0) : (ppd == NULL);
    bool custom_ok = (custom == (want_ppd ? FALSE : TRUE));
    bool size_ok = (got_w - want_w < 0.05 && want_w - got_w < 0.05 &&
                    got_h - want_h < 0.05 && want_h - got_h < 0.05);
    bool ok = ppd_ok && custom_ok && size_ok;

    printf("  %%-34s in %%6.1fx%%-6.1f -> media %%-9s custom=%%-3s %%6.1fx%%-6.1f  %%s\n",
           why, w, h, ppd ? ppd : "(none)", custom ? "yes" : "no", got_w, got_h,
           ok ? "ok" : "FAILED");
    if (!ok) failures++;
    gtk_paper_size_free(psize);
}

int main()
{
    printf("\nGTK %%d.%%d.%%d\n\n", gtk_get_major_version(), gtk_get_minor_version(),
           gtk_get_micro_version());

    /* A standard size has to reach CUPS by name, in portrait, whichever way round the
       caller hands it over - GtkPageSetup carries the orientation separately. */
    check(215.9, 279.4, "Letter", "Letter", 215.9, 279.4, "US Letter, portrait");
    check(279.4, 215.9, "Letter", "Letter", 215.9, 279.4, "US Letter, landscape");
    check(210.0, 297.0, "A4",     "A4",     210.0, 297.0, "A4, portrait");
    check(297.0, 210.0, "A4",     "A4",     210.0, 297.0, "A4, landscape");
    check(215.9, 355.6, "Legal",  "Legal",  215.9, 355.6, "US Legal, portrait");

    /* The editor sends the sheet size rounded up to whole millimetres, so Letter
       arrives as 216x280. That is still Letter to within the 1mm the lookup allows. */
    check(216.0, 280.0, "Letter", "Letter", 215.9, 279.4, "US Letter, rounded up");
    check(280.0, 216.0, "Letter", "Letter", 215.9, 279.4, "US Letter, rounded, landscape");

    /* Media that genuinely is not standard still has to go out as a custom size. */
    check(123.0, 456.0, "Custom (123mm x 456mm)", NULL, 123.0, 456.0, "a genuinely odd size");

    printf("\n%%s\n", failures
        ? "FAILED"
        : "ok - standard media keeps its CUPS name, in portrait, in both orientations");
    return failures ? 1 : 0;
}
''' % {'name_lookup': name_lookup, 'construction': construction}

with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'harness.cpp')
    exe = os.path.join(tmp, 'harness')
    open(src, 'w').write(harness)

    env = dict(os.environ, PKG_CONFIG_PATH=PKG_CONFIG_PATH)
    pkg = subprocess.run(['pkg-config', '--cflags', '--libs', 'gtk+-3.0'],
                         capture_output=True, text=True, env=env)
    if pkg.returncode != 0:
        sys.stderr.write(pkg.stdout + pkg.stderr)
        raise SystemExit('gtk+-3.0 not found via pkg-config')

    cmd = (['clang++', '-std=c++14', '-Wall', '-DQT_NO_KEYWORDS', '-o', exe, src]
           + pkg.stdout.split()
           + ['-I' + QT + '/lib/QtCore.framework/Headers', '-F' + QT + '/lib',
              '-framework', 'QtCore'])
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)

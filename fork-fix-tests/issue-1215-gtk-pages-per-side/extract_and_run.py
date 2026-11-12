#!/usr/bin/env python3
"""
#1215 (pages per sheet, Linux) - the GTK print dialog's "Pages per side" did nothing.

"Print using the system dialog" on Linux opens GtkPrintDialog (desktop-apps
win-linux/src/platform_linux/gtkprintdialog.cpp). For a CUPS printer GTK shows "Pages
per side" and "Page ordering" on its Page Setup tab without the app asking (the CUPS
print backend reports NUMBER_UP / NUMBER_UP_LAYOUT itself). But the job is printed by
Qt's CUPS engine from our QPrinter, and the dialog's OK branch read back colour, range,
page set, collate, duplex, reverse, copies and output URI - never number-up. So a user
who chose 2 or 4 pages per side got one page per sheet.

Fix: applyNumberUp(QPrinter*, GtkPrintSettings*) - called in the OK branch - hands
gtk_print_settings_get_number_up / _layout to Qt's CUPS engine as the job options
number-up / number-up-layout (PPK_CupsOptions, 0xfe00), which QCupsPrintEngine adds to
the job; 1 page per side adds nothing.

What this runs (Docker image rd-linux-verify:24.04: Qt 5.15, GTK 3.24, CUPS installed in
the throwaway container): the REAL applyNumberUp, extracted by brace matching, on a REAL
GtkPrintSettings set the way the dialog leaves it (gtk_print_settings_set_number_up /
_layout), and a REAL QPrinter on a CUPS queue whose backend captures the job; 4 pages are
drawn (a page number's worth of black bars each) and the job is printed. Checked per
case: the job's options (argv[5]) and the number of sheets in the filtered PostScript
(%%Page: count): 1 per side -> 4 sheets, no number-up; 2 -> 2 sheets with
number-up=2 number-up-layout=lrtb; 4 with top-to-bottom layout -> 1 sheet, number-up=4 number-up-layout=tblr.
It also checks the OK branch calls applyNumberUp with the dialog's settings.

BASELINE=1 reads gtkprintdialog.cpp from BASE_REF: there is no applyNumberUp and nothing
reads number-up, so the job gets no option and prints 4 sheets -> FAIL.

NOT claimed: the GTK dialog widgets themselves (that GTK shows "Pages per side" for a
CUPS queue is from GTK's cups backend source, not driven here); a real printer;
"Print to File" (PDF output ignores CUPS options - unchanged); Windows/macOS.

  RD_REPO     desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1  gtkprintdialog.cpp from BASE_REF (default: parent of the fix commit)
  RD_IMAGE    Docker image (default rd-linux-verify:24.04)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
BASE_REF = os.environ.get('BASE_REF', '04a0d87d2^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')
REL = 'win-linux/src/platform_linux/gtkprintdialog.cpp'

if BASELINE:
    src = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(REPO, REL), encoding='utf-8').read()


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


at = src.find('static void applyNumberUp(QPrinter *printer, GtkPrintSettings *settings)')
helper = brace_match(src, at) if at != -1 else ''
define = '#define PPK_CupsOptions QPrintEngine::PrintEnginePropertyKey(0xfe00)' if helper else ''
called = 'applyNumberUp(m_printer, settings);' in src[src.find('case GTK_RESPONSE_OK'):]

SRC = r'''
#include <QApplication>
#include <QPrinter>
#include <QPrinterInfo>
#include <QPrintEngine>
#include <QPainter>
#include <QStringList>
#include <gtk/gtk.h>
#include <gtk/gtkunixprint.h>
#include <cstdlib>
DEFINE
HELPER
int main(int argc, char **argv) {
	QApplication app(argc, argv);
	int n = atoi(argv[2]);
	GtkPrintSettings *settings = gtk_print_settings_new();
	gtk_print_settings_set_number_up(settings, n);
	gtk_print_settings_set_number_up_layout(settings, (GtkNumberUpLayout)atoi(argv[3]));
	QPrinter printer(QPrinterInfo::printerInfo(argv[1]), QPrinter::HighResolution);
	printer.setPageSize(QPageSize(QPageSize::A4));
	printer.setFullPage(true);
#if HAS_NUMBER_UP_HELPER
	applyNumberUp(&printer, settings);
#endif
	QPainter p(&printer);
	QRect r = p.viewport();
	for (int page = 1; page <= 4; ++page) {
		if (page > 1) printer.newPage();
		for (int b = 0; b < page; ++b)
			p.fillRect(QRect(r.width() / 10, r.height() / 10 + b * r.height() / 8, r.width() * 8 / 10, r.height() / 16), Qt::black);
	}
	p.end();
	g_object_unref(settings);
	return 0;
}
'''.replace('HAS_NUMBER_UP_HELPER', '1' if helper else '0').replace('DEFINE', define).replace('HELPER', helper)

BACKEND = r'''#!/bin/sh
if [ $# -eq 0 ]; then echo 'direct capture "Unknown" "capture"'; exit 0; fi
echo "$@" > /tmp/out/job-$1.args
if [ -n "$6" ]; then cat "$6" > /tmp/out/job-$1.data; else cat > /tmp/out/job-$1.data; fi
'''
RUN = r'''#!/bin/sh
set -e
export DEBIAN_FRONTEND=noninteractive QT_QPA_PLATFORM=offscreen
if ! command -v cupsd >/dev/null || ! command -v gs >/dev/null; then
  apt-get update -qq >/dev/null; apt-get install -y -qq cups cups-filters ghostscript >/dev/null 2>&1
fi
mkdir -p /tmp/out; chmod 777 /tmp/out; rm -f /tmp/out/*
cp /t/capture /usr/lib/cups/backend/capture; chmod 755 /usr/lib/cups/backend/capture
pgrep cupsd >/dev/null || cupsd; sleep 2
lpadmin -p rd1215 -E -v capture:/x -m drv:///sample.drv/generic.ppd -o PageSize=A4 2>/dev/null
cd /t && g++ -std=gnu++17 -fPIC -w -DQT_NO_KEYWORDS t.cpp -o t $(pkg-config --cflags --libs Qt5Widgets Qt5PrintSupport gtk+-unix-print-3.0)
n=0
for c in "1 0" "2 0" "4 4"; do
  ./t rd1215 $c 2>/dev/null; n=$((n+1))
  i=0; while [ $(ls /tmp/out/*.data 2>/dev/null | wc -l) -lt $n ]; do sleep 1; i=$((i+1)); [ $i -lt 60 ] || exit 1; done
  f=$(ls -t /tmp/out/*.data | head -1); echo "$c" > ${f%.data}.case
done
cp /tmp/out/* /t/out/
'''


def main():
    work = os.environ.get('RD_WORK') or tempfile.mkdtemp(prefix='rd1215-')
    os.makedirs(os.path.join(work, 'out'), exist_ok=True)
    open(os.path.join(work, 't.cpp'), 'w').write(SRC)
    open(os.path.join(work, 'capture'), 'w').write(BACKEND)
    open(os.path.join(work, 'run.sh'), 'w').write(RUN)
    subprocess.run(['docker', 'run', '--rm', '-v', '%s:/t' % work, IMAGE, 'sh', '/t/run.sh'], check=True)
    out = os.path.join(work, 'out')
    want = {'1 0': (4, None), '2 0': (2, 'number-up=2 number-up-layout=lrtb'), '4 4': (1, 'number-up=4 number-up-layout=tblr')}
    failures = 0
    print('#1215 GTK "Pages per side" -> CUPS job (%s):' % ('BASELINE ' + BASE_REF if BASELINE else 'working tree'))
    print('  helper applyNumberUp: %s; called in the dialog\'s OK branch: %s' % ('found' if helper else 'MISSING', called))
    if not called:
        failures += 1
    for c in sorted(f for f in os.listdir(out) if f.endswith('.case')):
        base = os.path.join(out, c[:-5])
        case = open(base + '.case').read().strip()
        args = open(base + '.args').read().split()
        # sheets in the filtered PostScript the printer would get (after cups-filters' number-up)
        sheets = open(base + '.data', 'rb').read().count(b'\n%%Page:')
        opts = [a for a in args if a.startswith('number-up')]
        w_sheets, w_opts = want[case]
        ok = sheets == w_sheets and (opts == (w_opts.split() if w_opts else []))
        failures += not ok
        print('  pages per side %s, layout %s: job options %-38s sheets %d  %s' % (
            case.split()[0], case.split()[1], ' '.join(opts) or '(none)', sheets,
            'ok' if ok else 'FAILED, want %d sheets / %s' % (w_sheets, w_opts or 'no option')))
    if not os.environ.get('RD_WORK'):
        shutil.rmtree(work, ignore_errors=True)
    print('FAIL' if failures else 'PASS #1215: pages per side chosen in the GTK dialog reach CUPS; 1 per side is unchanged')
    sys.exit(1 if failures else 0)


main()

#!/usr/bin/env python3
"""
#1468 - on Linux, with the desktop scaled to 125/150/175% (GNOME fractional scaling,
KDE Plasma's scale factor, Xfce's DPI), the editors' "Interface scaling: auto" came out
at 100% (or at 200% on a 4K monitor) instead of the system scale.

Cause: the app does its own scaling (main.cpp sets Qt::AA_DisableHighDpiScaling; CEF
gets --force-device-scale-factor=1 and is zoomed by the app). On Linux "auto" comes from
QDpiChecker::GetMonitorDpi (desktop-sdk qt_wrapper): max(physical DPI, QX11Info::appDpiX
- Qt's logical DPI, i.e. Xft.dpi), then screen-size guesses: any screen <= 1600x900 is
96 dpi, a 4K screen at 150-180 dpi is 192. So the desktop's scale only counted when it
was larger than the monitor's physical DPI and no guess fired: a 4K monitor at 125-175%
came out at 200%, a 1600x900 screen at 100% whatever was set, and a dense laptop panel
(14" 1080p, 157 dpi) at 175% whether the desktop said 125 or 150%.

Fix: GetMonitorDpi reads Xft.dpi from the root window's RESOURCE_MANAGER; when the desktop
sets anything but the default 96 it takes that as the DPI, skipping the max and the
guesses (divided by Qt's own QT_SCALE_FACTOR, which Qt applies by itself, so a user who
exports it is not scaled twice). At 96 or without Xft.dpi the old guess applies unchanged; a scale chosen in the
app's settings (force-scale) still short-circuits before any of this (GetForceScale).

What this runs (real source, not copies):
  desktop-sdk  qt_wrapper/src/qdpichecker.cpp       compiled WHOLE, with the real
                                                     include/qdpichecker.h;
               src/applicationmanager.cpp            Core_GetMonitorScale (brace-matched),
                                                     which is CAscDpiChecker::GetScale;
  desktop-apps win-linux/src/utils.cpp               choose_scaling (brace-matched), the
                                                     last step of Utils::getScreenDpiRatio*;
               win-linux/src/main.cpp                checked to still set AA_Use96Dpi and
                                                     AA_DisableHighDpiScaling, which the
                                                     harness sets the same way.
The checked value is the effective UI scale: the checker's scale times Qt's own
devicePixelRatio (1 unless QT_SCALE_FACTOR is exported, which Qt 5.15 applies by itself
even with AA_DisableHighDpiScaling).
CAscDpiChecker (applicationmanager.h) is stubbed to its Linux behaviour (base DPI
functions return -1; GetForceScale returns the "force-scale" user setting or -1).
Each scenario runs a fresh Xvfb of the given size and physical DPI, loads the given X
resources with xrdb (what gnome-settings-daemon / startplasma / xfsettingsd do), sets
the given environment, shows a QWidget and asks QDpiChecker::GetWidgetDpi for it - the
path Utils::getScreenDpiRatioByWidget takes - then GetScale and choose_scaling.

Scenarios (expected = what the desktop is set to):
  Xft.dpi 120/144/168/192 on 1920x1080        -> 1.25 / 1.5 / 1.75 / 2 (right before too)
  Xft.dpi 120 on 1600x900                      -> 1.25 (baseline: the <=1600x900 guess, 1)
  Xft.dpi 120 and 168 on a 27" 4K (163 dpi)    -> 1.25 / 1.75 (baseline: the 4K guess, 2)
  Xft.dpi 120 on a 14" 1080p (157 dpi)         -> 1.25 (baseline: physical wins, 1.75)
  KDE Plasma ScaleFactor=1.5 (startplasma: Xft.dpi 144 + QT_SCREEN_SCALE_FACTORS) -> 1.5
  GDK_SCALE=2 GDK_DPI_SCALE=0.75 with Xft.dpi 144 (GNOME X11 at 2x with 0.75 text) -> 1.5
  QT_SCALE_FACTOR=1.5 with Xft.dpi 144 / with Xft.dpi 96 (a common workaround) -> 1.5
  unchanged guards: no Xft.dpi on 1920x1080/96 -> 1; Xft.dpi 96 on a 14" 1080p (157 dpi)
  -> 1.75 (the physical guess, as before); no Xft.dpi on a 27" 4K -> 2;
  force-scale 1 with Xft.dpi 168 -> 1; force-scale 2 with Xft.dpi 120 -> 2.

NOT claimed: GDK_SCALE / GDK_DPI_SCALE are GTK's knobs and are not read; a desktop that sets
none of the X resources (bare Wayland compositors without XWayland scaling support)
still gets the physical guess; on GNOME Wayland what Xwayland reports depends on
mutter's xwayland-native-scaling. Per-monitor scales cannot be expressed through Xft.dpi
(one value for the X display). The real app on a real desktop is a GUI check.
macOS is not affected (it uses system scaling, CSystemWindowScale), nor Windows (it
reads the per-monitor DPI from the OS, not this file).

Runs in Docker image rd-linux-verify:24.04 (Ubuntu 24.04, Qt 5.15; RD_IMAGE to change),
installing make, xvfb, x11-xserver-utils and libqt5x11extras5-dev in the throwaway container
if missing. RD_NO_DOCKER=1 runs here (needs those plus qtbase5-dev).
  RD_REPO       desktop-sdk checkout (default ../../desktop-sdk)
  RD_APPS_REPO  desktop-apps checkout (default ../../desktop-apps)
  BASELINE=1    qdpichecker.cpp from BASE_REF (default: parent of the fix commit) -> FAIL
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
APPS = os.environ.get('RD_APPS_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '7ec92990^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')

QDC = 'ChromiumBasedEditors/lib/qt_wrapper/src/qdpichecker.cpp'
QDH = 'ChromiumBasedEditors/lib/qt_wrapper/include/qdpichecker.h'
AMC = 'ChromiumBasedEditors/lib/src/applicationmanager.cpp'
UTILS = 'win-linux/src/utils.cpp'
MAIN = 'win-linux/src/main.cpp'


def read(repo, rel, from_git=False):
    if from_git:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


def extract(text, anchor, needles=()):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit('%r not found - the extractor needs updating' % anchor)
    ob = text.index('{', at)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                body = text[at:i + 1]
                for n in needles:
                    if n not in body:
                        raise SystemExit('extracted %r is missing %r - wrong block?' % (anchor, n))
                return body
    raise SystemExit('unbalanced braces after %r' % anchor)


qdc = read(REPO, QDC, BASELINE)
qdh = read(REPO, QDH)
monitor_scale = extract(read(REPO, AMC), 'double Core_GetMonitorScale(', ('0.25',))
choose = extract(read(APPS, UTILS), 'inline double choose_scaling(double s)', ('1.25',))
main_cpp = read(APPS, MAIN)
for needle in ('Qt::AA_Use96Dpi', 'Qt::AA_DisableHighDpiScaling'):
    if needle not in main_cpp:
        raise SystemExit('main.cpp no longer sets %s - the harness set-up needs updating' % needle)
for needle in ('int QDpiChecker::GetMonitorDpi(', 'int QDpiChecker::GetWidgetDpi('):
    if needle not in qdc:
        raise SystemExit('qdpichecker.cpp has no %r - the harness needs updating' % needle)

# The CAscDpiChecker part of applicationmanager.h, as it behaves on Linux.
STUB_AM = r'''
#pragma once
#include <cstdlib>
#define DESKTOP_DECL
typedef void* WindowHandleId;
class CCefViewWidgetImpl {};
class CAscApplicationManager {};
MONITOR_SCALE_DECL
class CAscDpiChecker
{
public:
	CAscDpiChecker(CAscApplicationManager*) {}
	virtual ~CAscDpiChecker() {}
	virtual int GetWindowDpi(WindowHandleId, unsigned int*, unsigned int*) { return -1; }
	virtual int GetMonitorDpi(int, unsigned int*, unsigned int*) { return -1; }
	virtual int GetWidgetImplDpi(CCefViewWidgetImpl*, unsigned int*, unsigned int*) { return -1; }
	virtual double GetScale(unsigned int x, unsigned int y) { return Core_GetMonitorScale(x, y); }
	// the "force-scale" user setting (Interface scaling other than auto)
	double GetForceScale(unsigned int* dpix, unsigned int* dpiy)
	{
		const char* s = getenv("RD_FORCE_SCALE");
		if (!s || !*s)
			return -1;
		double d = atof(s);
		if (dpix) *dpix = (unsigned int)(d * 96);
		if (dpiy) *dpiy = (unsigned int)(d * 96);
		return d;
	}
};
'''.replace('MONITOR_SCALE_DECL', 'double Core_GetMonitorScale(const unsigned int& xDpi, const unsigned int& yDpi);')

STUB_CEFVIEW = r'''
#pragma once
#include <QWidget>
class QCefView : public QWidget {};
'''

MAIN_SRC = r'''
#include <QApplication>
#include <QWidget>
#include <QScreen>
#include <QX11Info>
#include <cstdio>
#include "include/qdpichecker.h"

MONITOR_SCALE
CHOOSE

int main(int argc, char** argv)
{
	// as win-linux/src/main.cpp
	QCoreApplication::setAttribute(Qt::AA_DisableHighDpiScaling);
	QCoreApplication::setAttribute(Qt::AA_Use96Dpi);
	QApplication app(argc, argv);
	QWidget w;
	w.resize(200, 100);
	w.show();
	app.processEvents();

	QDpiChecker checker(nullptr);
	unsigned int dx = 0, dy = 0;
	checker.GetWidgetDpi(&w, &dx, &dy);
	double scale = choose_scaling(checker.GetScale(dx, dy));
	printf("dpi=%u scale=%g qt_dpr=%g (qt_logical_dpi=%d)\n", dx, scale, w.devicePixelRatioF(), QX11Info::appDpiX(0));
	return 0;
}
'''.replace('MONITOR_SCALE', monitor_scale).replace('CHOOSE', choose)

PRO = r'''
QT += widgets x11extras
CONFIG += c++11
TARGET = dpi
DEFINES += _LINUX
INCLUDEPATH += .
SOURCES += main.cpp src/qdpichecker.cpp
LIBS += -lX11
'''

# name, screen WxH, physical dpi given to Xvfb, X resources, env, expected scale
SCENARIOS = [
    ('GNOME 125% (Xft.dpi 120), 1920x1080',   '1920x1080', 96,  'Xft.dpi: 120', '', 1.25),
    ('GNOME 150% (Xft.dpi 144), 1920x1080',   '1920x1080', 96,  'Xft.dpi: 144', '', 1.5),
    ('GNOME 175% (Xft.dpi 168), 1920x1080',   '1920x1080', 96,  'Xft.dpi: 168', '', 1.75),
    ('GNOME 200% (Xft.dpi 192), 1920x1080',   '1920x1080', 96,  'Xft.dpi: 192', '', 2),
    ('Xft.dpi 120 on 1600x900',               '1600x900',  96,  'Xft.dpi: 120', '', 1.25),
    ('Xft.dpi 120 on 27in 4K (163 dpi)',      '3840x2160', 163, 'Xft.dpi: 120', '', 1.25),
    ('Xft.dpi 168 on 27in 4K (163 dpi)',      '3840x2160', 163, 'Xft.dpi: 168', '', 1.75),
    ('KDE ScaleFactor=1.5 (startplasma)',     '1920x1080', 96,  'Xft.dpi: 144', 'QT_SCREEN_SCALE_FACTORS=1.5', 1.5),
    ('GDK_SCALE=2 GDK_DPI_SCALE=0.75, Xft 144', '1920x1080', 96, 'Xft.dpi: 144', 'GDK_SCALE=2 GDK_DPI_SCALE=0.75', 1.5),
    ('QT_SCALE_FACTOR=1.5, Xft.dpi 144',      '1920x1080', 96,  'Xft.dpi: 144', 'QT_SCALE_FACTOR=1.5', 1.5),
    ('QT_SCALE_FACTOR=1.5, Xft.dpi 96',       '1920x1080', 96,  'Xft.dpi: 96', 'QT_SCALE_FACTOR=1.5', 1.5),
    ('Xft.dpi 120 on 14in 1080p (157 dpi)',   '1920x1080', 157, 'Xft.dpi: 120', '', 1.25),
    ('unchanged: no Xft.dpi, 1920x1080 96dpi', '1920x1080', 96, '', '', 1),
    ('unchanged: Xft.dpi 96, 14in 1080p (157 dpi)', '1920x1080', 157, 'Xft.dpi: 96', '', 1.75),
    ('unchanged: no Xft.dpi, 27in 4K',        '3840x2160', 163, '', '', 2),
    ('explicit 100% beats Xft.dpi 168',       '1920x1080', 96,  'Xft.dpi: 168', 'RD_FORCE_SCALE=1', 1),
    ('explicit 200% beats Xft.dpi 120',       '1920x1080', 96,  'Xft.dpi: 120', 'RD_FORCE_SCALE=2', 2),
]

RUN_SH = r'''set -e
if ! command -v make >/dev/null || ! command -v Xvfb >/dev/null || ! command -v xrdb >/dev/null || [ ! -e /usr/include/$(gcc -dumpmachine)/qt5/QtX11Extras ]; then
  apt-get update -qq >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    make xvfb x11-xserver-utils libqt5x11extras5-dev >/dev/null
fi
cd "$1"
qmake -qt=5 dpi.pro >/dev/null 2>&1 || qmake dpi.pro >/dev/null
make -s -j4 >build.log 2>&1 || { cat build.log; exit 1; }
n=0
while IFS='|' read -r size pdpi res envs; do
  n=$((n+1)); d=$((90+n))
  Xvfb :$d -screen 0 ${size}x24 -dpi $pdpi -nolisten tcp -noreset >/dev/null 2>&1 &
  xp=$!
  for i in $(seq 50); do [ -e /tmp/.X11-unix/X$d ] && break; sleep 0.1; done
  if [ -n "$res" ]; then printf '%s\n' "$res" | DISPLAY=:$d xrdb -nocpp -merge; fi
  env -u QT_SCALE_FACTOR DISPLAY=:$d QT_QPA_PLATFORM=xcb $envs ./dpi 2>/dev/null || echo "dpi=? scale=? (crashed)"
  kill $xp; wait $xp 2>/dev/null || true
done < scenarios.txt
'''


def main():
    work = tempfile.mkdtemp(prefix='rd1468-')
    try:
        os.makedirs(os.path.join(work, 'include'))
        os.makedirs(os.path.join(work, 'src'))
        open(os.path.join(work, 'include', 'qdpichecker.h'), 'w').write(qdh)
        open(os.path.join(work, 'include', 'applicationmanager.h'), 'w').write(STUB_AM)
        open(os.path.join(work, 'include', 'qcefview.h'), 'w').write(STUB_CEFVIEW)
        open(os.path.join(work, 'src', 'qdpichecker.cpp'), 'w').write(qdc)
        open(os.path.join(work, 'main.cpp'), 'w').write(MAIN_SRC)
        open(os.path.join(work, 'dpi.pro'), 'w').write(PRO)
        open(os.path.join(work, 'run.sh'), 'w').write(RUN_SH)
        with open(os.path.join(work, 'scenarios.txt'), 'w') as f:
            for _, size, pdpi, res, envs, _ in SCENARIOS:
                f.write('%s|%d|%s|%s\n' % (size, pdpi, res, envs))
        if os.environ.get('RD_NO_DOCKER'):
            out = subprocess.run(['sh', os.path.join(work, 'run.sh'), work],
                                 capture_output=True, text=True)
        else:
            out = subprocess.run(['docker', 'run', '--rm', '-v', '%s:/t' % work, IMAGE,
                                  'sh', '/t/run.sh', '/t'], capture_output=True, text=True)
        if out.returncode != 0:
            sys.stderr.write(out.stdout + out.stderr)
            raise SystemExit('harness failed to build/run')
        lines = [l for l in out.stdout.splitlines() if l.startswith('dpi=')]
        if len(lines) != len(SCENARIOS):
            sys.stderr.write(out.stdout + out.stderr)
            raise SystemExit('expected %d results, got %d' % (len(SCENARIOS), len(lines)))
        bad = 0
        for (name, _, _, _, _, want), line in zip(SCENARIOS, lines):
            got = line.split('scale=')[1].split()[0]
            dpr = line.split('qt_dpr=')[1].split()[0] if 'qt_dpr=' in line else '?'
            ok = '?' not in (got, dpr) and abs(float(got) * float(dpr) - want) < 1e-9
            bad += not ok
            print('%s  %-46s want %-5g %s' % ('ok  ' if ok else 'FAIL', name, want, line))
        label = 'BASELINE (%s)' % BASE_REF if BASELINE else 'fix'
        if bad:
            print('FAIL [%s]: %d of %d scenarios scale wrong' % (label, bad, len(SCENARIOS)))
            sys.exit(1)
        print('PASS [%s]: all %d scenarios get the desktop scale' % (label, len(SCENARIOS)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()

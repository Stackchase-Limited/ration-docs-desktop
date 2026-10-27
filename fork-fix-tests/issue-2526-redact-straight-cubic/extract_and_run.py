#!/usr/bin/env python3
"""
#2526 - "PDF Editor - Redaction function does not delete all content layers".

Three defects in core/PdfFile/SrcWriter/RedactOutputDev.cpp let content survive
under a redaction. This test covers the one that is pure geometry:

DoPathRedact subtracts the redaction areas from every filled path with
Aggplus::CalcBooleanOperation. Producers write straight edges as cubics whose
control points lie on the chord (Quartz does for rounded rectangles), and the
boolean operation misses where such an edge crosses the redaction: it returns the
shape unchanged. The reporter's keyboard frame - a filled rounded rectangle -
stayed whole under the redaction.

The test lifts the real IsStraightCubic() out of the source, builds that frame
(coordinates from the reporter's PDF) the way DoPathRedact now does, subtracts
the redaction band with the real graphics library, and checks a point inside the
band is gone while one outside remains. It also shows the unfixed behaviour:
with every edge kept as a cubic the point inside the band survives.

Needs core built (core/build/lib/<platform>/graphics.framework).
"""
import os, re, subprocess, sys, tempfile, platform

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '../../core'))
src = open(os.path.join(CORE, 'PdfFile/SrcWriter/RedactOutputDev.cpp')).read()
m = re.search(r'static bool IsStraightCubic\(.*?\n}\n', src, re.S)
if not m:
    print('FAIL: IsStraightCubic not found in RedactOutputDev.cpp'); sys.exit(1)
helper = m.group(0)

prog = r'''
#include "DesktopEditor/graphics/GraphicsPath.h"
#include <cstdio>
using namespace Aggplus;
HELPER
struct Seg { bool curve; double x1, y1, x2, y2, x3, y3; };
static const double X0 = 632.442, Y0 = 328.578;
static const Seg FRAME[] = {
  {1, 632.442,330.082, 631.844,331.524, 630.781,332.587}, {1, 629.718,333.65, 628.276,334.248, 626.772,334.248},
  {1, 569.379,334.248, 94.3566,334.248, 36.9626,334.248}, {1, 35.459,334.248, 34.017,333.65, 32.9538,332.587},
  {1, 31.8906,331.524, 31.2933,330.082, 31.2933,328.578}, {1, 31.2933,293.989, 31.2933,111.708, 31.2933,77.1179},
  {1, 31.2933,75.6143, 31.8906,74.1723, 32.9538,73.1091}, {1, 34.017,72.0459, 35.459,71.4486, 36.9626,71.4486},
  {0, 626.772,71.4486, 0,0, 0,0}, {1, 628.276,71.4486, 629.718,72.0459, 630.781,73.1091},
  {1, 631.844,74.1723, 632.442,75.6143, 632.442,77.1179}, {1, 632.442,111.708, 632.442,293.989, 632.442,328.578}};
static CGraphicsPath frame(bool bUseHelper, int& nStraight) {
  CGraphicsPath p; p.StartFigure(); p.MoveTo(X0, Y0); double cx = X0, cy = Y0; nStraight = 0;
  for (const Seg& s : FRAME) {
    if (!s.curve) { p.LineTo(s.x1, s.y1); cx = s.x1; cy = s.y1; continue; }
    if (bUseHelper && IsStraightCubic(cx, cy, s.x1, s.y1, s.x2, s.y2, s.x3, s.y3)) { p.LineTo(s.x3, s.y3); ++nStraight; }
    else p.CurveTo(s.x1, s.y1, s.x2, s.y2, s.x3, s.y3);
    cx = s.x3; cy = s.y3;
  }
  p.CloseFigure(); return p;
}
int main() {
  CGraphicsPath band; band.StartFigure();
  band.MoveTo(90, 353.937); band.LineTo(620, 353.937); band.LineTo(620, 213.937); band.LineTo(90, 213.937); band.CloseFigure();
  int bad = 0, n = 0;
  CGraphicsPath before = CalcBooleanOperation(frame(false, n), band, BooleanOpType::Subtraction);
  printf("as cubics (unfixed): point in band kept=%d\n", (int)before.IsPointInPath(300, 280));
  CGraphicsPath after = CalcBooleanOperation(frame(true, n), band, BooleanOpType::Subtraction);
  bool inBand = after.IsPointInPath(300, 280), outside = after.IsPointInPath(300, 150), corner = after.IsPointInPath(33, 73);
  printf("straight cubics found: %d (expect 3, the rounded corners stay curves)\n", n);
  printf("fixed: point in band kept=%d, point outside band kept=%d, rounded corner kept=%d\n", (int)inBand, (int)outside, (int)corner);
  bad += (n != 3) + inBand + !outside;
  return bad ? 1 : 0;
}
'''.replace('HELPER', helper)

plat = 'mac_arm64' if platform.system() == 'Darwin' and platform.machine() == 'arm64' else None
libdir = os.path.join(CORE, 'build/lib', plat or 'linux_64')
with tempfile.TemporaryDirectory() as t:
    c, exe = os.path.join(t, 't.cpp'), os.path.join(t, 't')
    open(c, 'w').write(prog)
    if platform.system() == 'Darwin':
        link = ['-F' + libdir, '-framework', 'graphics', '-framework', 'kernel', '-framework', 'UnicodeConverter']
    else:
        link = ['-L' + libdir, '-lgraphics', '-lkernel', '-lUnicodeConverter']
    r = subprocess.run(['c++', '-std=c++11', '-w', '-I' + CORE, '-DLINUX', '-D_LINUX'] + (['-DMAC', '-D_MAC'] if plat else [])
                       + [c, '-o', exe, '-Wl,-rpath,' + libdir] + link, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:]); print('FAIL: does not build'); sys.exit(1)
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout, end='')
    print('PASS' if r.returncode == 0 else 'FAIL'); sys.exit(r.returncode)

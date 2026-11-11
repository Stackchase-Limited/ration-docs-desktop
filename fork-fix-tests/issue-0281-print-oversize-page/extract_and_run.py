#!/usr/bin/env python3
"""
#281 - "Bottom of page not printed if I use custom page (210x330mm)". A page bigger than the
sheet the printer uses (F4/Folio on A4 or Letter, A3 on A4, a custom size the driver does
not offer) lost everything past the sheet's edge - for a tall page, its bottom.

CPrintData::CheckPrintRotate (desktop-sdk fileprinter.cpp) in mode pm100 - every document
and presentation print, and spreadsheets without fit-to-page - kept a page that fits the
sheet neither way round at 100%: unturned at (0,0) or turned, and the overflow was clipped.
The fix fits it to the sheet with FitToPage, turned the way that keeps it larger, as the
pmFit branch of the same function does.

What runs here is the source, lifted by brace matching: CPrintData::FitToPage and
CPrintData::CheckPrintRotate from fileprinter.cpp, CPrintContextPageData from fileprinter.h,
CAscPrintSettings from applicationmanager.h (its defaults: pm100, RotateEnable). The printer
context is a stub reporting a 300 dpi sheet with no margins. Each case checks that the placed
page lies inside the sheet; the cases where the page fits are there to show those still print
at 100% (within a pixel).

NOT claimed: the platform drawing (Qt / CoreGraphics) or a real printer - the GUI print needs
a manual check. BASELINE=1 reads the sources at BASE_REF (parent of the fix): F4 on A4 goes
out 3898 px high on a 3508 px sheet - FAILED.
RD_REPO overrides the desktop-sdk checkout (default ../../desktop-sdk from this file).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk'))
# Pinned to the parent of the commit that landed this fix. It must NOT default to HEAD.
BASE_REF = os.environ.get('BASE_REF', 'c8d2135d^')
LIB = 'ChromiumBasedEditors/lib'


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s/%s' % (BASE_REF, LIB, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, LIB, rel), encoding='utf-8').read()


def brace_match(src, at, what):
    depth = 0
    for i in range(src.index('{', at), len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces extracting %s' % what)


def lift(src, needle, what):
    at = src.find(needle)
    if at == -1:
        raise SystemExit('%s is gone (looked for %r)' % (what, needle))
    return brace_match(src, at, what)


fileprinter = read('src/fileprinter.cpp')
fit = lift(fileprinter, 'void CPrintData::FitToPage(', 'FitToPage')
check = lift(fileprinter, 'CPrintData::CPrintContextPageData CPrintData::CheckPrintRotate(', 'CheckPrintRotate')
page_data = lift(read('src/fileprinter.h'), 'class CPrintContextPageData', 'CPrintContextPageData') + ';'
settings = lift(read('include/applicationmanager.h'), 'class CAscPrintSettings', 'CAscPrintSettings') + ';'
editor_type_enum = lift(read('include/cefview.h'), 'enum class AscEditorType', 'AscEditorType') + ';'

harness = r'''
#include <cmath>
#include <cstdio>
#include <vector>
namespace agg { const double pi = 3.14159265358979323846; }
%(editor_type_enum)s
%(settings)s
namespace NSEditorApi {
	struct CAscPrinterContextBase {
		virtual void GetLogicalDPI(int& x, int& y) = 0;
		virtual void GetPhysicalRect(int& x, int& y, int& w, int& h) = 0;
		virtual void GetPrintAreaSize(int& w, int& h) = 0;
	};
}
class CPagePrintData { public: double Width = 0, Height = 0; };
class CPrintData {
public:
	std::vector<CPagePrintData> m_arPages;
	AscEditorType m_eEditorType = AscEditorType::etDocument;
	%(page_data)s
	static void FitToPage(float, float, float, float, float&, float&, float&, float&);
	CPrintContextPageData CheckPrintRotate(NSEditorApi::CAscPrinterContextBase*, const CAscPrintSettings&, const int&);
};
struct Sheet : NSEditorApi::CAscPrinterContextBase {
	int dpi, w, h;
	Sheet(int d, int ww, int hh) : dpi(d), w(ww), h(hh) {}
	void GetLogicalDPI(int& x, int& y) override { x = y = dpi; }
	void GetPhysicalRect(int& x, int& y, int& ww, int& hh) override { x = 0; y = 0; ww = w; hh = h; }
	void GetPrintAreaSize(int& ww, int& hh) override { ww = w; hh = h; }
};

%(fit)s
%(check)s

static int failures = 0;
/* sheet in px at 300 dpi; page in mm; expect100: the page fits and must stay at 100%% */
static void run(const char* what, double pageW, double pageH, Sheet sheet, bool expect100)
{
	CPrintData data;
	CPagePrintData page; page.Width = pageW; page.Height = pageH;
	data.m_arPages.push_back(page);
	CAscPrintSettings settings;               /* the app's defaults: pm100, RotateEnable */
	CPrintData::CPrintContextPageData r = data.CheckPrintRotate(&sheet, settings, 0);
	bool rotated = std::fabs(r.Angle) > 1e-6;
	bool inside;
	if (rotated)   /* turned 90 degrees about the centre of the placed rectangle */
		inside = r.WidthPix <= sheet.h + 1.0 && r.HeightPix <= sheet.w + 1.0 &&
		         std::fabs(r.LeftPix + r.WidthPix / 2 - sheet.w / 2.0) < 1.0 &&
		         std::fabs(r.TopPix + r.HeightPix / 2 - sheet.h / 2.0) < 1.0;
	else
		inside = r.LeftPix >= -1.0 && r.TopPix >= -1.0 &&
		         r.LeftPix + r.WidthPix <= sheet.w + 1.0 && r.TopPix + r.HeightPix <= sheet.h + 1.0;
	double full = sheet.dpi * pageW / 25.4;
	bool at100 = std::fabs(r.WidthPix - full) <= 1.0;
	bool ok = inside && (!expect100 || at100);
	printf("  %%-34s %%7.1f x %%-7.1f px at (%%7.1f, %%7.1f)%%s on a %%dx%%d sheet  %%s\n", what, r.WidthPix, r.HeightPix,
	       r.LeftPix, r.TopPix, rotated ? " turned" : "       ", sheet.w, sheet.h,
	       ok ? "ok" : (!inside ? "FAILED - runs off the sheet" : "FAILED - no longer printed at 100%%"));
	if (!ok) failures++;
}

int main()
{
	Sheet A4(300, 2480, 3508), Letter(300, 2550, 3300), A4land(300, 3508, 2480);
	printf("\n");
	run("F4 210x330 on A4 (report)", 210, 330, A4, false);
	run("F4 210x330 on Letter", 210, 330, Letter, false);
	run("A3 on A4", 297, 420, A4, false);
	run("Legal on Letter", 215.9, 355.6, Letter, false);
	run("A4 on A4 (fits)", 210, 297, A4, true);
	run("A5 on A4 (fits)", 148, 210, A4, true);
	run("A4 landscape on A4 portrait", 297, 210, A4, true);
	run("A4 on A4 landscape sheet", 210, 297, A4land, true);
	printf("\n%%s\n", failures ? "FAILED" : "ok - a page larger than the sheet is shrunk onto it, nothing is cut off");
	return failures ? 1 : 0;
}
''' % dict(editor_type_enum=editor_type_enum, settings=settings, page_data=page_data, fit=fit, check=check)

print('lifted FitToPage, CheckPrintRotate from %s%s' % (REPO, ' @ ' + BASE_REF if os.environ.get('BASELINE') else ''))
sys.stdout.flush()
with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'harness.cpp')
    exe = os.path.join(tmp, 'harness')
    open(src, 'w').write(harness)
    c = subprocess.run(['clang++', '-std=c++14', '-w', '-o', exe, src], capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)

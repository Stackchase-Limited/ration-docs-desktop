#!/usr/bin/env python3
"""
#2110 - macOS: printing a slide (to a printer or to PDF) crops its right side. "This issue
does not occur on Windows."

The reporter's PDF is the whole diagnosis. Its one page is US Letter landscape, 792x612 pt,
and its content stream is

    q 0 0 3300 2550 re W n ... q 960 0 0 541 0 71 cm /Im1 Do Q     (/Im1 is 4000x2256 px)

3300x2550 is the sheet at 300 dpi. 4000 px is 300 dpi * 338.67 mm - the full width of a
16:9 slide at 100% - and the 4000-px raster lands at x=0, 960 pt wide on a 792-pt sheet.
The slide was printed actual size from the top-left corner: nothing was fitted.

CPrintData::CheckPrintRotate (fileprinter.cpp) does force pmFit for presentations, but it
learns the editor type from CCefViewEditor::GetEditorType() at print start, and that type is
only set when the host app answers ASC_MENU_EVENT_TYPE_CEF_TABEDITORTYPE with SetEditorType().
The Windows/Linux app does (cascapplicationmanagerwrapper.cpp); the macOS app only uses the
event for its tab icon. On macOS the type stayed etUndefined and CAscPrintSettings' default
pm100 applied. The fix sets the view's type where cefview.cpp handles the renderer's
"EditorType" message, so it no longer depends on the platform shell.

What runs here is the source, not a restatement of it, lifted by brace matching:
  - from cefview.cpp, the "EditorType" message branch, and the print-start line that copies
    the view's type into CPrintData;
  - from fileprinter.cpp, CPrintData::FitToPage and CPrintData::CheckPrintRotate;
  - from applicationmanager.h, CAscPrintSettings (its defaults matter), and from
    fileprinter.h, CPrintContextPageData.
The printer context is a stub that reports what the reporter's PDF shows the macOS context
reported: 300 dpi, a 3300x2550 px sheet, no margins. The CEF/listener types the message
branch touches are stubs with no logic. Each case delivers the "EditorType" message, starts
the print, and checks the page lands inside the sheet; the 16:9 Letter case also shows the
pixel size (4000 px, the reporter's raster) on BASELINE.

NOT claimed: the macOS NSPrintOperation / CoreGraphics side is not run (the PDF already shows
how it places what it is given), and nothing is printed through a real dialog - that needs a
GUI check on macOS.

BASELINE=1 reads the sources at BASE_REF (the parent of the fix): the message branch leaves
the view's type alone, the slide is printed at 100% and overflows the sheet - FAILED.
RD_REPO overrides the desktop-sdk checkout (default ../../desktop-sdk from this file).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk'))
# Pinned to the parent of the commit that landed this fix. It must NOT default to HEAD.
BASE_REF = os.environ.get('BASE_REF', 'c5fa6b67^')
LIB = 'ChromiumBasedEditors/lib'


def read(rel):
    if os.environ.get('BASELINE'):
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s/%s' % (BASE_REF, LIB, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, LIB, rel), encoding='utf-8').read()


def brace_match(src, at, what):
    open_brace = src.index('{', at)
    depth = 0
    for i in range(open_brace, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[at:i + 1]
    raise SystemExit('unbalanced braces extracting %s' % what)


def find(src, needle, what):
    at = src.find(needle)
    if at == -1:
        raise SystemExit('%s is gone (looked for %r)' % (what, needle))
    return at


cefview = read('src/cefview.cpp')
fileprinter = read('src/fileprinter.cpp')
fileprinter_h = read('src/fileprinter.h')
appmanager_h = read('include/applicationmanager.h')

# the "EditorType" branch: from its `if` to the end of its block
at = find(cefview, 'if (message_name == "EditorType"', 'the EditorType message branch')
editor_type_branch = brace_match(cefview, at, 'the EditorType branch')

# the print-start hand-off of the type into CPrintData
m = re.search(r'm_pInternal->m_oPrintData\.m_eEditorType = \(\(CCefViewEditor\*\)this\)->GetEditorType\(\);',
              cefview)
if not m:
    raise SystemExit('print start no longer copies the view type into CPrintData')
print_start_line = m.group(0).replace('m_pInternal->m_oPrintData.', 'data.').replace('this', 'view')

fit = brace_match(fileprinter, find(fileprinter, 'void CPrintData::FitToPage(', 'FitToPage'), 'FitToPage')
check = brace_match(fileprinter, find(fileprinter, 'CPrintData::CPrintContextPageData CPrintData::CheckPrintRotate(',
                                      'CheckPrintRotate'), 'CheckPrintRotate')
page_data = brace_match(fileprinter_h, find(fileprinter_h, 'class CPrintContextPageData', 'CPrintContextPageData'),
                        'CPrintContextPageData') + ';'
settings = brace_match(appmanager_h, find(appmanager_h, 'class CAscPrintSettings', 'CAscPrintSettings'),
                       'CAscPrintSettings') + ';'
enum_at = find(read('include/cefview.h'), 'enum class AscEditorType', 'AscEditorType')
editor_type_enum = brace_match(read('include/cefview.h'), enum_at, 'AscEditorType') + ';'
view_type_at = find(read('include/cefview.h'), 'enum CefViewWrapperType', 'CefViewWrapperType')
view_type_enum = brace_match(read('include/cefview.h'), view_type_at, 'CefViewWrapperType') + ';'

harness = r'''
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>
namespace agg { const double pi = 3.14159265358979323846; }

%(editor_type_enum)s
%(view_type_enum)s
%(settings)s

/* ---- stubs: no logic, only what the lifted code touches ---- */
namespace NSEditorApi {
	struct CAscPrinterContextBase {
		virtual void GetLogicalDPI(int& x, int& y) = 0;
		virtual void GetPhysicalRect(int& x, int& y, int& w, int& h) = 0;
		virtual void GetPrintAreaSize(int& w, int& h) = 0;
	};
	struct CAscTabEditorType { int id = 0, type = 0; void put_Id(int v) { id = v; } void put_Type(int v) { type = v; } };
	struct CAscCefMenuEvent { void* m_pData = nullptr; };
}
#define ASC_MENU_EVENT_TYPE_CEF_TABEDITORTYPE 1
struct Listener { int events = 0; void OnEvent(NSEditorApi::CAscCefMenuEvent* e) { events++; delete (NSEditorApi::CAscTabEditorType*)e->m_pData; delete e; } };
struct Args { int v; int GetInt(int) { return v; } };
struct ArgsPtr { Args* p; Args* operator->() { return p; } };
struct ViewInternal { int m_nEditorType = 0; };
class CCefView {
public:
	ViewInternal* m_pInternal = new ViewInternal();
	CefViewWrapperType m_eWrapperType = cvwtEditor;
	int GetId() { return 7; }
	CefViewWrapperType GetType() { return m_eWrapperType; }
	NSEditorApi::CAscCefMenuEvent* CreateCefEvent(int) { return new NSEditorApi::CAscCefMenuEvent(); }
};
class CCefViewEditor : public CCefView {
	AscEditorType m_eType = AscEditorType::etUndefined;   /* the real constructor's value */
public:
	void SetEditorType(AscEditorType e) { m_eType = e; }
	AscEditorType GetEditorType() { return m_eType; }
};
class CPagePrintData { public: double Width = 0, Height = 0; };
class CPrintData {
public:
	std::vector<CPagePrintData> m_arPages;
	AscEditorType m_eEditorType = AscEditorType::etDocument;   /* CPrintData() sets etDocument */
	%(page_data)s
	static void FitToPage(float, float, float, float, float&, float&, float&, float&);
	CPrintContextPageData CheckPrintRotate(NSEditorApi::CAscPrinterContextBase*, const CAscPrintSettings&, const int&);
};
/* what the reporter's PDF shows the macOS context reported: 300 dpi, sheet 3300x2550, no margins */
struct Paper : NSEditorApi::CAscPrinterContextBase {
	int dpi, w, h;
	Paper(int d, int ww, int hh) : dpi(d), w(ww), h(hh) {}
	void GetLogicalDPI(int& x, int& y) override { x = y = dpi; }
	void GetPhysicalRect(int& x, int& y, int& ww, int& hh) override { x = 0; y = 0; ww = w; hh = h; }
	void GetPrintAreaSize(int& ww, int& hh) override { ww = w; hh = h; }
};

/* ---- lifted from fileprinter.cpp ---- */
%(fit)s
%(check)s

/* ---- the lifted "EditorType" branch, in the shape of its handler ---- */
struct Handler {
	bool m_bIsEditorTypeSet = false;
	CCefView* m_pParent;
	Listener* pListener;
	bool OnMessage(const std::string& message_name, ArgsPtr args) {
		%(editor_type_branch)s
		return false;
	}
};

static int failures = 0;

static void run(const char* what, int rendererType, double slideW, double slideH, Paper paper, bool showPixels)
{
	CCefViewEditor* editor = new CCefViewEditor();
	CCefViewEditor* view = editor;
	Listener listener;
	Handler h; h.m_pParent = editor; h.pListener = &listener;
	Args a{rendererType};
	h.OnMessage("EditorType", ArgsPtr{&a});

	CPrintData data;
	%(print_start_line)s
	CPagePrintData page; page.Width = slideW; page.Height = slideH;
	data.m_arPages.push_back(page);
	CAscPrintSettings settings;   /* the app manager's settings, untouched by a slide print */
	CPrintData::CPrintContextPageData r = data.CheckPrintRotate(&paper, settings, 0);

	bool rotated = std::fabs(r.Angle) > 1e-6;
	double sheetW = rotated ? paper.h : paper.w, sheetH = rotated ? paper.w : paper.h;
	bool inside = r.LeftPix >= -0.5 && r.TopPix >= -0.5 &&
	              r.LeftPix + r.WidthPix <= paper.w + 0.5 && r.TopPix + r.HeightPix <= paper.h + 0.5;
	if (rotated)   /* turned 90 degrees about the centre of the placed rectangle */
		inside = r.WidthPix <= sheetW + 0.5 && r.HeightPix <= sheetH + 0.5 &&
		         std::fabs(r.LeftPix + r.WidthPix / 2 - paper.w / 2.0) < 1.0 &&
		         std::fabs(r.TopPix + r.HeightPix / 2 - paper.h / 2.0) < 1.0;
	printf("  %%-44s view type %%3d -> %%7.1f x %%-7.1f px at (%%6.1f, %%6.1f) on a %%dx%%d sheet  %%s\n",
	       what, (int)view->GetEditorType(), r.WidthPix, r.HeightPix, r.LeftPix, r.TopPix, paper.w, paper.h,
	       inside ? "ok" : "FAILED - overflows the sheet");
	if (showPixels && !inside)
		printf("  %%-44s (the reporter's PDF carries a %%d px wide raster for this page)\n", "", (int)(r.WidthPix + 0.5));
	if (!inside) failures++;
}

int main()
{
	printf("\n");
	/* the report: 16:9 slide, US Letter landscape, 300 dpi */
	run("16:9 slide, US Letter landscape (report)", 1, 338.667, 190.5, Paper(300, 3300, 2550), true);
	run("16:9 slide, A4 landscape", 1, 338.667, 190.5, Paper(300, 3508, 2480), false);
	run("4:3 slide, US Letter landscape", 1, 254.0, 190.5, Paper(300, 3300, 2550), false);
	run("16:9 slide, US Letter portrait", 1, 338.667, 190.5, Paper(300, 2550, 3300), false);
	printf("\n%%s\n", failures ? "FAILED"
	       : "ok - a presentation's slide is fitted to the sheet once the renderer reports the editor type");
	return failures ? 1 : 0;
}
''' % dict(editor_type_enum=editor_type_enum, view_type_enum=view_type_enum, settings=settings,
           page_data=page_data, fit=fit, check=check, editor_type_branch=editor_type_branch,
           print_start_line=print_start_line)

print('extracted from %s%s: EditorType branch, print-start type hand-off, FitToPage, CheckPrintRotate'
      % (REPO, ' @ ' + BASE_REF if os.environ.get('BASELINE') else ''))
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

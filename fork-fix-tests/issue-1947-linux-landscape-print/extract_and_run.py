#!/usr/bin/env python3
"""
#1947 (Linux part) - a landscape document printed on a CUPS printer comes out as a
shrunken portrait page: the 297x210 page scaled down to fit across the top of a
portrait sheet, unrotated. The reporter's CUPS log (ValdikSS, in the issue) has the
cause in it:

    argv[5]="media=A4 sides=one-sided nolandscape ..."

ceditortools.cpp puts the QPrinter into a Landscape QPageLayout when the first page
to print is landscape. Qt's CUPS engine (QCupsPrintEnginePrivate::closePrintDevice,
identical in the shipped Qt 5.9.9 and in 5.15) then adds the job option "landscape"
with an EMPTY value; CUPS encodes an empty boolean as false ("nolandscape"), and
current cups-filters honours that by fitting the landscape page onto the portrait
sheet without turning it. The option cannot be overridden from outside (a second
landscape=true through the engine's CUPS-options property loses to Qt's first one).

Fix: on Linux, for a job going to a CUPS printer (not to a PDF file), send the sheet
portrait and let CPrintData::CheckPrintRotate turn landscape pages onto it - what
quick print (which never sets an orientation; the reporter found it prints right)
and the landscape pages of a portrait-first document already did.

What this runs, all real source by brace matching:
  desktop-apps  ceditortools.cpp  the orientation set-up before the dialog, the
                                  Linux block after it (where the fix is) and
                                  CEditorTools::print(), the page loop;
  desktop-sdk   fileprinter.cpp   CPrintData::CheckPrintRotate + FitToPage;
                qascprinter.cpp   QAscPrinterContext BeginPaint/EndPaint/GetLogicalDPI/
                                  GetPhysicalRect/GetPrintAreaSize/getPrinter;
                qrenderer.cpp     CQRenderer::PrepareBitBlt (the page placement and
                                  the 90-degree turn of the vector print path);
                applicationmanager.h  CAscPrintSettings (defaults: pm100, rotate on).
Each page is a marker drawn in page coordinates (a bar along the page's top edge, a
square under its top-left corner) through those transforms, printed with a real
QPrinter to a real CUPS queue (generic PostScript PPD with a duplexer) whose backend
captures the job. The captured argv and the final PostScript are checked per job:
no landscape/nolandscape option, sides and the PPD Duplex/Tumble as requested, and
per sheet: portrait sheet, the marker filling it (not shrunk), portrait pages
upright, every landscape page turned the same way by 90 degrees.
Documents: PPPP, LLLL, PLPL, LPLP; sides: one-sided, long edge, short edge.

On tumble: IPP "sides" is defined against the sheet's edges, not the content, so a
portrait job of turned landscape pages with two-sided-long-edge correctly gets
Tumble false - the same Duplex/Tumble CUPS emits when it turns a landscape PDF
itself (checked: a landscape Qt PDF sent with no orientation option also prints
DuplexNoTumble, turned the other way round, i.e. the same pairing of fronts and backs).

BASELINE=1 reads ceditortools.cpp from BASE_REF (desktop-sdk is unchanged): LLLL and
LPLP go out with "nolandscape" and come back shrunk -> FAIL.

NOT claimed: a real printer's handling (duplex units, driverless IPP printers that
take the PDF directly); the raster print path (QAscPrinterContext::BitBlt, used when
the vector renderer refuses a page) is not drawn here - it applies the same rotate(90)
around the same centre; Windows (#1947's original report) is untouched by this fix.

Runs on Linux with root (installs cups in a throwaway container): by default the
build/print step runs in Docker image rd-linux-verify:24.04 (Qt 5.15, set RD_IMAGE to
change); RD_NO_DOCKER=1 runs it on this machine (needs cups, cups-filters,
ghostscript, qtbase5-dev, and permission to add a CUPS queue).
  RD_REPO      desktop-apps checkout (default ../../desktop-apps)
  RD_SDK_REPO  desktop-sdk checkout (default ../../desktop-sdk)
  BASELINE=1   ceditortools.cpp from BASE_REF (default: parent of the fix commit)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
SDK = os.environ.get('RD_SDK_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'f20587061^')
BASELINE = bool(os.environ.get('BASELINE'))
IMAGE = os.environ.get('RD_IMAGE', 'rd-linux-verify:24.04')

TOOLS = 'win-linux/src/ceditortools.cpp'
FP = 'ChromiumBasedEditors/lib/src/fileprinter.cpp'
QP = 'ChromiumBasedEditors/lib/qt_wrapper/src/qascprinter.cpp'
QR = 'ChromiumBasedEditors/lib/qt_wrapper/qrenderer/src/qrenderer.cpp'
AM = 'ChromiumBasedEditors/lib/include/applicationmanager.h'


def read(repo, rel, from_git=False):
    if from_git:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


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
    raise SystemExit('unbalanced braces from offset %d' % start)


def extract(text, anchor, needles=()):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit('%r not found - the extractor needs updating' % anchor)
    body = brace_match(text, at)
    for n in needles:
        if n not in body:
            raise SystemExit('extracted %r is missing %r - wrong block?' % (anchor, n))
    return body


def between(text, start, end, needles=()):
    a = text.find(start)
    if a == -1:
        raise SystemExit('%r not found - the extractor needs updating' % start)
    b = text.find(end, a)
    body = text[a:b]
    for n in needles:
        if n not in body:
            raise SystemExit('block at %r is missing %r' % (start, n))
    return body


tools = read(REPO, TOOLS, BASELINE)
fp = read(SDK, FP)
qp = read(SDK, QP)
qr = read(SDK, QR)
am = read(SDK, AM)

pre_dialog = extract(tools, 'if ( !AscAppManager::printData().isQuickPrint() ) {\n                //',
                     ('setPageSize', 'pageOrientation'))
post_dialog = between(tools, 'if ( printer->outputFormat() == QPrinter::PdfFormat ) {', '#endif',
                      ('setOutputFileName("")',))
print_loop = extract(tools, 'void print(const sPrintConf& c)', ('newPage', 'ASC_MENU_EVENT_TYPE_CEF_PRINT_PAGE'))
check_rotate = extract(fp, 'CPrintData::CPrintContextPageData CPrintData::CheckPrintRotate(', ('tmp_M_PI_2',))
fit = extract(fp, 'void CPrintData::FitToPage(')
ctx_methods = '\n'.join(extract(qp, a) for a in (
    'bool QAscPrinterContext::BeginPaint()', 'void QAscPrinterContext::EndPaint()',
    'QPrinter* QAscPrinterContext::getPrinter()', 'void QAscPrinterContext::GetLogicalDPI(',
    'void QAscPrinterContext::GetPhysicalRect(', 'void QAscPrinterContext::GetPrintAreaSize('))
prepare = extract(qr, 'void NSQRenderer::CQRenderer::PrepareBitBlt(', ('rotate(90)',))
settings_cls = extract(am, 'class CAscPrintSettings', ('RotateEnable',)) + ';'
page_data_cls = extract(read(SDK, 'ChromiumBasedEditors/lib/src/fileprinter.h'),
                        'class CPrintContextPageData', ('IsRotate',)) + ';'

SRC = r'''
#include <QApplication>
#include <QPrinter>
#include <QPrinterInfo>
#include <QPrintEngine>
#include <QPainter>
#include <QPageLayout>
#include <QFileInfo>
#include <QTransform>
#include <QVector>
#include <cmath>
#include <cstdio>
#include <vector>
#include <string>

namespace agg { const double pi = 3.14159265358979323846; }
enum class AscEditorType { etDocument, etPresentation, etSpreadsheet };
SETTINGS_CLS

// ---- QAscPrinterContext: the real methods on the real members --------------------
class QAscPrinterContext {
public:
	QPrinter m_oPrinter;
	QPainter m_oPainter;
	QPaintDevice* m_pDevice = NULL;
	enum { pdtNone, pdtSimple, pdtPaged } m_eDeviceType = pdtNone;
	bool m_bIsUsePainter = false;
	QAscPrinterContext(const QPrinterInfo& pi) : m_oPrinter(pi, QPrinter::HighResolution) {
		// QAscPrinterContext::setDefaults
		QPrinterInfo oInfo(m_oPrinter);
		m_oPrinter.setDuplex(oInfo.defaultDuplexMode());
		m_oPrinter.setPageSize(oInfo.defaultPageSize());
	}
	bool BeginPaint(); void EndPaint(); QPrinter* getPrinter();
	void GetLogicalDPI(int&, int&); void GetPhysicalRect(int&, int&, int&, int&); void GetPrintAreaSize(int&, int&);
	QPainter* GetPainter() { return &m_oPainter; }
	void AddRef() {}
	void SetPageOrientation(int) {}		// a no-op in qascprinter.cpp (bug 59263)
};
namespace NSEditorApi { typedef QAscPrinterContext CAscPrinterContextBase; }
CTX_METHODS

// ---- CQRenderer::PrepareBitBlt on the members it uses ----------------------------
namespace NSQRenderer {
class CQRenderer {
public:
	QAscPrinterContext* m_pContext;
	int m_nPixelWidth, m_nPixelHeight;
	double m_dTileScaleX, m_dTileScaleY;
	QTransform m_oPositionTransform;
	CQRenderer(QAscPrinterContext* c) : m_pContext(c) {}
	void applyTransform() { m_pContext->GetPainter()->setTransform(m_oPositionTransform); }
	void PrepareBitBlt(const int&, const int&, const int&, const int&, const double&, const double&,
	                   const double&, const double&, const double&, const double&, const double&);
};
}
PREPARE

// ---- CPrintData::CheckPrintRotate ------------------------------------------------
struct CPagePrintData { double Width, Height; };
class CPrintData {
public:
	std::vector<CPagePrintData> m_arPages;
	AscEditorType m_eEditorType = AscEditorType::etDocument;
	PAGE_DATA_CLS
	void FitToPage(float, float, float, float, float&, float&, float&, float&);
	CPrintContextPageData CheckPrintRotate(NSEditorApi::CAscPrinterContextBase*, const CAscPrintSettings&, const int&);
};
FIT
CHECK_ROTATE

// ---- the page: a marker in page pixels, placed as CPrintData::Print does ---------
static CPrintData g_doc;
static void drawPage(QAscPrinterContext* ctx, int idx) {
	CAscPrintSettings settings;
	CPrintData::CPrintContextPageData d = g_doc.CheckPrintRotate(ctx, settings, idx);
	ctx->GetPainter()->save();
	NSQRenderer::CQRenderer r(ctx);
	r.PrepareBitBlt(0, 0, (int)(d.WidthPix + 0.5), (int)(d.HeightPix + 0.5), d.LeftPix, d.TopPix, d.WidthPix, d.HeightPix, d.Angle, 1, 1);
	QPainter* p = ctx->GetPainter();
	double w = d.WidthPix, h = d.HeightPix, s = std::min(w, h);
	p->fillRect(QRectF(0, 0, w, 0.04 * s), Qt::black);                     // along the top edge
	p->fillRect(QRectF(0.02 * s, 0.08 * s, 0.12 * s, 0.12 * s), Qt::black); // under the top-left corner
	ctx->GetPainter()->restore();
}

// ---- stubs for what CEditorTools::print() touches ---------------------------------
struct PageRanges { int fromPage, toPage; PageRanges(int a = 0, int b = 0) : fromPage(a), toPage(b) {} };
struct CPrintProgress { CPrintProgress(void*) {} void startProgress() {} void setProgress(int, int) {} bool isRejected() { return false; } };
#define PROCESSEVENTS()
#define ASC_MENU_EVENT_TYPE_CEF_PRINT_PAGE 5012
struct CAscPrintPage { QAscPrinterContext* c; int n; void put_Context(QAscPrinterContext* x) { c = x; } void put_Page(int x) { n = x; } };
struct CAscMenuEvent { int t; void* m_pData; CAscMenuEvent(int x) : t(x), m_pData(0) {} };
struct CCefView {
	int GetPrintPageOrientation(int i) { return (i >= 0 && i < (int)g_doc.m_arPages.size() && g_doc.m_arPages[i].Width > g_doc.m_arPages[i].Height) ? 1 : 0; }
	void Apply(CAscMenuEvent* e) { CAscPrintPage* d = (CAscPrintPage*)e->m_pData; drawPage(d->c, d->n); delete d; delete e; }
};
struct sPrintConf { CCefView* view; QAscPrinterContext* context; QVector<PageRanges>* page_ranges; void* parent; };
PRINT_LOOP

// ---- AscAppManager::printData() as the in-app print panel fills it -----------------
struct PrintData {
	QPageLayout::Orientation o;
	bool isQuickPrint() { return false; }
	bool useSystemDialog() { return false; }
	QPageSize pageSize() { return QPageSize(QPageSize::A4); }	// preset "A4" (cprintdata.cpp)
	QPageLayout::Orientation pageOrientation() { return o; }
};
static PrintData g_pd;
namespace AscAppManager { PrintData& printData() { return g_pd; } }
#define LOCAL_PATH_SAVE 0
namespace Utils { void keepLastPath(int, const QString&) {} }

int main(int argc, char** argv) {
	QApplication app(argc, argv);
	QString pattern = argv[2], sides = argv[3];
	for (QChar ch : pattern)
		g_doc.m_arPages.push_back(ch == 'L' ? CPagePrintData{297, 210} : CPagePrintData{210, 297});
	// the panel's paperOrientation is taken from the first page printed
	g_pd.o = g_doc.m_arPages[0].Width > g_doc.m_arPages[0].Height ? QPageLayout::Landscape : QPageLayout::Portrait;

	QAscPrinterContext* pContext = new QAscPrinterContext(QPrinterInfo::printerInfo(argv[1]));
	QPrinter* printer = pContext->getPrinter();
	int pagesCount = pattern.size();
	printer->setFromTo(1, pagesCount);
	printer->setDuplex(sides == "long" ? QPrinter::DuplexLongSide : sides == "short" ? QPrinter::DuplexShortSide : QPrinter::DuplexNone);
	PRE_DIALOG
	QFileInfo info("/tmp/doc.docx");
	printer->printEngine()->setProperty(QPrintEngine::PPK_OutputFileName, QString("/tmp/doc.pdf"));
	// dialog->accept(): the in-app panel, no system dialog
	POST_DIALOG
	QVector<PageRanges> page_ranges; page_ranges.append(PageRanges(1, pagesCount));
	print({new CCefView, pContext, &page_ranges, NULL});
	return 0;
}
'''
for k, v in (('SETTINGS_CLS', settings_cls), ('CTX_METHODS', ctx_methods), ('PREPARE', prepare),
             ('PAGE_DATA_CLS', page_data_cls), ('FIT', fit), ('CHECK_ROTATE', check_rotate),
             ('PRINT_LOOP', print_loop), ('PRE_DIALOG', pre_dialog), ('POST_DIALOG', post_dialog)):
    SRC = SRC.replace(k, v, 1)

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
lpadmin -p rd1947 -E -v capture:/x -m drv:///sample.drv/generic.ppd -o PageSize=A4 -o Option1=True 2>/dev/null
cd /t && g++ -std=gnu++17 -fPIC -w t.cpp -o t $(pkg-config --cflags --libs Qt5Widgets Qt5PrintSupport)
n=0
for doc in PPPP LLLL PLPL LPLP; do for s in none long short; do
  ./t rd1947 $doc $s 2>/dev/null; n=$((n+1))
  while [ $(ls /tmp/out/*.data 2>/dev/null | wc -l) -lt $n ]; do sleep 1; done
  f=$(ls -t /tmp/out/*.data | head -1); echo "$doc $s" > ${f%.data}.case
done; done
sleep 1
for f in /tmp/out/*.data; do b=${f%.data}; gs -q -dNOPAUSE -dBATCH -sDEVICE=pgmraw -r20 -sOutputFile=$b-%d.pgm $f; done
cp /tmp/out/* /t/out/
'''


def read_pgm(path):
    data = open(path, 'rb').read()
    parts, i = [], 0
    while len(parts) < 4:
        while data[i:i + 1].isspace():
            i += 1
        if data[i:i + 1] == b'#':
            while data[i:i + 1] != b'\n':
                i += 1
            continue
        j = i
        while not data[j:j + 1].isspace():
            j += 1
        parts.append(data[i:j])
        i = j
    w, h = int(parts[1]), int(parts[2])
    px = data[i + 1:i + 1 + w * h]
    return w, h, [[px[y * w + x] < 128 for x in range(w)] for y in range(h)]


def classify(w, h, dark):
    """-> (top_edge, left_edge, bar_coverage): the sheet edge the page's top bar runs
    along, the sheet edge the page's left side is on, and how much of that edge the
    bar covers (1.0 = the page fills the sheet; a shrunk page stays well under)."""
    edges = {
        'top': [(x, y) for y in range(0, max(2, h // 25)) for x in range(w)],
        'bottom': [(x, y) for y in range(h - max(2, h // 25), h) for x in range(w)],
        'left': [(x, y) for x in range(0, max(2, w // 25)) for y in range(h)],
        'right': [(x, y) for x in range(w - max(2, w // 25), w) for y in range(h)],
    }
    score = {e: sum(dark[y][x] for x, y in pts) / len(pts) for e, pts in edges.items()}
    top = max(score, key=score.get)
    along = w if top in ('top', 'bottom') else h
    covered = set()
    for x, y in edges[top]:
        if dark[y][x]:
            covered.add(x if top in ('top', 'bottom') else y)
    coverage = len(covered) / along
    # the square sits under one end of the bar: which end?
    depth = int(0.08 * min(w, h)), int(0.20 * min(w, h))
    def region(first_half):
        cnt = 0
        for t in range(along // 2):
            a = t if first_half else along - 1 - t
            for d in range(depth[0], depth[1]):
                x, y = {'top': (a, d), 'bottom': (a, h - 1 - d), 'left': (d, a), 'right': (w - 1 - d, a)}[top]
                cnt += dark[y][x]
        return cnt
    first = region(True) > region(False)
    left = {'top': ('left', 'right'), 'bottom': ('left', 'right'),
            'left': ('top', 'bottom'), 'right': ('top', 'bottom')}[top][0 if first else 1]
    return top, left, coverage


def main():
    work = tempfile.mkdtemp(prefix='rd1947-')
    os.makedirs(os.path.join(work, 'out'))
    open(os.path.join(work, 't.cpp'), 'w').write(SRC)
    open(os.path.join(work, 'capture'), 'w').write(BACKEND)
    open(os.path.join(work, 'run.sh'), 'w').write(RUN)
    if os.environ.get('RD_NO_DOCKER'):
        os.symlink(work, '/t') if not os.path.exists('/t') else None
        subprocess.run(['sh', '/t/run.sh'], check=True)
    else:
        subprocess.run(['docker', 'run', '--rm', '-v', '%s:/t' % work, IMAGE, 'sh', '/t/run.sh'], check=True)

    out = os.path.join(work, 'out')
    failures = 0
    cases = sorted((f for f in os.listdir(out) if f.endswith('.case')), key=lambda f: int(f[4:-5]))
    if len(cases) != 12:
        raise SystemExit('expected 12 captured jobs, got %d' % len(cases))
    for c in cases:
        base = os.path.join(out, c[:-5])
        doc, sides = open(base + '.case').read().split()
        args = open(base + '.args').read()
        ps = open(base + '.data', 'rb').read()
        problems = []
        if 'landscape' in args.split():
            problems.append('job option landscape')
        if 'nolandscape' in args.split():
            problems.append('job option nolandscape')
        want_sides = {'none': 'one-sided', 'long': 'two-sided-long-edge', 'short': 'two-sided-short-edge'}[sides]
        if 'sides=' + want_sides not in args:
            problems.append('sides is not ' + want_sides)
        want_ps = {'none': b'<</Duplex false>>', 'long': b'<</Duplex true/Tumble false>>',
                   'short': b'<</Duplex true/Tumble true>>'}[sides]
        if want_ps not in ps:
            problems.append('PostScript lacks %s' % want_ps.decode())
        turned = set()
        sheets = []
        for i, kind in enumerate(doc, 1):
            w, h, dark = read_pgm('%s-%d.pgm' % (base, i))
            top, left, cov = classify(w, h, dark)
            sheets.append('%s:%s/%s/%.2f' % (kind, top, left, cov))
            if w > h:
                problems.append('sheet %d is landscape' % i)
            if cov < 0.9:
                problems.append('page %d shrunk (bar covers %.0f%% of the edge)' % (i, 100 * cov))
            if kind == 'P' and (top, left) != ('top', 'left'):
                problems.append('portrait page %d not upright (%s/%s)' % (i, top, left))
            if kind == 'L':
                if (top, left) not in (('right', 'top'), ('left', 'bottom')):
                    problems.append('landscape page %d not turned 90 degrees (%s/%s)' % (i, top, left))
                turned.add((top, left))
        if len(turned) > 1:
            problems.append('landscape pages turned different ways')
        verdict = 'ok  ' if not problems else 'FAIL'
        failures += bool(problems)
        print('%s %-4s %-5s %s  %s%s' % (verdict, doc, sides, ' '.join(sheets),
                                        'nolandscape ' if 'nolandscape' in args.split() else '',
                                        ('<- ' + '; '.join(problems)) if problems else ''))
    shutil.rmtree(work, ignore_errors=True)
    print('%s: %d/12 jobs wrong (%s)' % ('FAIL' if failures else 'PASS', failures,
                                          'BASELINE ' + BASE_REF if BASELINE else 'working tree'))
    sys.exit(1 if failures else 0)


main()

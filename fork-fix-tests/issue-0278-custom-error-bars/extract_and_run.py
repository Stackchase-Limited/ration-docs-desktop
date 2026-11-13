#!/usr/bin/env python3
"""
#278 - custom error bars whose plus/minus values come from sheet ranges.

Before: the spreadsheet editor could only add Standard error / Percentage /
Standard deviation error bars (asc_ChartSettings.setDisplayErrorBars,
common/apiCommon.js); a CUST bar got a one-point constant. The model already
read, drew and round-tripped c:errBars with c:plus/c:minus c:numRef, but
  * nothing in the API could build such bars from a range, and
  * CErrBars.getPlusDataRefs/getMinusDataRefs (common/Drawings/Format/
    ChartFormat.js) dropped the refs (no `return`), so the chart never noticed
    edits to the error-value cells: the bars kept their old cached values.
  * CErrBars.setErrValType recorded errDir as the old value, so undoing a
    change of error value type restored the wrong type.

Now asc_ChartSettings.setCustomErrorBars(plus, minus, barType, endCap[, errDir])
builds CMinusPlus numRefs (CMinusPlus.setValues, like series values), fills
their caches from the sheet, and the chart follows edits to those cells.

End to end: the sdkjs tree under test (BASELINE=1: the same tree with every file
changed since BASE_REF taken from BASE_REF) is built with the fork's build
(build/build.py --product cell) into a temp copy; core's docbuilder opens an
empty xlsx, enters data, adds a bar chart, calls setCustomErrorBars, changes an
error-value cell, passes that cell to Workbook.handleDrawingsOnWorkbookChange
(what WorksheetView calls after an edit) and saves xlsx. The test checks the chart XML of that file (c:errBars cust, the two
c:f refs, cached values including the edited cell, Plus-only/No-cap settings),
then reopens the saved file in docbuilder (x2t xlsx -> sdkjs -> xlsx again) and
checks getCustomErrorBars() reads the same refs back and the second save keeps
them: the x2t round trip.

NOT claimed: the web-apps "Format error bars" dialog (needs a GUI check); Excel
was not run - the XML shape follows ECMA-376 21.2.2.55 errBars and what x2t
already writes for files from Excel.

  RD_REPO=<sdkjs checkout>           (default ../../sdkjs)
  RD_CORE_BUILD=<core build dir>     (default ../../core/build; needs bin/mac_arm64/{docbuilder,x2t})
  RD_WEBAPPS=<web-apps checkout>     (default ../../web-apps; only vendor/xregexp is used)
  RD_FONTS=<font cache dir>          (default ../../../.rd-work/fonts-cache; copied, never written)
  BASELINE=1                         use BASE_REF's version of the changed files; must FAIL
  BASE_REF                           default: parent of the #278 commit
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
REPO = os.path.abspath(os.environ.get('RD_REPO') or os.path.join(ROOT, 'sdkjs'))
CORE = os.path.abspath(os.environ.get('RD_CORE_BUILD') or os.path.join(ROOT, 'core', 'build'))
WEBAPPS = os.path.abspath(os.environ.get('RD_WEBAPPS') or os.path.join(ROOT, 'web-apps'))
FONTS = os.path.abspath(os.environ.get('RD_FONTS') or os.path.join(ROOT, '..', '.rd-work', 'fonts-cache'))
BASE_REF = os.environ.get('BASE_REF', 'cca3a897a9^')
BASELINE = bool(os.environ.get('BASELINE'))
BIN = os.path.join(CORE, 'bin', 'mac_arm64')
LIB = os.path.join(CORE, 'lib', 'mac_arm64')


def git(*a):
    return subprocess.run(['git', '-C', REPO] + list(a), capture_output=True, check=True).stdout


def shadow(dst, overrides):
    """dst mirrors REPO by symlinks; paths in overrides (rel -> bytes) are real files."""
    def fill(rel):
        src = os.path.join(REPO, rel)
        here = os.path.join(dst, rel)
        os.makedirs(here, exist_ok=True)
        for name in os.listdir(src):
            r = os.path.join(rel, name) if rel else name
            if name in ('deploy', 'develop') and not rel:
                continue
            if any(o == r or o.startswith(r + '/') for o in overrides):
                if r in overrides:
                    with open(os.path.join(dst, r), 'wb') as f:
                        f.write(overrides[r])
                else:
                    fill(r)
            else:
                os.symlink(os.path.join(src, name), os.path.join(dst, r))
    fill('')
    b = os.path.join(dst, 'build')
    if os.path.islink(b):
        os.unlink(b)
        os.makedirs(b)
        for name in os.listdir(os.path.join(REPO, 'build')):
            os.symlink(os.path.join(REPO, 'build', name), os.path.join(b, name))


def empty_xlsx(path):
    ct = 'application/vnd.openxmlformats-officedocument.spreadsheetml'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="%s.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="%s.worksheet+xml"/></Types>' % (ct, ct))
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/></Relationships>' % rel)
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="%s"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % rel)
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/worksheet" Target="worksheets/sheet1.xml"/></Relationships>' % rel)
        z.writestr('xl/worksheets/sheet1.xml', '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')


# Results go to cells of a second sheet: docbuilder has no reliable stdout.
SCRIPT1 = '''
builder.OpenFile("%(xlsx)s");
var s = Api.GetActiveSheet();
var data = [["Q1", 10, 1, 0.5], ["Q2", 20, 2, 1], ["Q3", 30, 3, 1.5], ["Q4", 40, 4, 2]];
for (var i = 0; i < data.length; i++) {
    s.GetRange("A" + (i + 1)).SetValue(data[i][0]);
    s.GetRange("B" + (i + 1)).SetValue(data[i][1]);
    s.GetRange("C" + (i + 1)).SetValue(data[i][2]);
    s.GetRange("D" + (i + 1)).SetValue(data[i][3]);
}
var chart = s.AddChart("'Sheet1'!$A$1:$B$4", true, "bar", 2, 100 * 36000, 70 * 36000, 5, 0, 1, 0);
var res = s.GetRange("H1");
try {
    var props = chart.Chart.getAscSettings();
    var rc = props.setCustomErrorBars("Sheet1!$C$1:$C$4", "Sheet1!$D$1:$D$4", AscFormat.st_errbartypeBOTH, true);
    s.GetRange("H2").SetValue("rc=" + rc);
    var bad = props.isValidCustomErrorBars("not a range", "");
    s.GetRange("H3").SetValue("bad=" + bad);
    s.GetRange("C2").SetValue(7);   // edit an error-value cell after the bars exist
    // what WorksheetView does after an edit (WorkbookView.handleDrawingsOnWorkbookChange -> model)
    Asc.editor.wbModel.handleDrawingsOnWorkbookChange([new AscCommonExcel.Range(s.worksheet, 1, 2, 1, 2)]);
    var ser = chart.Chart.getAllSeries()[0];
    var pts = ser.errBars[0].plus.numRef.numCache.pts.map(function (p) { return p.val; });
    s.GetRange("H4").SetValue("cache=" + pts.join(","));
    res.SetValue("ok");
} catch (e) {
    res.SetValue("ERR " + e.message);
}
builder.SaveFile("xlsx", "%(out1)s");
builder.CloseFile();
'''

SCRIPT2 = '''
builder.OpenFile("%(out1)s");
var s = Api.GetActiveSheet();
var res = s.GetRange("I1");
try {
    var cs = null;
    var drawings = s.GetAllCharts();
    cs = drawings[0].Chart;
    var info = cs.getAscSettings().getCustomErrorBars();
    res.SetValue(info ? ("plus=" + info.plus + "|minus=" + info.minus + "|type=" + info.barType + "|cap=" + info.endCap + "|val=" + info.errValType) : "none");
    // second edit: plus only, no end caps, same refs
    var rc = cs.getAscSettings().setCustomErrorBars("Sheet1!$C$1:$C$4", "", AscFormat.st_errbartypePLUS, false);
    s.GetRange("I2").SetValue("rc2=" + rc);
} catch (e) {
    res.SetValue("ERR " + e.message);
}
builder.SaveFile("xlsx", "%(out2)s");
builder.CloseFile();
'''


def chart_xml(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.match(r'xl/charts/chart\d+\.xml$', n)]
        return z.read(names[0]).decode('utf-8') if names else ''


def cell_texts(path):
    with zipfile.ZipFile(path) as z:
        ss = z.read('xl/sharedStrings.xml').decode('utf-8') if 'xl/sharedStrings.xml' in z.namelist() else ''
    return re.findall(r'<t[^>]*>([^<]*)</t>', ss)


def errbars(xml):
    m = re.search(r'<c:errBars>(.*?)</c:errBars>', xml, re.S)
    return m.group(1) if m else ''


def part(xml, tag):
    m = re.search(r'<c:%s>(.*?)</c:%s>' % (tag, tag), xml, re.S)
    return m.group(1) if m else ''


def main():
    for f in ('docbuilder', 'x2t'):
        if not os.path.exists(os.path.join(BIN, f)):
            sys.exit('FAIL: %s not built in %s (set RD_CORE_BUILD)' % (f, BIN))
    if not os.path.exists(os.path.join(FONTS, 'AllFonts.js')):
        sys.exit('FAIL: no AllFonts.js in %s (set RD_FONTS)' % FONTS)
    overrides = {}
    if BASELINE:
        changed = git('diff', '--name-only', BASE_REF, '--', '.').decode().split()
        for rel in changed:
            try:
                overrides[rel] = git('show', '%s:%s' % (BASE_REF, rel))
            except subprocess.CalledProcessError:
                pass
    with tempfile.TemporaryDirectory(prefix='rd278-') as tmp:
        tree = os.path.join(tmp, 'sdkjs')
        shadow(tree, overrides)
        r = subprocess.run([sys.executable, os.path.join(tree, 'build', 'build.py'), '--product', 'cell', '--beta=false'],
                           capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-2000:], r.stderr[-2000:])
            sys.exit('FAIL: sdkjs build failed')
        fonts = os.path.join(tmp, 'fonts')   # a copy: x2t may rewrite AllFonts.js in its font dir
        os.makedirs(fonts)
        for n in ('AllFonts.js', 'font_selection.bin'):
            shutil.copy2(os.path.join(FONTS, n), os.path.join(fonts, n))
        app = os.path.join(tmp, 'app')
        os.makedirs(os.path.join(app, 'bin'))
        os.makedirs(os.path.join(app, 'editors', 'web-apps', 'vendor'))
        os.symlink(LIB, os.path.join(app, 'Frameworks'))
        shutil.copy2(os.path.join(BIN, 'docbuilder'), os.path.join(app, 'bin', 'docbuilder'))
        subprocess.run(['cp', '-c', os.path.join(BIN, 'x2t'), os.path.join(app, 'bin', 'x2t')], check=True)
        os.symlink(os.path.join(tree, 'deploy', 'sdkjs'), os.path.join(app, 'editors', 'sdkjs'))
        os.symlink(os.path.join(WEBAPPS, 'vendor', 'xregexp'), os.path.join(app, 'editors', 'web-apps', 'vendor', 'xregexp'))
        with open(os.path.join(app, 'bin', 'DoctRenderer.config'), 'w') as f:
            f.write('<Settings>\n<file>../editors/sdkjs/common/Native/native.js</file>\n'
                    '<file>../editors/sdkjs/common/Native/jquery_native.js</file>\n'
                    '<allfonts>%s</allfonts>\n<file>../editors/web-apps/vendor/xregexp/xregexp-all-min.js</file>\n'
                    '<sdkjs>../editors/sdkjs</sdkjs>\n</Settings>\n' % os.path.join(fonts, 'AllFonts.js'))
        xlsx = os.path.join(tmp, 'empty.xlsx')
        empty_xlsx(xlsx)
        p = {'xlsx': xlsx, 'out1': os.path.join(tmp, 'out1.xlsx'), 'out2': os.path.join(tmp, 'out2.xlsx')}
        for name, script, out in (('s1.js', SCRIPT1, p['out1']), ('s2.js', SCRIPT2, p['out2'])):
            js = os.path.join(tmp, name)
            with open(js, 'w') as f:
                f.write(script % p)
            r = subprocess.run([os.path.join(app, 'bin', 'docbuilder'), js], cwd=tmp, capture_output=True, text=True, timeout=300)
            if not os.path.exists(out):
                print(r.stdout[-2000:], r.stderr[-2000:])
                sys.exit('FAIL: docbuilder produced no %s' % os.path.basename(out))
        x1, x2 = chart_xml(p['out1']), chart_xml(p['out2'])
        t1, t2 = cell_texts(p['out1']), cell_texts(p['out2'])
    e1, e2 = errbars(x1), errbars(x2)
    plus1, minus1 = part(e1, 'plus'), part(e1, 'minus')
    checks = [
        ('setCustomErrorBars ran', 'ok' in t1, 'script result %r' % [t for t in t1 if t.startswith(('ok', 'ERR'))]),
        ('returned No error', 'rc=0' in t1, 'got %r' % [t for t in t1 if t.startswith('rc=')]),
        ('a bad range is rejected', any(t.startswith('bad=') and t != 'bad=0' for t in t1), 'got %r' % [t for t in t1 if t.startswith('bad=')]),
        ('cache follows the edited cell C2 (1,7,3,4)', 'cache=1,7,3,4' in t1, 'got %r' % [t for t in t1 if t.startswith('cache=')]),
        ('saved c:errBars is custom', '<c:errValType val="cust"/>' in e1, 'errBars=%r' % e1[:300]),
        ('saved plus ref', '<c:f>Sheet1!$C$1:$C$4</c:f>' in plus1, 'plus=%r' % plus1[:200]),
        ('saved minus ref', '<c:f>Sheet1!$D$1:$D$4</c:f>' in minus1, 'minus=%r' % minus1[:200]),
        ('saved plus cache has the edit', '<c:v>7</c:v>' in plus1, 'plus=%r' % plus1[:400]),
        ('saved both directions with caps', '<c:errBarType val="both"/>' in e1 and '<c:noEndCap val="0"/>' in e1, 'errBars=%r' % e1[:300]),
        ('reopened file reads the refs back', 'plus==Sheet1!$C$1:$C$4|minus==Sheet1!$D$1:$D$4|type=0|cap=true|val=0' in t2,
         'got %r' % [t for t in t2 if t.startswith(('plus=', 'none', 'ERR'))]),
        ('second save: plus only, no caps', '<c:errBarType val="plus"/>' in e2 and '<c:noEndCap val="1"/>' in e2
         and '<c:f>Sheet1!$C$1:$C$4</c:f>' in part(e2, 'plus') and '<c:minus>' not in e2, 'errBars=%r' % e2[:400]),
    ]
    fails = 0
    for name, ok, why in checks:
        print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else ': ' + why))
        fails += 0 if ok else 1
    print('FAIL %d check(s)' % fails if fails else 'PASS #278 custom error bars from sheet ranges (docbuilder + x2t round trip)')
    sys.exit(1 if fails else 0)


main()

#!/usr/bin/env python3
"""
#883 follow-up - FREQUENCY returned its counts in sorted-bin order and took
text/logical bins as 0.

#883 itself (horizontal result) was already right in 9.4. Its triage found two
more differences from Excel in cFREQUENCY (cell/model/FormulaObjects/
statisticalFunctions.js):
  * bins_array was sorted and the counts written in that sorted order:
    data 1..10, bins {7;2;5} gave 2,3,2,3; Excel gives 2,2,3,3 (each count in
    the row of its bin - the intervals come from the sorted bins). LibreOffice's
    ScFrequency (sc/source/core/tool/interpr5.cxx) does the same through a bin
    index order; community tests of unsorted bins in Excel agree.
  * a text or logical bin was pushed as a 0 bin: bins {3;"x";8} gave 0,3,5,2;
    Excel ignores text ("FREQUENCY ignores blank cells and text"), so the result
    is 3,5,2 and the 4th row of the array formula is #N/A.

End to end: the sdkjs tree under test (BASELINE=1: the same tree with every
file changed since BASE_REF taken from BASE_REF) is built with the fork's
concat build (build/build.py --product cell) into a temp copy, a font list is
generated with core's allfontsgen, and core's docbuilder (with core's x2t) opens
an empty xlsx, enters the data and the two FREQUENCY array formulas, and saves
CSV. The test reads the computed cells from that CSV.

NOT claimed: Excel was not run here; the expected values follow Microsoft's
documentation, LibreOffice's Excel-compatible implementation and published
Excel tests of unsorted bins. Bins holding logical values are treated like
text (ignored), as LibreOffice does for references.

  RD_REPO=<sdkjs checkout>           (default ../../sdkjs)
  RD_CORE_BUILD=<core build dir>     (default ../../core/build; needs bin/mac_arm64/{docbuilder,x2t,allfontsgen})
  RD_WEBAPPS=<web-apps checkout>     (default ../../web-apps; only vendor/xregexp is used)
  BASELINE=1                         use BASE_REF's version of the changed files; must FAIL
  BASE_REF                           default: parent of the #883 commit
"""
import csv
import os
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
BASE_REF = os.environ.get('BASE_REF', '0bb6ae9857^')
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
    # build.py writes deploy/ next to its own directory: give it a real build/ dir
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


SCRIPT = '''
builder.OpenFile("%(xlsx)s");
var s = Api.GetActiveSheet();
for (var i = 1; i <= 10; i++) s.GetRange("A" + i).SetValue(i);
s.GetRange("B1").SetValue(7); s.GetRange("B2").SetValue(2); s.GetRange("B3").SetValue(5);
s.GetRange("C1").SetValue(3); s.GetRange("C2").SetValue("x"); s.GetRange("C3").SetValue(8);
s.GetRange("D1:D4").SetFormulaArray("=FREQUENCY(A1:A10,B1:B3)");
s.GetRange("E1:E4").SetFormulaArray("=FREQUENCY(A1:A10,C1:C3)");
builder.SaveFile("csv", "%(csv)s");
builder.CloseFile();
'''


def main():
    for f in ('docbuilder', 'x2t', 'allfontsgen'):
        if not os.path.exists(os.path.join(BIN, f)):
            sys.exit('FAIL: %s not built in %s (set RD_CORE_BUILD)' % (f, BIN))
    overrides = {}
    if BASELINE:
        changed = git('diff', '--name-only', BASE_REF, '--', '.').decode().split()
        for rel in changed:
            try:
                overrides[rel] = git('show', '%s:%s' % (BASE_REF, rel))
            except subprocess.CalledProcessError:
                pass  # added since BASE_REF: not in the baseline build's configs either
    with tempfile.TemporaryDirectory(prefix='rd883-') as tmp:
        tree = os.path.join(tmp, 'sdkjs')
        shadow(tree, overrides)
        r = subprocess.run([sys.executable, os.path.join(tree, 'build', 'build.py'), '--product', 'cell', '--beta=false'],
                           capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-2000:], r.stderr[-2000:])
            sys.exit('FAIL: sdkjs build failed')
        fonts = os.path.join(tmp, 'fonts')
        os.makedirs(fonts)
        env = dict(os.environ, DYLD_FRAMEWORK_PATH=LIB)
        subprocess.run([os.path.join(BIN, 'allfontsgen'), '--use-system=1', '--allfonts=' + os.path.join(fonts, 'AllFonts.js'),
                        '--selection=' + os.path.join(fonts, 'font_selection.bin')], env=env, capture_output=True)
        # docbuilder looks for ../Frameworks, x2t and DoctRenderer.config next to itself
        app = os.path.join(tmp, 'app')
        os.makedirs(os.path.join(app, 'bin'))
        os.makedirs(os.path.join(app, 'editors', 'web-apps', 'vendor'))
        os.symlink(LIB, os.path.join(app, 'Frameworks'))
        shutil.copy2(os.path.join(BIN, 'docbuilder'), os.path.join(app, 'bin', 'docbuilder'))
        # x2t finds its frameworks through @executable_path/../Frameworks, so it must sit in app/bin (APFS clone)
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
        out = os.path.join(tmp, 'out.csv')
        js = os.path.join(tmp, 'freq.js')
        with open(js, 'w') as f:
            f.write(SCRIPT % {'xlsx': xlsx, 'csv': out})
        r = subprocess.run([os.path.join(app, 'bin', 'docbuilder'), js], cwd=tmp, capture_output=True, text=True, timeout=300)
        if not os.path.exists(out):
            print(r.stdout[-2000:], r.stderr[-2000:])
            sys.exit('FAIL: docbuilder produced no CSV')
        rows = list(csv.reader(open(out, encoding='utf-8-sig')))
    got_d = [rows[i][3] for i in range(4)]
    got_e = [rows[i][4] for i in range(4)]
    fails = 0
    for name, got, want, why in (
            ('FREQUENCY(1..10, {7;2;5})', got_d, ['2', '2', '3', '3'], 'counts must follow the bins\' order (7, 2, 5, rest)'),
            ('FREQUENCY(1..10, {3;"x";8})', got_e, ['3', '5', '2', '#N/A'], 'the text bin is ignored, not a 0 bin')):
        if got == want:
            print('ok   %s = %s' % (name, ','.join(got)))
        else:
            fails += 1
            print('FAIL %s = %s, Excel gives %s: %s' % (name, ','.join(got), ','.join(want), why))
    print('FAIL %d check(s)' % fails if fails else 'PASS #883 FREQUENCY bin order and text bins (docbuilder)')
    sys.exit(1 if fails else 0)


main()

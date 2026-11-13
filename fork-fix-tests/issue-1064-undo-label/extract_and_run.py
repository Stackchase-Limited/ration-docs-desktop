#!/usr/bin/env python3
"""
#1064 - list of undo steps: the smallest useful part - the editors can say WHAT
Undo would undo ("Undo: Typing", "Undo: Insert Rows").

Before: nothing in sdkjs gave a history point a readable name. Word/slide points
carry an internal description id (AscDFH.historydescription_*), and spreadsheet
points have none at all (243 of 244 Create_NewPoint calls pass nothing).
Now: common/HistoryCommon.js has an English label table for the common
description ids (typing, paste, delete, formatting, tables, pictures, slides,
...) and, for spreadsheets, names a point by its changes (AscCommonExcel undo
class + AscCH change type, the most telling one wins: Insert Rows over Entry
over Bold). baseEditorsApi.asc_getUndoLabel() (common/apiBase.js) returns the
label of the step Undo would revert, "Edit" for an unnamed step, null when
there is nothing to undo. web-apps shows it in the Undo tooltip only when the
user opts in (test: issue-1064-undo-label-ui-test.js).

End to end: the sdkjs tree under test (BASELINE=1: files changed since BASE_REF
taken from BASE_REF) is built with the fork's build (build/build.py --product
word --product cell) into a temp copy; core's docbuilder opens an empty xlsx and
an empty docx, turns history on (docbuilder runs with it off), makes edits the
way the editors do (a history point, then the change: the cell value, bold, an
inserted row; in the document a letter typed through StartAction with the
typing description, the api's Bold, then an action without a label) and asks asc_getUndoLabel
after each, including after an Undo. Results are written into the file and read
back from the saved copy.

NOT claimed: the GUI tooltip (needs a GUI check); presentation points use the
same table (shared CHistory with word) but are not run here.

  RD_REPO=<sdkjs checkout>           (default ../../sdkjs)
  RD_CORE_BUILD=<core build dir>     (default ../../core/build; needs bin/mac_arm64/{docbuilder,x2t})
  RD_WEBAPPS=<web-apps checkout>     (default ../../web-apps; only vendor/xregexp is used)
  RD_FONTS=<font cache dir>          (default ../../../.rd-work/fonts-cache; copied, never written)
  BASELINE=1                         use BASE_REF's version of the changed files; must FAIL
  BASE_REF                           default: parent of the #1064 commit
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
BASE_REF = os.environ.get('BASE_REF', 'cfc1f19761^')
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



def empty_docx(path):
    ct = 'application/vnd.openxmlformats-officedocument.wordprocessingml'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="%s.document.main+xml"/></Types>' % ct)
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/></Relationships>' % rel)
        z.writestr('word/document.xml', '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p/></w:body></w:document>')


PROBE = '''
var out = [];
function probe(tag) {
    var v;
    try { v = Asc.editor.asc_getUndoLabel(); } catch (e) { v = "ERR " + e.message; }
    out.push(tag + "=" + v);
}
'''

# a history point, then the change - as WorksheetView does for an edit
CELL = PROBE + '''
builder.OpenFile("%(xlsx)s");
var s = Api.GetActiveSheet();
probe("nothing");
while (!AscCommon.History.Is_On()) AscCommon.History.TurnOn();
AscCommon.History.Create_NewPoint();
s.GetRange("A1").SetValue(5);
probe("value");
AscCommon.History.Create_NewPoint();
s.GetRange("A2:A3").SetBold(true);
probe("bold");
AscCommon.History.Create_NewPoint();
s.worksheet.insertRowsBefore(1, 2);
probe("rows");
AscCommon.History.Undo();
probe("undone");
AscCommon.History.TurnOff();
s.GetRange("H1").SetValue("RESULT " + out.join(" ## "));
builder.SaveFile("xlsx", "%(xout)s");
builder.CloseFile();
'''

DOC = PROBE + '''
builder.OpenFile("%(docx)s");
var doc = Asc.editor.getLogicDocument();
probe("nothing");
while (!AscCommon.History.Is_On()) AscCommon.History.TurnOn();
doc.StartAction(AscDFH.historydescription_Document_AddLetter);
doc.AddToParagraph(new AscWord.CRunText(0x61));
doc.FinalizeAction();
probe("typed");
doc.SelectAll();
Asc.editor.put_TextPrBold(true);         // the toolbar's Bold button
probe("bold");
doc.StartAction(AscDFH.historydescription_Document_ApiBuilder);
doc.AddToParagraph(new AscCommonWord.ParaTextPr({Italic: true}));
doc.FinalizeAction();
probe("unnamed");
AscCommon.History.TurnOff();
Api.GetDocument().GetElement(0).AddText("RESULT " + out.join(" ## "));
builder.SaveFile("docx", "%(dout)s");
builder.CloseFile();
'''


def result(path, part):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        text = ''.join(z.read(n).decode('utf-8') for n in names if n == part)
    m = re.search(r'RESULT ([^<]*)', text)
    return dict(kv.split('=', 1) for kv in m.group(1).split(' ## ')) if m else {}


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
    with tempfile.TemporaryDirectory(prefix='rd1064-') as tmp:
        tree = os.path.join(tmp, 'sdkjs')
        shadow(tree, overrides)
        r = subprocess.run([sys.executable, os.path.join(tree, 'build', 'build.py'), '--product', 'cell', '--product', 'word', '--beta=false'],
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
        p = {'xlsx': os.path.join(tmp, 'empty.xlsx'), 'docx': os.path.join(tmp, 'empty.docx'),
             'xout': os.path.join(tmp, 'out.xlsx'), 'dout': os.path.join(tmp, 'out.docx')}
        empty_xlsx(p['xlsx'])
        empty_docx(p['docx'])
        for name, script, out in (('cell.js', CELL, p['xout']), ('doc.js', DOC, p['dout'])):
            js = os.path.join(tmp, name)
            with open(js, 'w') as f:
                f.write(script % p)
            r = subprocess.run([os.path.join(app, 'bin', 'docbuilder'), js], cwd=tmp, capture_output=True, text=True, timeout=300)
            if not os.path.exists(out):
                print(r.stdout[-2000:], r.stderr[-2000:])
                sys.exit('FAIL: docbuilder produced no %s' % os.path.basename(out))
        cell = result(p['xout'], 'xl/sharedStrings.xml')
        word = result(p['dout'], 'word/document.xml')
    checks = [
        ('cell: nothing to undo -> null', cell.get('nothing'), 'null'),
        ('cell: a typed value -> Entry', cell.get('value'), 'Entry'),
        ('cell: bold -> Bold', cell.get('bold'), 'Bold'),
        ('cell: insert rows -> Insert Rows', cell.get('rows'), 'Insert Rows'),
        ('cell: after Undo the previous step -> Bold', cell.get('undone'), 'Bold'),
        ('word: nothing to undo -> null', word.get('nothing'), 'null'),
        ('word: typing -> Typing', word.get('typed'), 'Typing'),
        ('word: the Bold button -> Bold', word.get('bold'), 'Bold'),
        ('word: a step without a label -> Edit', word.get('unnamed'), 'Edit'),
    ]
    fails = 0
    for name, got, want in checks:
        ok = got == want
        print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else ': got %r' % got))
        fails += 0 if ok else 1
    print('FAIL %d check(s)' % fails if fails else 'PASS #1064 asc_getUndoLabel names the step Undo reverts (docbuilder, cell + word)')
    sys.exit(1 if fails else 0)


main()

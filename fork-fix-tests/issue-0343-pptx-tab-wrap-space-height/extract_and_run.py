#!/usr/bin/env python3
"""
#343 - pptx: text placed differently from PowerPoint in the reporter's TD02_2019.pptm-3.pptx.

Reference: the deck carries the thumbnail PowerPoint saved with it (docProps/thumbnail.jpeg,
Application "Microsoft Office PowerPoint" 14.0). Against it two things differed:

1. "... « défaillant » <tab><tab><tab>Vrai <tab> Faux" wraps after the tabs. PowerPoint keeps the
   first tab on line 1 and carries the other two to line 2, so "Vrai" sits at the third default
   stop (229pt), level with the "Vrai" of the next paragraph. We put it at 157pt.
   Cause: Paragraph.private_RecalculateGetTabPos (sdkjs word/Editor/Paragraph_Recalculate.js)
   applies Word's rule (bug 32345): a default tab that starts inside the line but ends past the
   right edge is clamped to the edge and stays on the line. PowerPoint wraps it instead.
2. Headings "A l'examen" (18pt) end with a 28pt space; PowerPoint makes the line 28pt tall, so
   everything below sits 8-12pt lower per heading. ParaRun.Recalculate_LineMetrics
   (word/Editor/Run.js) skipped para_Space when sizing a line.
Fix: for DrawingML text (not bFromDocument, not the document editor) the clamp is not applied
and spaces count towards the line height. After it every line of that slide matches the
thumbnail within its 2.8pt pixel.

What this runs - REAL code: the sdkjs under test is built (slide product) and loaded by x2t's
doctrenderer, which lays out a generated one-slide deck and writes a PDF (pptx -> pdf, the
editor's layout engine). pdftotext -bbox gives each word's box. One text box, 18pt Arial, insets
7.2pt, default tab stops every 72pt from the inset:
  "Alpha" + 7 tabs + "Bravo": five tabs fit, the sixth would end past the right edge.
      PowerPoint: the sixth and seventh tabs wrap, "Bravo" at inset + 144pt on line 2.
      (old: the sixth was clamped to the edge and stayed on line 1, only the seventh wrapped,
      "Bravo" at inset + 72pt - the reporter's misaligned "Vrai")
  "Charlie" + a 40pt space, then "Delta", "Echo", "Foxtrot" (plain 18pt lines).
      Bravo->Delta spans the Charlie line, Delta->Foxtrot two plain lines: the first must be
      > 10pt larger (a 40pt line instead of an 18pt one; old: equal).
NOT claimed: Word documents (their behaviour is meant to be unchanged - not exercised here);
custom (non-default) tab stops past the edge; sheet shapes (same code path, not run); the
editor's cursor drawing.

Env: RD_SDKJS (default ../../sdkjs; copied and built into a temp dir), RD_X2T (default
../../core/build/bin/mac_arm64/x2t), RD_X2T_FRAMEWORKS, RD_FONTS, RD_WEBAPPS, RD_TMP, RD_KEEP=1,
PDFTOTEXT. BASELINE=1 builds sdkjs from `git archive BASE_REF` (default the commit before the
fix) - MUST FAIL. Exit 77 (skip) without x2t, fonts or pdftotext.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'issue-2002-media-trim'))
import media_c1 as h  # noqa: E402

BASELINE = bool(os.environ.get('BASELINE'))
BASE_REF = os.environ.get('BASE_REF', '11054e3e63^')
FMT_PDF = 513
PDFTOTEXT = os.environ.get('PDFTOTEXT') or shutil.which('pdftotext') or '/opt/homebrew/bin/pdftotext'

BOX_X = 1828800      # 144pt
BOX_CX = 5486400     # 432pt
INSET = 7.2


def run(text, sz=1800):
    return ('<a:r><a:rPr lang="en-US" sz="%d" dirty="0"><a:latin typeface="Arial"/></a:rPr><a:t>%s</a:t></a:r>'
            % (sz, text))


def para(*runs):
    return '<a:p><a:pPr defTabSz="914400"/>%s</a:p>' % ''.join(runs)


def make_deck(dst):
    body = (para(run('Alpha' + '\t' * 7 + 'Bravo'))
            + para(run('Charlie'), run(' ', 4000))
            + para(run('Delta'))
            + para(run('Echo'))
            + para(run('Foxtrot')))
    sp = ('<p:sp><p:nvSpPr><p:cNvPr id="6" name="box"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>'
          '<a:xfrm><a:off x="%d" y="914400"/><a:ext cx="%d" cy="4572000"/></a:xfrm>'
          '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody>'
          '<a:bodyPr wrap="square" lIns="91440" rIns="91440"/><a:lstStyle/>%s</p:txBody></p:sp>') % (BOX_X, BOX_CX, body)
    zin = zipfile.ZipFile(h.TEMPLATE)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == 'ppt/slides/slide1.xml':
                d = d.replace(b'</p:spTree>', sp.encode() + b'</p:spTree>', 1)
            zo.writestr(it, d)


def words(pdf):
    out = subprocess.run([PDFTOTEXT, '-bbox', pdf, '-'], capture_output=True, text=True, check=True).stdout
    return {w: (float(x), float(y)) for x, y, w in
            re.findall(r'<word xMin="([-\d.]+)" yMin="([-\d.]+)"[^>]*>([^<]+)</word>', out)}


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache'),
                    (PDFTOTEXT, 'pdftotext')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('x2t: %s%s' % (x2t, '  (BASELINE, sdkjs %s)' % BASE_REF if BASELINE else ''))
    tmp = tempfile.mkdtemp(prefix='issue0343-', dir=os.environ.get('RD_TMP'))
    names = ('Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot')
    try:
        tree = h.build_sdkjs(tmp, BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'in.pptx')
        make_deck(deck)
        pdf = os.path.join(tmp, 'out.pdf')
        h.convert(conv, deck, pdf, FMT_PDF)
        ws = words(pdf)
        print('words (x, yMin pt): %s' % ', '.join('%s=(%.2f, %.2f)' % ((k,) + ws[k]) if k in ws else '%s=-' % k for k in names))
        h.check(all(k in ws for k in names), 'all six words rendered')
        if all(k in ws for k in names):
            left = BOX_X / 12700.0 + INSET
            h.check(abs(ws['Alpha'][0] - left) < 1.0, 'Alpha starts at the inset (%.2f vs %.2f)' % (ws['Alpha'][0], left))
            h.check(ws['Bravo'][1] > ws['Alpha'][1] + 10, 'Bravo is on the line below Alpha')
            h.check(abs(ws['Bravo'][0] - (left + 144.0)) < 1.0,
                    'the tab that would end past the edge wraps: two tabs on line 2, Bravo at the second default stop '
                    '(Bravo - inset = %.2f pt, want 144)' % (ws['Bravo'][0] - left))
            big = ws['Delta'][1] - ws['Bravo'][1]
            ref = ws['Foxtrot'][1] - ws['Delta'][1]
            h.check(big - ref > 10.0,
                    'a 40pt space makes its line taller (Bravo->Delta %.2f pt vs Delta->Foxtrot %.2f pt)' % (big, ref))
    finally:
        if not os.environ.get('RD_KEEP'):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print('kept %s' % tmp)
    h.finish('#343 slide tabs past the right edge wrap and spaces count towards line height')


if __name__ == '__main__':
    main()

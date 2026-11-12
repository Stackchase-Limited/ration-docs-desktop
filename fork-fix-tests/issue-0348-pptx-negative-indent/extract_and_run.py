#!/usr/bin/env python3
"""
#348 - pptx: a paragraph with marL=0 and a negative indent started its first line LEFT of the
text box, so its first characters were drawn outside the shape (in the reporter's deck the
leading "•" and part of the first word fall off the slide).

PowerPoint does not do that. The reporter's Presentation1.pptx carries the thumbnail PowerPoint
saved with it (docProps/thumbnail.jpeg, Application "Microsoft Office PowerPoint"): its first
lines ("• The provenance of dust", indent=-385763 EMU = -30.4pt, marL=0) start at the box's
left inset, ~30pt right of where we put them; every other line matches. So PowerPoint clamps
the first line at the inset.

Cause: Paragraph.private_RecalculateLineFillRanges (sdkjs word/Editor/Paragraph_Recalculate.js)
starts the first line at XStart + Ind.Left + Ind.FirstLine with no lower bound. That is right
for Word (a hanging indent may go into the page margin) but not for DrawingML text. Fix: for
paragraphs outside the document editor (slides, sheet shapes) the first line starts no further
left than the text box inset (mirrored for right-to-left paragraphs).

What this runs - REAL code: the sdkjs under test is built (slide product) and loaded by x2t's
doctrenderer, which lays out a generated one-slide deck and writes a PDF (pptx -> pdf, the same
layout engine the editor uses). pdftotext -bbox gives each word's x. In one text box:
  "Alpha"  marL=0,      indent=-385763  (the reporter's case: must start at the inset)
  "Bravo"  marL=0,      no indent       (reference: the inset)
  "Charlie" marL=457200, indent=-228600 (a hanging indent inside the box: must stay at +18pt)
Checks: Alpha starts where Bravo does (within 1pt); Charlie still starts 18pt right of Bravo.
NOT claimed: right-to-left paragraphs (the mirrored clamp is not exercised here); the editor's
cursor/selection drawing (same Lines/Ranges, not driven here); whether PowerPoint also clamps
when marL > 0 and marL+indent < 0 (the thumbnail only shows marL=0) - we clamp there too.

Env: RD_SDKJS (default ../../sdkjs; copied and built into a temp dir), RD_X2T (default
../../core/build/bin/mac_arm64/x2t), RD_X2T_FRAMEWORKS, RD_FONTS, RD_WEBAPPS, RD_TMP, RD_KEEP=1,
PDFTOTEXT (default: pdftotext on PATH). BASELINE=1 builds sdkjs from `git archive BASE_REF`
(default the commit before the fix) - MUST FAIL. Exit 77 (skip) without x2t, fonts or pdftotext.
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
BASE_REF = os.environ.get('BASE_REF', 'b258d6e942^')
FMT_PDF = 513
PDFTOTEXT = os.environ.get('PDFTOTEXT') or shutil.which('pdftotext') or '/opt/homebrew/bin/pdftotext'


def para(text, ppr):
    return ('<a:p><a:pPr%s/><a:r><a:rPr lang="en-US" sz="2000" dirty="0"><a:latin typeface="Arial"/>'
            '</a:rPr><a:t>%s</a:t></a:r></a:p>' % (ppr, text))


def make_deck(dst):
    sp = ('<p:sp><p:nvSpPr><p:cNvPr id="6" name="box"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>'
          '<a:xfrm><a:off x="1828800" y="1828800"/><a:ext cx="5486400" cy="2743200"/></a:xfrm>'
          '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="91440"/>'
          '<a:lstStyle/>'
          + para('Alpha', ' indent="-385763"')
          + para('Bravo', '')
          + para('Charlie', ' marL="457200" indent="-228600"')
          + '</p:txBody></p:sp>')
    zin = zipfile.ZipFile(h.TEMPLATE)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == 'ppt/slides/slide1.xml':
                d = d.replace(b'</p:spTree>', sp.encode() + b'</p:spTree>', 1)
            zo.writestr(it, d)


def word_x(pdf):
    out = subprocess.run([PDFTOTEXT, '-bbox', pdf, '-'], capture_output=True, text=True, check=True).stdout
    return {w: float(x) for x, w in re.findall(r'<word xMin="([-\d.]+)"[^>]*>([^<]+)</word>', out)}


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache'),
                    (PDFTOTEXT, 'pdftotext')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('x2t: %s%s' % (x2t, '  (BASELINE, sdkjs %s)' % BASE_REF if BASELINE else ''))
    tmp = tempfile.mkdtemp(prefix='issue0348-', dir=os.environ.get('RD_TMP'))
    try:
        tree = h.build_sdkjs(tmp, BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'in.pptx')
        make_deck(deck)
        pdf = os.path.join(tmp, 'out.pdf')
        h.convert(conv, deck, pdf, FMT_PDF)
        xs = word_x(pdf)
        print('first word x (pt): %s' % ', '.join('%s=%.2f' % (k, xs.get(k, float('nan'))) for k in ('Alpha', 'Bravo', 'Charlie')))
        h.check(all(k in xs for k in ('Alpha', 'Bravo', 'Charlie')), 'all three paragraphs rendered')
        if all(k in xs for k in ('Alpha', 'Bravo', 'Charlie')):
            box_left = 1828800 / 12700.0
            h.check(xs['Bravo'] > box_left, 'reference line starts inside the box (%.2f > %.2f)' % (xs['Bravo'], box_left))
            h.check(abs(xs['Alpha'] - xs['Bravo']) < 1.0,
                    'marL=0 indent=-30.4pt: first line starts at the inset, not left of the box (Alpha - Bravo = %.2f pt)'
                    % (xs['Alpha'] - xs['Bravo']))
            h.check(abs(xs['Charlie'] - xs['Bravo'] - 18.0) < 1.0,
                    'hanging indent inside the box unchanged: first line at marL+indent = 18pt (Charlie - Bravo = %.2f pt)'
                    % (xs['Charlie'] - xs['Bravo']))
    finally:
        if not os.environ.get('RD_KEEP'):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print('kept %s' % tmp)
    h.finish('#348 pptx first line with marL=0 and a negative indent starts at the text box inset')


if __name__ == '__main__':
    main()

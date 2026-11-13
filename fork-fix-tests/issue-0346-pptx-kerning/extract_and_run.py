#!/usr/bin/env python3
"""
#346 - pptx: "FREE (LIQUID) FRESH WATER!" fits on one line in PowerPoint but wrapped in ours.

Reference: the reporter's Presentation2.pptx carries PowerPoint's own thumbnail
(docProps/thumbnail.jpeg, PowerPoint 14.0): one line. The text is 24pt Arial Bold in a box with
357.6pt of room; the deck's default text style (presentation.xml, master) has kern="1200", i.e.
pair kerning from 12pt up - PowerPoint's default. Unkerned the line is 358.64pt (wraps), kerned
355.54pt (W-A and A-T pairs; fits).

Cause: sdkjs dropped kern entirely - the PPTY reader skipped rPr attribute 8
(common/Shapes/Serialize.js "s.Skip2(4); // kern"), CTextPr had no field for it, the paragraph
shaper (word/Editor/Paragraph/TextShaper.js) never set HarfBuzz's 'kern' feature bit, and the
PPTY writer (common/Shapes/SerializeWriter.js) never wrote it - so every save also stripped all
kern attributes from the deck, after which PowerPoint wrapped the line as well.
Fix: CTextPr.Kern read/written in PPTY and carried like the other run properties (also in
CTextPr.Write_ToBinary, which is the key of the compiled text-property cache - without it a
kern="0" run shared the cached, kerned properties of a kern="1200" one: check B below); the
shaper enables kerning for runs at or above that size (kern="0" stays off).

What this runs - REAL code: the sdkjs under test is built (slide product) and loaded by x2t's
doctrenderer.
 1. Layout (pptx -> pdf): three text boxes 4724400 EMU wide (default insets), each one run of
    "FREE (LIQUID) FRESH WATER!" in 24pt Arial Bold:
      A  kern="1200" on the run        -> must be ONE line (old: two)
      B  kern="0" on the run (off)     -> must stay TWO lines (control: unkerned text does wrap)
      C  no kern on the run, inherits the template's default kern="1200" -> ONE line (old: two)
    pdftotext -bbox: "WATER!" on the same line as "FREE" or below it.
 2. Save (the desktop save path: pptx -> Editor.bin, then x2t replays a changes file through
    sdkjs and writes pptx from the sdkjs model): kern="1200" and kern="0" on the slide's runs and
    the 9 + 19 kern attributes of the template's presentation.xml and master must survive
    (old: all removed).
NOT claimed (checked by hand in headless Chromium with the real slide editor, not here): the
editor's WASM shaper (Presentation2: one line, 125.42mm, with the fix; two lines without) and
run-level kern on a duplicated slide surviving the desktop save (3 of 3 kept; 0 before).
Also not claimed: whether PowerPoint kerns across a space; mixed-version co-editing (an older
sdkjs reading a Kern-carrying CTextPr change would misread it).

Env: RD_SDKJS (default ../../sdkjs; copied and built into a temp dir), RD_X2T, RD_X2T_FRAMEWORKS,
RD_FONTS (fonts cache with Arial Bold), RD_WEBAPPS, RD_TMP, RD_KEEP=1, PDFTOTEXT. BASELINE=1 builds
sdkjs from `git archive BASE_REF` (default the commit before the fix) - MUST FAIL.
Exit 77 (skip) without x2t, fonts or pdftotext.
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
BASE_REF = os.environ.get('BASE_REF', '37ea3d91f9^')
FMT_PDF = 513
PDFTOTEXT = os.environ.get('PDFTOTEXT') or shutil.which('pdftotext') or '/opt/homebrew/bin/pdftotext'
TEXT = 'FREE (LIQUID) FRESH WATER!'


def box(spid, y, label, kern):
    k = '' if kern is None else ' kern="%s"' % kern
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="%s"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>'
            '<a:xfrm><a:off x="914400" y="%d"/><a:ext cx="4724400" cy="461665"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>'
            '<a:p><a:r><a:rPr lang="en-US" sz="2400" b="1"%s dirty="0"><a:latin typeface="Arial"/></a:rPr>'
            '<a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>') % (spid, label, y, k, TEXT)


def make_deck(dst):
    sps = box(10, 457200, 'Aa', '1200') + box(11, 2286000, 'Bb', '0') + box(12, 4114800, 'Cc', None)
    zin = zipfile.ZipFile(h.TEMPLATE)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == 'ppt/slides/slide1.xml':
                d = d.replace(b'</p:spTree>', sps.encode() + b'</p:spTree>', 1)
            zo.writestr(it, d)


def lines(pdf):
    """box label -> (y of its "FREE", y of its "WATER!"); boxes A, B, C are stacked top to bottom"""
    out = subprocess.run([PDFTOTEXT, '-bbox', pdf, '-'], capture_output=True, text=True, check=True).stdout
    ws = re.findall(r'<word xMin="([-\d.]+)" yMin="([-\d.]+)"[^>]*>([^<]+)</word>', out)
    free = sorted(float(y) for x, y, w in ws if w == 'FREE')
    water = sorted(float(y) for x, y, w in ws if w == 'WATER!')
    if len(free) != 3 or len(water) != 3:
        return {}
    return dict(zip(('Aa', 'Bb', 'Cc'), zip(free, water)))


def kerns(pptx):
    z = zipfile.ZipFile(pptx)
    out = {}
    for n in ('ppt/presentation.xml', 'ppt/slideMasters/slideMaster1.xml', 'ppt/slides/slide1.xml'):
        x = z.read(n).decode('utf-8')
        out[n] = (len(re.findall(r'kern="1200"', x)), len(re.findall(r'kern="0"', x)))
    return out


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache'),
                    (PDFTOTEXT, 'pdftotext')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('x2t: %s%s' % (x2t, '  (BASELINE, sdkjs %s)' % BASE_REF if BASELINE else ''))
    tmp = tempfile.mkdtemp(prefix='issue0346-', dir=os.environ.get('RD_TMP'))
    try:
        tree = h.build_sdkjs(tmp, BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'in.pptx')
        make_deck(deck)
        before = kerns(deck)

        pdf = os.path.join(tmp, 'out.pdf')
        h.convert(conv, deck, pdf, FMT_PDF)
        ls = lines(pdf)
        print('label y / WATER! y: %s' % ls)
        one = lambda k: k in ls and ls[k][1] is not None and abs(ls[k][1] - ls[k][0]) < 1.0
        two = lambda k: k in ls and ls[k][1] is not None and ls[k][1] - ls[k][0] > 10.0
        h.check(one('Aa'), 'A kern="1200": the kerned line fits, WATER! stays on the first line')
        h.check(two('Bb'), 'B kern="0" (control): the unkerned line does not fit, WATER! wraps')
        h.check(one('Cc'), 'C no kern on the run: inherits the default kern="1200" and fits on one line')

        bd = h.deck_to_bin(conv, tmp, deck, 'bin')
        ch = os.path.join(tmp, 'changes0.json')
        open(ch, 'w').close()
        saved = h.save_with_changes(conv, tmp, bd, ch, 'save')
        after = kerns(saved)
        print('kern="1200"/kern="0" counts before: %s' % before)
        print('                           after save: %s' % after)
        h.check(after == before, 'saving through sdkjs keeps every kern attribute (slide runs, presentation defaults, master)')
    finally:
        if not os.environ.get('RD_KEEP'):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print('kept %s' % tmp)
    h.finish('#346 slide text is kerned per a:rPr kern and kern survives saving')


if __name__ == '__main__':
    main()

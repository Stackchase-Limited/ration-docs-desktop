#!/usr/bin/env python3
"""
#2484 - a picture's transparent colour (PowerPoint: Picture Format > Color > Set Transparent Color).

PowerPoint stores it as <a:clrChange><a:clrFrom>colour</a:clrFrom><a:clrTo>colour + alpha 0</a:clrTo>
</a:clrChange> in the picture's <a:blip>. sdkjs and x2t kept it (CClrChange, Format.js), but nothing
drew it: the editors drew the picture with that colour opaque (a white picture background stayed
white over a coloured slide).

Fix (sdkjs canvas path; honours what the file says, no option): CShapeDrawer.drawBlipFill hands the
canvas graphics a copy of the picture with every clrFrom pixel turned into clrTo
(getClrChangeImage, word/Drawing/ShapeDrawer.js), made once per image and colours (WeakMap cache).

What this runs (REAL code): x2t makes Editor.bin from a one-slide deck (black background) with two
copies of a 20x10 PNG, left half white, right half blue: the upper one with
<a:clrChange> white -> white alpha 0, the lower one without. The real slide editor (headless
Chromium) draws the slide with its own canvas graphics (CGraphics + DrawPage, as the thumbnails and
the slide view do) and the test reads pixels:
  - upper picture, white half: the black background shows through (the fix);
  - upper picture, blue half: still blue (only the transparent colour changes);
  - lower picture, white half: still white (a picture without clrChange is unchanged);
  - background: black.
NOT claimed: PDF export and printing (core's renderer, not this path - still opaque), the editor's
own UI for setting the colour (there is none), JPEG pictures whose "white" is not exactly the colour
(PowerPoint's matching tolerance is not known; exact match here).

Env: RD_SDKJS, RD_X2T, RD_FONTS (a COPY of the fonts cache: x2t may rewrite AllFonts.js), RD_TMP,
RD_PLAYWRIGHT, RD_CHROME. BASELINE=1 builds SDKJS_BASE_REF (the parent of the fix) and MUST FAIL.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'issue-2002-media-trim'))
import media_c1 as h  # noqa: E402

BASELINE = bool(os.environ.get('BASELINE'))
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '1fccd3ade2^')

PIC_W, PIC_H = 20, 10
X0, Y0, CX, CY = 1000000, 1000000, 4000000, 2000000
Y1 = 3500000


def png_half_white_blue():
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    rows = b''
    for _ in range(PIC_H):
        rows += b'\x00' + b'\xff\xff\xff' * (PIC_W // 2) + b'\x00\x00\xff' * (PIC_W // 2)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', PIC_W, PIC_H, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def pic(pid, y, clr_change):
    blip_inner = ('<a:clrChange><a:clrFrom><a:srgbClr val="FFFFFF"/></a:clrFrom><a:clrTo><a:srgbClr val="FFFFFF">'
                  '<a:alpha val="0"/></a:srgbClr></a:clrTo></a:clrChange>') if clr_change else ''
    return ('<p:pic><p:nvPicPr><p:cNvPr id="%d" name="pic%d"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            '<p:blipFill><a:blip r:embed="rId20">%s</a:blip><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            '<p:spPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
            % (pid, pid, blip_inner, X0, y, CX, CY))


def make_deck(dst):
    zin = zipfile.ZipFile(h.TEMPLATE)
    size = re.search(rb'<p:sldSz cx="(\d+)" cy="(\d+)"', zin.read('ppt/presentation.xml'))
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == 'ppt/slides/slide1.xml':
                d = re.sub(rb'<p:spTree>.*</p:spTree>', lambda m: (
                    '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
                    + pic(4, Y0, True) + pic(5, Y1, False) + '</p:spTree>').encode(), d, flags=re.S)
                d = d.replace(b'<p:cSld>', b'<p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="000000"/></a:solidFill>'
                              b'<a:effectLst/></p:bgPr></p:bg>', 1)
            elif it.filename == 'ppt/slides/_rels/slide1.xml.rels':
                d = d.replace(b'</Relationships>', b'<Relationship Id="rId20" Type="http://schemas.openxmlformats.org/'
                              b'officeDocument/2006/relationships/image" Target="../media/image20.png"/></Relationships>', 1)
            elif it.filename == '[Content_Types].xml' and b'Extension="png"' not in d:
                d = d.replace(b'</Types>', b'<Default Extension="png" ContentType="image/png"/></Types>', 1)
            zo.writestr(it, d)
        zo.writestr('ppt/media/image20.png', png_half_white_blue())
    return int(size.group(1)), int(size.group(2))


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('BASELINE (%s)' % SDKJS_BASE_REF if BASELINE else 'tree under test')
    tmp = tempfile.mkdtemp(prefix='issue2484-', dir=os.environ.get('RD_TMP'))
    try:
        tree = h.build_sdkjs(tmp, SDKJS_BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'clr.pptx')
        sw, sh = make_deck(deck)
        b = h.deck_to_bin(conv, tmp, deck, 'b')
        k = 400.0 / sw

        def pt(x_frac, y_emu):
            return [int((X0 + CX * x_frac) * k), int((y_emu + CY / 2) * k)]
        points = [pt(0.25, Y0), pt(0.75, Y0), pt(0.25, Y1), pt(0.75, Y1), [int(10500000 * k), int(500000 * k)]]
        r = subprocess.run(['node', os.path.join(HERE, 'render.js'), tree, b, os.path.join(h.FONTS, 'AllFonts.js'), json.dumps(points)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise SystemExit('render failed:\n' + r.stdout[-2000:] + r.stderr[-2000:])
        res = json.loads(r.stdout.strip().splitlines()[-1])
        px = res['px']
        print('image loaded %s, effects %s, pixels (upper white, upper blue, lower white, lower blue, background): %s, errors %s'
              % (res['imageLoaded'], res['effects'], px, res['errors']))
        h.check(res['imageLoaded'], 'the picture is loaded in the editor')

        def near(a, rgb):
            return all(abs(a[i] - rgb[i]) <= 24 for i in range(3))
        h.check(near(px[4], (0, 0, 0)), 'the slide background is black')
        h.check(near(px[0], (0, 0, 0)), 'picture with clrChange white -> transparent: its white shows the black background')
        h.check(near(px[1], (0, 0, 255)), 'its blue half stays blue')
        h.check(near(px[2], (255, 255, 255)), 'the same picture without clrChange stays white')
        h.check(near(px[3], (0, 0, 255)), 'and blue')
    finally:
        if not os.environ.get('KEEP_TMP'):
            shutil.rmtree(tmp, ignore_errors=True)
    h.finish('#2484 a picture\'s transparent colour (a:clrChange) is drawn')


if __name__ == '__main__':
    main()

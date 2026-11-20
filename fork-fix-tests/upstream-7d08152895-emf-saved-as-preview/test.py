#!/usr/bin/env python3
"""
Upstream 7d08152895, backported for 2026.3.1 (adapted: upstream's `false == bDownload &&` term
dropped - it comes from upstream ee7185f148, which we do not have):
an EMF/WMF picture was saved as its display preview and the vector original was lost.

Opening a docx, x2t keeps an EMF picture as media/display2image1.emf next to the preview
display2image1.svg (or .png when it cannot make an SVG) that the editor draws. When the document
refers to the picture by that preview, saving it back
(CImageManager2::GenerateImage, OOXML/Binary/Presentation/BinaryFileReaderWriter.cpp) swapped
in the original metafile only for pictures that also had additional files (OLE objects, media).
An ordinary picture was written to the docx as the preview: word/media/image1.svg plus a PNG
fallback, and the EMF was gone.

What runs - the REAL x2t, both directions:
  1. a docx with one EMF picture (generated here: a 100x100 EMF with a rectangle) -> Editor.bin
     (x2t writes media/display2image1.emf + display2image1.svg; Editor.bin names the .emf);
  2. control: that Editor.bin -> docx. The EMF comes back (before and after the fix).
  3. the same Editor.bin with its picture reference switched to the preview the editor draws,
     "display2image1.svg" (same length, UTF-16 in place) -> docx.
     Fixed: word/media holds the original EMF, byte for byte, and no .svg/.png.
     2026.3.0: the docx carries the SVG preview (+ PNG) and no EMF  -> FAIL.
NOT claimed: which editor actions make the editor send the preview name (step 3 models that
reference rather than driving the editor); pptx/xlsx (same function, not run); WMF (the
display1 branch, same code).

  RD_X2T=<x2t>         (default ../../core/build/bin/mac_arm64/x2t; frameworks beside it or in
                        ../../core/build/lib/mac_arm64, or RD_X2T_LIBS)
  BASELINE=1           use RD_X2T_BASE (default .rd-work/mac-2026.3.0/payload/converter/x2t,
                        v2026.3.0 = aa16ec2c0d); must FAIL
  RD_FONTS             font cache (default .rd-work/fonts-cache; copied first)
Exit 77 (skip) without x2t or fonts.
"""
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
RDWORK = os.path.normpath(os.path.join(ROOT, '..', '.rd-work'))
BASELINE = bool(os.environ.get('BASELINE'))
X2T = (os.environ.get('RD_X2T_BASE') or os.path.join(RDWORK, 'mac-2026.3.0', 'payload', 'converter', 'x2t')) if BASELINE \
    else (os.environ.get('RD_X2T') or os.path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64', 'x2t'))
FONTS = os.environ.get('RD_FONTS') or os.path.join(RDWORK, 'fonts-cache')
FMT_DOCX, FMT_DOCT_BIN = 65, 8193

failures = []


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def libs():
    if os.environ.get('RD_X2T_LIBS'):
        return os.environ['RD_X2T_LIBS']
    d = os.path.dirname(X2T)
    if os.path.isdir(os.path.join(d, 'kernel.framework')):
        return d
    return os.path.normpath(os.path.join(d, '..', '..', 'lib', 'mac_arm64'))


def emf():
    rect = struct.pack('<II4i', 43, 24, 10, 10, 90, 90)                    # EMR_RECTANGLE
    eof = struct.pack('<IIIII', 14, 20, 0, 16, 20)                         # EMR_EOF
    total = 108 + len(rect) + len(eof)
    hdr = struct.pack('<II4i4iIIIIHHIII2i2iIII2i', 1, 108, 0, 0, 99, 99, 0, 0, 2645, 2645, 0x464D4520, 0x10000,
                      total, 3, 1, 0, 0, 0, 0, 1024, 768, 320, 240, 0, 0, 0, 320000, 240000)
    return hdr + rect + eof


def make_docx(path, data):
    R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="%s" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
           'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
           '<w:body><w:p><w:r><w:t>Before</w:t></w:r><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
           '<wp:extent cx="952200" cy="952200"/><wp:docPr id="1" name="Picture 1"/><a:graphic>'
           '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr>'
           '<pic:cNvPr id="1" name="image1.emf"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rId9"/>'
           '<a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="952200" cy="952200"/>'
           '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
           '</wp:inline></w:drawing></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>') % R
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/><Default Extension="emf" ContentType="image/x-emf"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="%s/officeDocument" Target="word/document.xml"/></Relationships>' % R)
        z.writestr('word/_rels/document.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId9" Type="%s/image" Target="media/image1.emf"/></Relationships>' % R)
        z.writestr('word/document.xml', doc)
        z.writestr('word/media/image1.emf', data)


def x2t(src, dst, fmt, work, fonts):
    td = tempfile.mkdtemp(dir=work)
    p = os.path.join(td, 'params.xml')
    open(p, 'w').write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo>'
                       '<m_nFormatTo>%d</m_nFormatTo><m_sFontDir>%s</m_sFontDir><m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath>'
                       '<m_sTempDir>%s</m_sTempDir></TaskQueueDataConvert>' % (src, dst, fmt, fonts, fonts, td))
    l = libs()
    r = subprocess.run([X2T, p], capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, DYLD_FRAMEWORK_PATH=l, DYLD_LIBRARY_PATH=l))
    if r.returncode or not os.path.exists(dst):
        sys.exit('x2t failed (%d) -> %s\n%s%s' % (r.returncode, dst, r.stdout[-800:], r.stderr[-800:]))


def media(docx):
    with zipfile.ZipFile(docx) as z:
        rels = z.read('word/_rels/document.xml.rels').decode('utf-8', 'replace')
        return {n: hashlib.sha1(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('word/media/')}, rels


def main():
    for p, what in ((X2T, 'x2t'), (os.path.join(FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('x2t: %s%s' % (X2T, '  (BASELINE)' if BASELINE else ''))
    work = tempfile.mkdtemp(prefix='up7d0815-')
    try:
        fonts = os.path.join(work, 'fonts')
        shutil.copytree(FONTS, fonts)
        data = emf()
        want = hashlib.sha1(data).hexdigest()
        src = os.path.join(work, 'in.docx')
        make_docx(src, data)
        opened = os.path.join(work, 'opened')
        os.makedirs(opened)
        x2t(src, os.path.join(opened, 'Editor.bin'), FMT_DOCT_BIN, work, fonts)
        print('opened media: %s' % sorted(os.listdir(os.path.join(opened, 'media'))))

        # control: Editor.bin as x2t wrote it (names display2image1.emf)
        ctl = os.path.join(work, 'control.docx')
        x2t(os.path.join(opened, 'Editor.bin'), ctl, FMT_DOCX, work, fonts)
        m, _ = media(ctl)
        print('control save: %s' % sorted(m))
        check(want in m.values(), 'control: Editor.bin naming the .emf saves the EMF back')

        # the picture referred to by its display preview
        pv = os.path.join(work, 'preview')
        shutil.copytree(opened, pv)
        binp = os.path.join(pv, 'Editor.bin')
        b = open(binp, 'rb').read()
        old, new = 'display2image1.emf'.encode('utf-16-le'), 'display2image1.svg'.encode('utf-16-le')
        if b.count(old) != 1:
            sys.exit('Editor.bin does not name display2image1.emf once (%d) - the test needs updating' % b.count(old))
        open(binp, 'wb').write(b.replace(old, new))
        out = os.path.join(work, 'saved.docx')
        x2t(binp, out, FMT_DOCX, work, fonts)
        m, rels = media(out)
        print('preview save: %s' % sorted(m))
        check(want in m.values(), 'picture named by its SVG preview is saved as the original EMF, byte for byte')
        check(not any(n.endswith(('.svg', '.png')) for n in m), 'no SVG/PNG preview stored in place of the EMF')
        check('.emf"' in rels, 'the picture relationship targets the .emf')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print('FAIL: %d check(s) failed' % len(failures))
        sys.exit(1)
    print('PASS: upstream 7d08152895 EMF pictures keep their vector original on save')


if __name__ == '__main__':
    main()

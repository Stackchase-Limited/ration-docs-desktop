#!/usr/bin/env python3
r"""End-to-end demonstration of ONLYOFFICE/DesktopEditors#139 with the real x2t.

There is no way to hand a .pptx a control character - the character is illegal
in XML, so it cannot exist in a valid input file. It gets into the editor by
being pasted, which means it reaches the converter in the editor's own .bin
serialisation. So that is what this builds:

  sample.pptx --x2t--> .bin        the editor opening a presentation
  patch one code unit in the .bin  the user pasting U+0008 into a run
  .bin --x2t--> .pptx              THE SAVE - this is where the bug is
  .pptx --x2t--> .bin              the reopen

and then asks two questions of the saved .pptx: is every XML part well-formed,
and does the reopened .bin still contain the text that was on the slide.

A second case covers the same defect one part over: ppt/commentAuthors.xml
wrote a comment author's `initials` raw while writing the sibling `name`
escaped, so an author with '&' in their initials produced a part that does not
parse and every comment author was lost. That one needs no .bin detour - a
plain .pptx can carry it - so it is driven straight through x2t.

Before the fix the saved slide1.xml is not well-formed and the reopen loses
every run on the slide, roughly 74 KB of content, not just the pasted
character. After it, the file is clean and nothing is lost.

  ./e2e.py                    use core/build/bin/<plat>/x2t
  RD_X2T=/path/to/old/x2t ./e2e.py    run the same check against another build

Requires a built x2t. Skips (exit 77) if there is none.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.dom.minidom
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SAMPLE = os.path.join(ROOT, 'document-templates', 'sample', 'sample.pptx')
MARK = 'HEAD_MARKER_ALPHA@@TAIL_MARKER_OMEGA'
FMT_PPTX = 129
FMT_BIN_SLIDE = 8195


def find_x2t():
    if os.environ.get('RD_X2T'):
        return os.environ['RD_X2T']
    for plat in ('mac_arm64', 'mac_64', 'linux_64'):
        p = os.path.join(ROOT, 'core', 'build', 'bin', plat, 'x2t')
        if os.path.isfile(p):
            return p
    for app in ('desktop-apps/build/Ration Docs.app', ):
        p = os.path.join(ROOT, app, 'Contents/Resources/converter/x2t')
        if os.path.isfile(p):
            return p
    return None


def find_frameworks():
    """x2t in core/build/bin is not self-contained; it resolves its frameworks
    by @rpath out of the app bundle's converter directory."""
    for c in (os.path.join(ROOT, 'desktop-apps/build/Ration Docs.app/Contents/Resources/converter'),
              os.path.join(ROOT, 'core', 'build', 'lib', 'mac_arm64')):
        if os.path.isdir(c):
            return c
    return None


def find_fonts():
    base = os.path.expanduser('~/Library/Application Support')
    for bid in ('com.stackchase.rationdocs', 'com.onlyoffice.desktopeditors'):
        p = os.path.join(base, bid, 'data', 'fonts')
        if os.path.isdir(p):
            return p
    return ''


X2T = find_x2t()
if not X2T:
    sys.stderr.write('no x2t built - skipping (build core, see build_tools/MACOS_ARM64_DESKTOP_BUILD.md)\n')
    sys.exit(77)
FW = find_frameworks()
FONTS = find_fonts()
TMP = tempfile.mkdtemp(prefix='issue139-')


def convert(src, dst, fmt):
    params = os.path.join(TMP, 'params.xml')
    with open(params, 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert>'
                 '<m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo>'
                 '<m_nFormatTo>%d</m_nFormatTo><m_sFontDir>%s</m_sFontDir>'
                 '</TaskQueueDataConvert>' % (src, dst, fmt, FONTS))
    env = dict(os.environ)
    if FW:
        env['DYLD_FRAMEWORK_PATH'] = FW
        env['DYLD_LIBRARY_PATH'] = FW
        env['LD_LIBRARY_PATH'] = FW
    r = subprocess.run([X2T, params], capture_output=True, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit('x2t failed (%d) converting %s -> format %d\n%s%s'
                         % (r.returncode, os.path.basename(src), fmt, r.stdout, r.stderr))


def seed_pptx(path):
    zin = zipfile.ZipFile(SAMPLE)
    old = None
    for name in zin.namelist():
        if name == 'ppt/slides/slide1.xml':
            body = zin.read(name).decode('utf-8')
            start = body.find('<a:t>')
            end = body.find('</a:t>', start)
            old = body[start:end + len('</a:t>')]
            break
    if old is None:
        raise SystemExit('no <a:t> run found in the sample presentation')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == 'ppt/slides/slide1.xml':
                data = data.replace(old.encode('utf-8'),
                                    ('<a:t>%s</a:t>' % MARK).encode('utf-8'), 1)
            zo.writestr(item, data)


def paste_control_char(src_bin, dst_bin, code):
    """The editor holds run text as UTF-16; replace one placeholder code unit,
    which is exactly what pasting the character into that run would produce."""
    data = bytearray(open(src_bin, 'rb').read())
    at = data.find(MARK.encode('utf-16-le'))
    if at < 0:
        raise SystemExit('marker run not found in the .bin')
    at += len('HEAD_MARKER_ALPHA') * 2
    assert data[at:at + 2] == b'@\x00', data[at:at + 2]
    data[at:at + 2] = bytes([code & 0xFF, code >> 8])
    open(dst_bin, 'wb').write(data)


def malformed_parts(pptx):
    bad = []
    z = zipfile.ZipFile(pptx)
    for name in z.namelist():
        if not (name.endswith('.xml') or name.endswith('.rels')):
            continue
        try:
            xml.dom.minidom.parseString(z.read(name))
        except Exception as exc:
            bad.append('%s: %s' % (name, exc))
    return bad


def present(path_bin, text):
    return open(path_bin, 'rb').read().find(text.encode('utf-16-le')) >= 0


AUTHORS_PART = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<p:cmAuthorLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    ' xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
    # The escaped forms below are what sits in the FILE; the parsed values are
    # 'Ampersand & Co' and 'A&C'. '<' is in there too because writing it raw
    # opens a bogus element rather than merely an undefined entity.
    '<p:cmAuthor id="1" name="Ampersand &amp; Co" initials="A&amp;&lt;C" lastIdx="1" clrIdx="0"/>'
    '</p:cmAuthorLst>')


def seed_pptx_with_author(path):
    """Same sample presentation plus one comment author whose initials contain
    a character that has to be escaped."""
    import re
    zin = zipfile.ZipFile(SAMPLE)
    rels = zin.read('ppt/_rels/presentation.xml.rels').decode('utf-8')
    used = [int(m) for m in re.findall(r'Id="rId(\d+)"', rels)]
    rid = 'rId%d' % (max(used) + 1)
    rels = rels.replace('</Relationships>',
        '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/commentAuthors" Target="commentAuthors.xml"/>'
        '</Relationships>' % rid)
    types = zin.read('[Content_Types].xml').decode('utf-8').replace('</Types>',
        '<Override PartName="/ppt/commentAuthors.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.presentationml.commentAuthors+xml"/></Types>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zo:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == 'ppt/_rels/presentation.xml.rels':
                data = rels.encode('utf-8')
            elif item.filename == '[Content_Types].xml':
                data = types.encode('utf-8')
            zo.writestr(item, data)
        zo.writestr('ppt/commentAuthors.xml', AUTHORS_PART)


def main():
    print('x2t: %s' % X2T)
    p = lambda n: os.path.join(TMP, n)

    seed_pptx(p('seed.pptx'))
    convert(p('seed.pptx'), p('opened.bin'), FMT_BIN_SLIDE)
    paste_control_char(p('opened.bin'), p('pasted.bin'), 0x0008)

    # THE SAVE
    convert(p('pasted.bin'), p('saved.pptx'), FMT_PPTX)
    # THE REOPEN
    convert(p('saved.pptx'), p('reopened.bin'), FMT_BIN_SLIDE)
    # Control: the same round trip with no control character in it.
    convert(p('opened.bin'), p('control.pptx'), FMT_PPTX)
    convert(p('control.pptx'), p('control.bin'), FMT_BIN_SLIDE)

    failures = 0

    bad = malformed_parts(p('saved.pptx'))
    if bad:
        print('FAIL  the saved .pptx is not well-formed XML:')
        for b in bad:
            print('        %s' % b)
        failures += 1
    else:
        print('ok    every XML part of the saved .pptx is well-formed')

    probes = ['HEAD_MARKER_ALPHA', 'TAIL_MARKER_OMEGA', 'Here you can find', 'Your Logo']
    lost = [t for t in probes if not present(p('reopened.bin'), t)]
    if lost:
        print('FAIL  content lost after save/close/open: %s' % ', '.join(lost))
        failures += 1
    else:
        print('ok    all slide text survives save/close/open')

    a, b = os.path.getsize(p('control.bin')), os.path.getsize(p('reopened.bin'))
    print('      reopened %d bytes, control (no control char) %d bytes, delta %+d' % (b, a, b - a))
    if b != a:
        print('FAIL  the pasted character changed how much content survived')
        failures += 1

    # Second case: comment author initials.
    seed_pptx_with_author(p('authors.pptx'))
    convert(p('authors.pptx'), p('authors.bin'), FMT_BIN_SLIDE)
    convert(p('authors.bin'), p('authors_saved.pptx'), FMT_PPTX)
    z = zipfile.ZipFile(p('authors_saved.pptx'))
    if 'ppt/commentAuthors.xml' not in z.namelist():
        print('FAIL  the comment authors part did not survive the round trip')
        failures += 1
    else:
        part = z.read('ppt/commentAuthors.xml')
        try:
            xml.dom.minidom.parseString(part)
            print('ok    ppt/commentAuthors.xml is well-formed with \'&\' in initials')
        except Exception as exc:
            print('FAIL  ppt/commentAuthors.xml is not well-formed: %s' % exc)
            print('        %s' % part.decode('utf-8', 'replace')[-220:])
            failures += 1

    if failures:
        print('\n%d failure(s) - ONLYOFFICE/DesktopEditors#139' % failures)
        return 1
    print('\nall checks passed')
    return 0


try:
    sys.exit(main())
finally:
    shutil.rmtree(TMP, ignore_errors=True)

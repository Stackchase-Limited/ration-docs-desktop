#!/usr/bin/env python3
"""
#2002 - DATA LOSS: a video's trim (Trim Video start/end) was lost on save.

PowerPoint stores the trim as <p14:media r:embed=".."><p14:trim st="2500.5"
end="31000"/></p14:media> (ms cut from the start / from the end, [MS-PPTX]
2.3.3.18 CT_MediaTrim) in the video's nvPr extLst.
  - core Ext::toXmlWriter wrote p14:media without its p14:trim, so even a plain
    pptx -> Editor.bin -> pptx in x2t dropped it; Ext::toPPTY wrote st/end as
    fixed-point LONGs (x100000) that clamp at ~21.4 s; NvPr::fromPPTY skipped the
    extLst record (core, OOXML/PPTXFormat/Logic/ExtP.cpp, NvPr.cpp, Pic.cpp).
  - sdkjs ReadNvPr skipped the extLst record, so the model never had the trim and
    every save from the editor wrote the video untrimmed (common/Shapes/
    Serialize.js, SerializeWriter.js, common/Drawings/Format/Format.js UniMedia).

What this runs - all REAL code, no stubs of the code under test:
  1. x2t: a one-slide deck with a trimmed video (st 2500.5 ms, end 31000 ms: more
     than 21.4 s on purpose) -> Editor.bin -> pptx. The saved slide must carry
     <p14:trim st="2500.5" end="31000"/>.
  2. x2t + the sdkjs under test in its doctrenderer (the desktop's save path:
     Editor.bin + changes/ -> sdkjs opens, applies, writes -> core writes pptx),
     with an empty change set: the trim must survive the sdkjs read + write.
  3. The real slide editor (sdkjs under test, headless Chromium, stubbed desktop
     host): open that Editor.bin - the video must have trimSt/trimEnd; duplicate
     the slide (copies the video through the change binary) and move the original
     video; save. Those changes, written as the desktop writes changes0.json, are
     replayed by x2t: both slides' videos must keep the trim and the move must
     land.
NOT claimed: PowerPoint opening the saved file (the XML is what PowerPoint itself
writes); the players honouring the trim (issue-2002-trim-playback); docx (wp15) media.

Shared harness: media_c1.py (also used by issue-2002-trim-playback, issue-2005-*, issue-2006-*).
Env:
  RD_SDKJS (sdkjs tree, default ../../sdkjs; copied and built with its own
  build/build.py into a temp dir), RD_WEBAPPS (for xregexp, default ../../web-apps),
  RD_X2T (x2t with the fix, default ../../core/build/bin/mac_arm64/x2t),
  RD_X2T_FRAMEWORKS (default ../../core/build/lib/mac_arm64), RD_FONTS (the app's
  fonts cache dir with AllFonts.js + font_selection.bin), RD_PLAYWRIGHT, RD_CHROME,
  RD_NO_BROWSER=1 skips part 3, RD_TMP (temp parent), RD_KEEP=1 keeps it.
  BASELINE=1: sdkjs from `git archive SDKJS_BASE_REF` and x2t RD_X2T_BASE (default
  the 2026.2.0 release converter in .rd-work/payload/converter, which predates the
  core fix) - MUST FAIL.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import media_c1 as h  # noqa: E402

BASELINE = bool(os.environ.get('BASELINE'))
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '7b232bed78^')
ST, END = '2500.5', '31000'


def trims(pptx):
    import re
    out = []
    for n in (1, 2):
        try:
            xml = h.slide_xml(pptx, n)
        except KeyError:
            break
        for pic in re.findall(r'<p:pic>.*?</p:pic>', xml, re.S):
            if 'videoFile' not in pic:
                continue
            t = re.search(r'<p14:trim\b[^>]*>', pic)
            off = re.search(r'<a:off x="(\d+)"', pic)
            out.append(('slide%d' % n, t.group(0) if t else None, int(off.group(1)) if off else None))
    return out


def good(t):
    return bool(t) and 'st="%s"' % ST in t and 'end="%s"' % END in t


def main():
    x2t = h.find_x2t(BASELINE)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('x2t: %s%s' % (x2t, '  (BASELINE, sdkjs %s)' % SDKJS_BASE_REF if BASELINE else ''))
    tmp = tempfile.mkdtemp(prefix='issue2002-', dir=os.environ.get('RD_TMP'))
    try:
        tree = h.build_sdkjs(tmp, SDKJS_BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'in.pptx')
        h.make_deck(deck, trim=(ST, END))
        print('input: %s' % trims(deck))

        # 1. core alone
        a = h.deck_to_bin(conv, tmp, deck, 'a')
        h.convert(conv, os.path.join(a, 'Editor.bin'), os.path.join(a, 'out.pptx'), h.FMT_PPTX)
        v = trims(os.path.join(a, 'out.pptx'))
        print('x2t pptx -> Editor.bin -> pptx: %s' % v)
        h.check(len(v) == 1 and good(v[0][1]), 'x2t round trip keeps <p14:trim st="%s" end="%s"/>' % (ST, END))

        # 2. through the sdkjs reader + writer in x2t's doctrenderer (the desktop's save), no changes
        empty = os.path.join(tmp, 'empty.json')
        open(empty, 'w').close()
        v = trims(h.save_with_changes(conv, tmp, a, empty, 'b'))
        print('Editor.bin -> sdkjs (doctrenderer) -> pptx: %s' % v)
        h.check(len(v) == 1 and good(v[0][1]), 'save through sdkjs keeps the trim')

        # 3. the real editor: open, duplicate the slide, move the video, save; x2t replays the changes
        if os.environ.get('RD_NO_BROWSER'):
            print('skip editor round trip (RD_NO_BROWSER)')
        else:
            res, changes = h.editor(tree, a, tmp)
            print('editor: opened %s, after duplicate %s, change batches %d, page errors %s'
                  % (res['opened'], res['edited'], res['changeBatches'], res['errors']))
            want = {'trimSt': float(ST), 'trimEnd': float(END)}
            h.check(res['opened'] == [[want]], 'the editor model has the trim after opening')
            h.check(res['edited'] == [[want], [want]], 'the duplicated video has the trim too')
            v = trims(h.save_with_changes(conv, tmp, a, changes, 'c'))
            print('editor changes replayed by x2t: %s' % v)
            h.check(len(v) == 2 and all(good(t) for _, t, _ in v), 'both videos saved with the trim')
            h.check(len(v) == 2 and sorted(o for _, _, o in v)[1] > 1000000, 'the moved video kept its move (change applied)')
    finally:
        if not os.environ.get('RD_KEEP'):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print('kept %s' % tmp)
    h.finish('#2002 video trim survives x2t, the sdkjs save and an editor round trip')


if __name__ == '__main__':
    main()

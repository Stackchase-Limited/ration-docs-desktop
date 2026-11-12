#!/usr/bin/env python3
"""
#2002 (second part) - the players honour a video's trim, and the editor can set it.

After the data-loss fix (issue-2002-media-trim: p14:trim kept by core and sdkjs) the
trim still did nothing: the players played the whole media and the editor had no
way to set it. Now:
  sdkjs  CImageShape.getMediaStartTime/getMediaEndTime return the trim (whole ms),
         so every player command's StartTime/EndTime carries it (EndTime = ms cut
         from the END, as p14:trim end, [MS-PPTX] 2.3.3.18); asc_get/setMediaSettings
         "TrimStart"/"TrimEnd" (ms, 0 = none) via CImageShape.setMediaTrim.
  web-apps  Playback > Trim start / Trim end (seconds).
  desktop-sdk  setMediaFlags (#2005) applies StartTime/EndTime: macOS sets the item's
         forwardPlaybackEndTime and plays/seeks from the trim start; Qt starts at the
         trim start and stops (or loops / rewinds) at the trimmed end.

What this runs (REAL code; shared harness ../issue-2002-media-trim/media_c1.py):
  1. the real slide editor (headless Chromium) on a deck with <p14:trim st="2500.5"
     end="31000"/>: the settings show it, the player commands carry it; setting
     TrimStart 1000 / TrimEnd 0 reopens the player with it, and the saved pptx (x2t
     replaying the editor's changes) has <p14:trim st="1000"/>.
  2. web-apps: the REAL Playback code of ImageSettings against a stub api.
  3. macOS: the REAL CCefViewMedia + AppKit player, generated 1 s silent movie, trim
     300 ms + 300 ms: plays 300..700 and stops; with loop it stays inside 300..700;
     with rewind it returns to 300, paused.
  4. Qt 5 (when available): QAscVideoView keeps the trim from setMediaFlags.
NOT claimed: a GUI check; Linux/Windows playback at runtime (QMediaPlayer does not
play offscreen here); the slider/time label still show the whole media.

Env as media_c1.py; RD_X2T must have the core part of #2002 (for the saved p14:trim).
BASELINE=1 uses SDKJS_BASE_REF / WEBAPPS_BASE_REF / BASE_REF (desktop-sdk) and MUST FAIL.
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'issue-2002-media-trim'))
import media_c1 as h  # noqa: E402

BASELINE = bool(os.environ.get('BASELINE'))
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '3ac6a8d2b2^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', '291d879da9^')
BASE_REF = os.environ.get('BASE_REF', '8160bcfb^')


def times(step):
    return [(p['Cmd'], p['StartTime'], p['EndTime']) for p in step['player'] if p['Cmd'] in ('showMediaControl', 'setMediaFlags')]


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('BASELINE (%s, %s, %s)' % (SDKJS_BASE_REF, WEBAPPS_BASE_REF, BASE_REF) if BASELINE else 'trees under test')
    tmp = tempfile.mkdtemp(prefix='issue2002p-', dir=os.environ.get('RD_TMP'))
    try:
        print('-- sdkjs: the editor')
        tree = h.build_sdkjs(tmp, SDKJS_BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'trim.pptx')
        h.make_deck(deck, trim=('2500.5', '31000'))
        a = h.deck_to_bin(conv, tmp, deck, 'a')
        res, changes = h.editor(tree, a, tmp, [{'TrimStart': 1000, 'TrimEnd': 0}], 'trim')
        s0, s1 = res['steps']
        print('opened: %s %s' % ({k: s0['settings'].get(k) for k in ('TrimStart', 'TrimEnd')}, times(s0)))
        print('after TrimStart 1000 / TrimEnd 0: %s %s' % ({k: s1['settings'].get(k) for k in ('TrimStart', 'TrimEnd')}, times(s1)))
        h.check(s0['settings'].get('TrimStart') == 2501 and s0['settings'].get('TrimEnd') == 31000, 'the settings show the file\'s trim (ms)')
        h.check(times(s0) == [('showMediaControl', 2501, 31000), ('setMediaFlags', 2501, 31000)], 'the player commands carry it (StartTime, EndTime)')
        h.check(s1['settings'].get('TrimStart') == 1000 and s1['settings'].get('TrimEnd') == 0, 'the new trim is read back')
        h.check(times(s1) == [('showMediaControl', 1000, None), ('setMediaFlags', 1000, None)], 'the player is reopened with the new trim')
        xml = h.slide_xml(h.save_with_changes(conv, tmp, a, changes, 'trim-save'))
        t = re.findall(r'<p14:trim\b[^>]*>', xml)
        print('saved: %s' % t)
        h.check(t == ['<p14:trim st="1000"/>'], 'saved as <p14:trim st="1000"/>')

        print('-- web-apps: Playback > Trim start / Trim end')
        r = h.webapps_panel(WEBAPPS_BASE_REF if BASELINE else None, ['numTrimStart', 'numTrimEnd'],
                            {'Mute': False, 'TrimStart': 2500, 'TrimEnd': 31000}, [['onMediaTrimChange', 'TrimStart', 1.5]])
        h.check(r is not None and 'id="image-spin-trim-start"' in r['template'] and 'id="image-spin-trim-end"' in r['template'], 'the template has both fields')
        h.check(r is not None and r.get('values') == {'numTrimStart': 2.5, 'numTrimEnd': 31}, 'the fields show seconds (got %s)' % (r and r.get('values')))
        h.check(r is not None and r.get('calls') == [{'TrimStart': 1500}], 'a change sends ms (got %s)' % (r and r.get('calls')))

        print('-- desktop-sdk macOS: CCefViewMedia + AppKit player (AVPlayer), trim 300 + 300 ms of 1 s')
        if sys.platform != 'darwin':
            print('skip (not macOS)')
        else:
            mac = h.MacPlayer(tmp, BASE_REF if BASELINE else None)
            plain, loop, rewind = mac.run(0, 300, 300), mac.run(1, 300, 300), mac.run(2, 300, 300)
            for n, s in (('plain', plain), ('loop', loop), ('rewind', rewind)):
                print('%s: %s' % (n, ' '.join('%d:%d:%d' % v for v in s)))
            h.check(h.at(plain, 100)[0] >= 300, 'starts at the trim start (0.1 s after play: %s)' % (h.at(plain, 100),))
            q = h.at(plain, 1500)
            h.check(q[1] == 0 and 650 <= q[0] <= 750, 'stops at the trimmed end, 700 ms (1.5 s: %s)' % (q,))
            inside = all(250 <= v[1] <= 760 for v in loop)
            h.check(inside and h.at(loop, 2500)[1] == 1, 'with loop it plays 300..700 over and over (2.5 s: %s)' % (h.at(loop, 2500),))
            q = h.at(rewind, 1500)
            h.check(q[1] == 0 and 250 <= q[0] <= 350, 'with rewind it goes back to 300 ms, paused (1.5 s: %s)' % (q,))

        print('-- desktop-sdk Qt: QCefView_Media + QAscVideoView')
        qt = h.qt_player(tmp, BASE_REF if BASELINE else None, r'"trim=%d,%d\n", p->m_nTrimStart, p->m_nTrimEnd')
        if qt is not None:
            built, run = qt
            h.check(built, 'the Qt player builds with the change')
            if built:
                h.check(run(0, 300, 300) == 'trim=300,300' and run(0, -1, -1) == 'trim=0,0', 'setMediaFlags gives the view the trim (%s / %s)' % (run(0, 300, 300), run(0, -1, -1)))
    finally:
        if not os.environ.get('RD_KEEP'):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print('kept %s' % tmp)
    h.finish('#2002 the trim plays as trimmed and can be set in the editor')


if __name__ == '__main__':
    main()

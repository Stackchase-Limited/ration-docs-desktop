#!/usr/bin/env python3
"""
#2006 - Presentation: "Rewind after playing" for a video / audio.

PowerPoint stores it as fill="remove" on the <p:cTn> of the media's
<p:video|p:audio><p:cMediaNode> (its default, fill="hold", keeps the last frame).
That survived open/save, but nothing in the editor could set it and neither desktop
player had an end-of-media hook: the video always stayed on its last frame.

Fix (option; default unchanged = stay on the last frame), on top of #2005's
setMediaFlags command and end-of-media hooks:
  sdkjs  CTiming.getMediaSettings/setMediaSettings "Rewind"; setMediaFlags flag 2.
  web-apps  Playback > Rewind after playing.
  desktop-sdk  macOS: at AVPlayerItemDidPlayToEndTime pause + seek to the start;
         Qt: at EndOfMedia seek to 0 + pause (first frame shown). Loop wins over rewind.

What this runs (REAL code; shared harness ../issue-2002-media-trim/media_c1.py):
  1. the real slide editor (headless Chromium): a video without a media node - Rewind
     off, From 0; ticking Rewind sends setMediaFlags From 2 and the saved pptx has
     fill="remove" on the media node; a PowerPoint deck with fill="remove" - Rewind on,
     From 2 straight away.
  2. web-apps: the REAL Playback code of ImageSettings against a stub api.
  3. macOS: the REAL CCefViewMedia + AppKit player, generated 1 s silent movie: with
     the flag it is back at 0, paused, after the end; without it stays at the end.
  4. Qt 5 (when available): the REAL QCefView_Media + QAscVideoView take the flag.
NOT claimed: a GUI check in the app; Linux/Windows playback at runtime; that
PowerPoint writes exactly fill="remove" for this option (from the triage notes and
the time-node semantics: remove = the media's effect, its position, is undone).

Env: RD_SDKJS, RD_WEBAPPS, RD_DESKTOP_SDK, RD_CORE, RD_X2T, RD_FONTS, RD_QMAKE,
RD_KERNEL_DIR (see media_c1.py). BASELINE=1 uses SDKJS_BASE_REF / WEBAPPS_BASE_REF /
BASE_REF (desktop-sdk) - the parents of the fixes - and MUST FAIL.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'issue-2002-media-trim'))
import media_c1 as h  # noqa: E402

BASELINE = bool(os.environ.get('BASELINE'))
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '09f9fe40f6^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', '9cf394be57^')
BASE_REF = os.environ.get('BASE_REF', 'a7c893cc^')
NAME, FLAG, CHECKBOX, CTRL = 'Rewind', 2, 'image-checkbox-rewind', 'chRewind'


def flags_sent(step):
    return [p['From'] for p in step['player'] if p['Cmd'] == 'setMediaFlags']


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('BASELINE (%s, %s, %s)' % (SDKJS_BASE_REF, WEBAPPS_BASE_REF, BASE_REF) if BASELINE else 'trees under test')
    tmp = tempfile.mkdtemp(prefix='issue2006-', dir=os.environ.get('RD_TMP'))
    try:
        print('-- sdkjs: the editor')
        tree = h.build_sdkjs(tmp, SDKJS_BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'plain.pptx')
        h.make_deck(deck)
        a = h.deck_to_bin(conv, tmp, deck, 'a')
        res, changes = h.editor(tree, a, tmp, [{NAME: True}], 'plain')
        s0, s1 = res['steps']
        print('opened %s, flags %s; after %s=true: %s, flags %s' % (s0['settings'], flags_sent(s0), NAME, s1['settings'], flags_sent(s1)))
        h.check(s0['settings'].get(NAME) is False and flags_sent(s0) == [0], 'a video without a media node: %s off, setMediaFlags From 0' % NAME)
        h.check(s1['settings'].get(NAME) is True and flags_sent(s1) == [FLAG], 'ticking %s: the player is reopened with setMediaFlags From %d' % (NAME, FLAG))
        ctn = h.media_cTn(h.slide_xml(h.save_with_changes(conv, tmp, a, changes, 'plain-save')))
        print('saved media node cTn: %s' % ctn)
        h.check(bool(ctn) and ctn.get('fill') == 'remove' and 'repeatCount' not in ctn, 'saved as PowerPoint does: fill="remove" on the media node')

        deck2 = os.path.join(tmp, 'pp.pptx')
        h.make_deck(deck2, media_node_attrs='fill="remove"')
        b = h.deck_to_bin(conv, tmp, deck2, 'b')
        res, _ = h.editor(tree, b, tmp, [], 'pp')
        s0 = res['steps'][0]
        print('PowerPoint deck that rewinds: %s, flags %s' % (s0['settings'], flags_sent(s0)))
        h.check(s0['settings'].get(NAME) is True and flags_sent(s0) == [FLAG], 'a deck that rewinds: %s on, setMediaFlags From %d' % (NAME, FLAG))

        print('-- web-apps: Playback > Rewind after playing')
        r = h.webapps_panel(WEBAPPS_BASE_REF if BASELINE else None, [CTRL], {'Mute': False, NAME: True}, [['onMediaSettingChange', NAME, False]])
        h.check(r is not None and 'id="%s"' % CHECKBOX in r['template'], 'the template has the checkbox')
        h.check(r is not None and 'values' in r and r['values'][CTRL] is True, 'the box shows the setting (got %s)' % (r and r.get('values')))
        h.check(r is not None and r.get('calls') == [{NAME: False}], 'unticking sends {%s: false} (got %s)' % (NAME, r and r.get('calls')))

        print('-- desktop-sdk macOS: CCefViewMedia + AppKit player (AVPlayer)')
        if sys.platform != 'darwin':
            print('skip (not macOS)')
        else:
            mac = h.MacPlayer(tmp, BASE_REF if BASELINE else None)
            on, off = mac.run(FLAG), mac.run(0)
            print('flag %d: %s' % (FLAG, ' '.join('%d:%d:%d' % s for s in on)))
            print('no flag: %s' % ' '.join('%d:%d:%d' % s for s in off))
            p1, p2 = h.at(on, 1500), h.at(on, 2500)
            h.check(p1 and p1[1] == 0 and p1[0] < 100 and p2 and p2[1] == 0 and p2[0] < 100, 'with the rewind flag the 1 s movie is back at its start, paused, after its end (1.5 s: %s, 2.5 s: %s)' % (p1, p2))
            q = h.at(off, 1500)
            h.check(q and q[1] == 0 and q[0] >= 900, 'without it, it stops at the end as before (1.5 s: %s)' % (q,))

        print('-- desktop-sdk Qt: QCefView_Media + QAscVideoView')
        qt = h.qt_player(tmp, BASE_REF if BASELINE else None, r'"rewind=%d\n", (int)p->m_bIsRewind')
        if qt is not None:
            built, run = qt
            h.check(built, 'the Qt player builds with the change')
            if built:
                h.check(run(FLAG) == 'rewind=1' and run(0) == 'rewind=0', 'setMediaFlags sets the view\'s rewind (%s / %s)' % (run(FLAG), run(0)))
    finally:
        if not os.environ.get('RD_KEEP'):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print('kept %s' % tmp)
    h.finish('#2006 Rewind after playing: settable, saved as PowerPoint does, and the players rewind')


if __name__ == '__main__':
    main()

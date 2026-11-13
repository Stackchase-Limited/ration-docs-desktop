#!/usr/bin/env python3
"""
#2550 - Presentation: Media animations (Play / Pause / Stop) in the Animation tab.

PowerPoint's Animations > Media effects are ordinary timing nodes: a <p:par> whose cTn has
presetClass="mediacall" (presetID 1 Play, 2 Pause, 3 Stop) holding
<p:cmd type="call" cmd="playFrom(0.0)" | "togglePause" | "stop"> on the video/audio. The editor
kept them from PowerPoint files (and since #878 a Play reaches the desktop player in a slide show),
but could not create them: CTiming.createEffect only knew the preset binaries of the entrance/
emphasis/exit/path classes (ANIMATION_PRESET_CLASSES has no class 3), so asc_AddAnimation with
PRESET_CLASS_MEDIACALL did nothing, and the Animation gallery had no Media group.

Fix (a new choice in the gallery; nothing changes for existing effects or decks):
  sdkjs     AscFormat.MEDIACALL_PLAY/PAUSE/STOP; CTiming.createMediaCallEffect builds the par +
            p:cmd as PowerPoint writes it (only for a video or audio); callTimelineMediaCommand
            sends Pause/Stop only to the media's own open player and never drops a timeline
            command as a repeat of the last one (a second Pause resumes).
  web-apps  Animation gallery / Add animation / More effects: group "Media" with Play, Pause,
            Stop, enabled only while a video or audio is selected; Duration/Repeat locked for them.

What this runs (REAL code; harness ../issue-2002-media-trim/media_c1.py):
  1. the real slide editor (headless Chromium) on a deck made by x2t: Media > Play on a text
     placeholder adds nothing; on the video, Play, Pause and Stop are added and reported to the
     tab as class 3 / type 1..3; the desktop save (x2t replaying the editor's changes) writes
     presetClass="mediacall" presetID 1/2/3 with p:cmd type="call" cmd="playFrom(0.0)"/
     "togglePause"/"stop" on spid of the video.
  2. that saved deck, opened again, in a real slide show: click 1 opens the video's player and
     plays it, click 2 sends togglePause, click 3 sends stop.
  3. a deck written as PowerPoint writes these effects (Play, Pause, Pause, Stop on click)
     round-trips through x2t (pptx -> Editor.bin -> pptx) with the effects intact, and plays in
     the slide show; the second Pause reaches the player (before, callMediaPlayerCommand dropped
     it as a repeat of the first, so a paused video could not be resumed by the timeline).
  4. web-apps: the REAL Common.define.effectData (define.js) has the Media group and the three
     effects; the REAL controller code (onFocusObject + lockMediaEffects) disables them unless a
     video/audio is selected.
NOT claimed: a GUI check of the gallery (icons: Play/Stop reuse the preview icons, Pause is drawn
in CSS); that PowerPoint itself opens a deck saved here (the XML is compared with what PowerPoint
writes, not opened in PowerPoint); the Play effect's duration: PowerPoint writes the media's
length, which the editor does not know, so 1 ms is written and an "After previous" effect after a
Play starts with the media rather than at its end.

Env: RD_SDKJS, RD_WEBAPPS, RD_X2T, RD_FONTS (a COPY of the fonts cache: x2t may rewrite
AllFonts.js), RD_TMP, RD_PLAYWRIGHT, RD_CHROME. BASELINE=1 uses SDKJS_BASE_REF / WEBAPPS_BASE_REF
(the parents of the fixes) and MUST FAIL.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'issue-2002-media-trim'))
import media_c1 as h  # noqa: E402

BASELINE = bool(os.environ.get('BASELINE'))
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '8a4cb045f8^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', 'c3c656be29^')

CMDS = {'1': 'playFrom(0.0)', '2': 'togglePause', '3': 'stop'}


def run_editor(tree, bin_dir, work, mode, name):
    out = os.path.join(work, name + '-changes0.json')
    r = subprocess.run(['node', os.path.join(HERE, 'editor_media.js'), tree, os.path.join(bin_dir, 'Editor.bin'),
                        os.path.join(h.FONTS, 'AllFonts.js'), out, mode], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit('editor harness failed:\n' + r.stdout[-2000:] + r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1]), out


def media_effects(xml):
    """(presetID, cmd type, cmd, spid, nodeType) of every presetClass="mediacall" par of a slide."""
    res = []
    for m in re.finditer(r'<p:cTn\b([^>]*presetClass="mediacall"[^>]*)>(.*?)</p:cmd>', xml, re.S):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        cmd = re.search(r'<p:cmd\b([^>]*)>', m.group(2))
        cattrs = dict(re.findall(r'(\w+)="([^"]*)"', cmd.group(1))) if cmd else {}
        spid = re.search(r'<p:spTgt\s+spid="(\d+)"', m.group(2))
        res.append((attrs.get('presetID'), cattrs.get('type'), cattrs.get('cmd'), spid and spid.group(1), attrs.get('nodeType')))
    return res


def video_spid(xml):
    m = re.search(r'<p:pic>\s*<p:nvPicPr>\s*<p:cNvPr id="(\d+)"', xml)
    return m and m.group(1)


def pp_timing(spid):
    """the main sequence as PowerPoint writes Play, Pause, Pause (resume), Stop on click for the video spid."""
    nid = [2]

    def n():
        nid[0] += 1
        return nid[0]
    clicks = ''
    for pid in ('1', '2', '2', '3'):
        dur = '1000' if pid == '1' else '1'
        clicks += ('<p:par><p:cTn id="%d" fill="hold"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>'
                   '<p:par><p:cTn id="%d" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
                   '<p:par><p:cTn id="%d" presetID="%s" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="clickEffect">'
                   '<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
                   '<p:cmd type="call" cmd="%s"><p:cBhvr><p:cTn id="%d" dur="%s" fill="hold"/><p:tgtEl><p:spTgt spid="%s"/></p:tgtEl></p:cBhvr></p:cmd>'
                   '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
                   % (n(), n(), n(), pid, CMDS[pid], n(), dur, spid))
    return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>' + clicks +
            '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
            '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
            '<p:video><p:cMediaNode vol="80000"><p:cTn id="%d" fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/>'
            '</p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="%s"/></p:tgtEl></p:cMediaNode></p:video>'
            '</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>' % (n(), spid))


def make_pp_deck(src, dst):
    zin = zipfile.ZipFile(src)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == 'ppt/slides/slide1.xml':
                d = d.replace(b'</p:sld>', pp_timing('4').encode() + b'</p:sld>', 1)
            zo.writestr(it, d)


def show_cmds(res):
    """per click: the player commands of the slide show, without the bookkeeping ones."""
    return [[c['Cmd'] for c in step['player'] if c['Cmd'] not in ('update', 'hideMediaControl')] for step in res['clicks']]


def check_show(res, what, pauses=1):
    cmds = show_cmds(res)
    print('%s: in show %s, commands per click %s' % (what, res['inShow'], cmds))
    h.check(res['inShow'] and len(cmds) >= 3 + pauses, '%s: the slide show runs' % what)
    if len(cmds) < 3 + pauses:
        return
    h.check('showMediaControl' in cmds[1] and 'play' in cmds[1] and cmds[1].index('showMediaControl') < cmds[1].index('play'),
            '%s: click 1 (Play) opens the video\'s player and plays it' % what)
    for i in range(pauses):
        h.check(cmds[2 + i] == ['togglePause'], '%s: click %d (Pause) sends togglePause%s' % (what, 2 + i, ' again (resumes)' if i else ''))
    h.check(cmds[2 + pauses] == ['stop'], '%s: click %d (Stop) sends stop' % (what, 2 + pauses))


def webapps_checks():
    src = h.WEBAPPS
    ref = WEBAPPS_BASE_REF if BASELINE else None
    define_js = h.read(src, 'apps/presentationeditor/main/app/view/define.js', ref)
    ctrl_js = h.read(src, 'apps/presentationeditor/main/app/controller/Animation.js', ref)
    script = os.path.join(HERE, 'webapps_check.js')
    r = subprocess.run(['node', script], input=json.dumps({'define': define_js, 'ctrl': ctrl_js}), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('web-apps check failed:\n' + r.stdout[-2000:] + r.stderr[-2000:])
    res = json.loads(r.stdout.strip().splitlines()[-1])
    print('web-apps: %s' % res)
    h.check(res['group'] == 3, 'web-apps: the gallery has a Media group (PRESET_CLASS_MEDIACALL)')
    h.check(res['effects'] == [[1, 'Play'], [2, 'Pause'], [3, 'Stop']], 'web-apps: Media has Play, Pause, Stop (gallery)')
    h.check(res['full'] == [[1, 'Play'], [2, 'Pause'], [3, 'Stop']], 'web-apps: and in More effects')
    h.check(res['lockedNoMedia'] is True and res['lockedMedia'] is False,
            'web-apps: Media effects are disabled unless a video/audio is selected')


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('BASELINE (%s, %s)' % (SDKJS_BASE_REF, WEBAPPS_BASE_REF) if BASELINE else 'trees under test')
    print('-- web-apps')
    webapps_checks()
    tmp = tempfile.mkdtemp(prefix='issue2550-', dir=os.environ.get('RD_TMP'))
    try:
        print('-- sdkjs: the editor')
        tree = h.build_sdkjs(tmp, SDKJS_BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        deck = os.path.join(tmp, 'plain.pptx')
        h.make_deck(deck)
        a = h.deck_to_bin(conv, tmp, deck, 'a')
        res, changes = run_editor(tree, a, tmp, 'add', 'add')
        print('Play on a placeholder: %s; on the video: %s; tab properties %s' % (res['onShape'], res['added'], res['props']))
        h.check(res['onShape'] == [], 'Media > Play on a text placeholder adds nothing')
        h.check([(e['cls'], e['id'], e['cmd'], e['target']) for e in res['added']] ==
                [(3, 1, 'playFrom(0.0)', 'video'), (3, 2, 'togglePause', 'video'), (3, 3, 'stop', 'video')],
                'Media > Play, Pause, Stop on the video add the three mediacall effects')
        h.check(res['props'] == [{'cls': 3, 'type': 1}, {'cls': 3, 'type': 2}, {'cls': 3, 'type': 3}],
                'the Animation tab gets each new effect as class 3 (Media), type 1/2/3')
        saved = h.save_with_changes(conv, tmp, a, changes, 'add-save')
        xml = h.slide_xml(saved)
        spid = video_spid(xml)
        eff = media_effects(xml)
        print('saved: video spid %s, media effects %s' % (spid, eff))
        h.check([e[:4] for e in eff] == [('1', 'call', 'playFrom(0.0)', spid), ('2', 'call', 'togglePause', spid), ('3', 'call', 'stop', spid)],
                'saved as PowerPoint writes them: presetClass="mediacall" + p:cmd type="call" playFrom(0.0)/togglePause/stop')

        b = h.deck_to_bin(conv, tmp, saved, 'b')
        res, _ = run_editor(tree, b, tmp, 'show', 'show-ours')
        check_show(res, 'deck made here')

        pp = os.path.join(tmp, 'pp.pptx')
        make_pp_deck(deck, pp)
        c = h.deck_to_bin(conv, tmp, pp, 'c')
        back = os.path.join(tmp, 'pp-back.pptx')
        h.convert(conv, os.path.join(c, 'Editor.bin'), back, h.FMT_PPTX)
        eff_in, eff_out = media_effects(h.slide_xml(pp)), media_effects(h.slide_xml(back))
        print('PowerPoint-style deck: %s -> %s' % (eff_in, eff_out))
        h.check(len(eff_in) == 4 and [e[:4] for e in eff_out] == [e[:4] for e in eff_in], 'a PowerPoint-style deck keeps its Play/Pause/Stop through x2t')
        res, _ = run_editor(tree, c, tmp, 'show', 'show-pp')
        check_show(res, 'PowerPoint-style deck', pauses=2)
    finally:
        if not os.environ.get('KEEP_TMP'):
            shutil.rmtree(tmp, ignore_errors=True)
    h.finish('#2550 media Play/Pause/Stop animations')


if __name__ == '__main__':
    main()

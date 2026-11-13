#!/usr/bin/env python3
"""
#2020 - Ctrl+Shift+V pastes values only in the spreadsheet editor (an option, off by default).

The report's first half (Paste Special > Values changed the destination's font size / added a
currency symbol) is fixed in 9.4 and confirmed by the reporter. What remained: Ctrl+Shift+V, the
Excel/LibreOffice key for "paste values", did nothing special - cell/model/Shortcuts.js binds Paste
only to Ctrl+V / Shift+Insert (Cmd+V), and _onWindowKeyDown (cell/view/EventsController.js) had no
case for V, so the keys fell through to an ordinary paste.

What now: File > Advanced settings "Ctrl+Shift+V pastes values only in the cell grid" (⇧⌘V on
macOS), stored as sse-settings-paste-values-shortcut, handed to sdkjs as asc_setPasteValuesShortcut.
With it on, Ctrl+Shift+V (Cmd+Shift+V) in the grid - cell editor closed, no drawing selected, sheet
editable - arms the next paste (EventsController case 86) and asks the host for it (asc_Paste ->
AscDesktopEditor.Paste, the toolbar Paste button's path); asc_PasteData then pastes it with
Paste Special > Values props (one paste, within 2 s of the keys). Off, nothing changes.

This test runs REAL code: the sdkjs tree under test (RD_REPO; BASELINE=1: `git archive BASE_REF`) is
built (cell, concat build), a workbook made here is converted by x2t, and the cell editor runs in
headless Chromium with a stubbed desktop host whose Paste() fires the paste the way the host does
(the clipboard is what the real copy code produced from Src!B3:B6: rich text runs, a bold Times 18
cell, a currency-formatted number, a two-line cell). Dest!B3:B6 are Arial 9 italic, format 0.00.
Checked: option on -> the keys are taken (preventDefault), Dest keeps its own font/number format and
gets the values (line break kept, no rich runs); one Undo takes it back; a following plain paste is a
normal paste. Option off -> the keys are not taken and an ordinary paste happens (as today).
It also checks the web-apps wiring (checkbox, saved key, Main/LeftMenu hand-off) by reading RD_WEBAPPS.

Also established (no change needed): Paste Special > Values does NOT carry the source's run fonts -
the binary route's calculateValueAndBinaryFormula only fills rangeStyle.cellValueData when
specialPasteProps.cellStyle is set (pasteOnlyValues clears it), and the rich branches before
WorksheetView.js `range.setValueData(rangeStyle.cellValueData)` need specialPasteProps.font. The
"special" route of paste_rt.js shows it (both binary and HTML clipboards); not asserted here.

NOT claimed: that CEF / the macOS menu deliver Cmd+Shift+V / Ctrl+Shift+V to the editor (no menu item
uses Cmd+Shift+V in Main.storyboard; Paste and Match Style is Opt+Cmd+Shift+V) and that the host's
real Paste() produces the paste event - needs a GUI check; the browser (non-desktop) route, where the
keys' own paste event is used.

  python3 fork-fix-tests/issue-2020-paste-values-shortcut/extract_and_run.py
  RD_REPO=<sdkjs checkout> (default ../../sdkjs), RD_WEBAPPS=<web-apps> (default ../../web-apps),
  RD_X2T, RD_FONTS, RD_PLAYWRIGHT, RD_CHROME (see ../issue-2002-media-trim/media_c1.py)
  BASELINE=1 with BASE_REF / WEBAPPS_BASE_REF: no option, the keys paste everything -> FAILS.
Exits 2 (CANNOT RUN) when x2t, the fonts cache or Playwright is missing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'issue-2002-media-trim'))
import media_c1 as h  # noqa: E402  (x2t helpers shared with the media tests)

REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'sdkjs'))
WEBAPPS = os.environ.get('RD_WEBAPPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'web-apps'))
BASE_REF = os.environ.get('BASE_REF', '4b3250a966^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', '023d023fa9^')
BASELINE = bool(os.environ.get('BASELINE'))

failures = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + detail) if detail and not cond else ''))
    if not cond:
        failures.append(name)


def cannot(what):
    print('CANNOT RUN: ' + what)
    sys.exit(2)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise SystemExit('command failed: ' + ' '.join(cmd[:3]))
    return r.stdout


def build_cell(tmp):
    tree = os.path.join(tmp, 'sdkjs')
    if BASELINE:
        h.materialize(REPO, BASE_REF, [], tree)
    else:
        os.makedirs(tree)
        for name in os.listdir(REPO):
            if name in ('.git', 'deploy', 'develop', 'build'):
                continue
            if subprocess.run(['cp', '-cR', os.path.join(REPO, name), tree], capture_output=True).returncode != 0:
                src = os.path.join(REPO, name)
                (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(tree, name))
        os.makedirs(os.path.join(tree, 'build'))
        for f in os.listdir(os.path.join(REPO, 'build')):
            p = os.path.join(REPO, 'build', f)
            if f != 'node_modules' and os.path.isfile(p):
                shutil.copy(p, os.path.join(tree, 'build', f))
    r = subprocess.run([sys.executable, 'build.py', '--beta=false', '--minimize', '--desktop', '--product', 'cell'],
                       cwd=os.path.join(tree, 'build'), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(os.path.join(tree, 'deploy', 'sdkjs', 'cell', 'sdk-all.js')):
        raise SystemExit('sdkjs build failed:\n' + r.stdout[-2000:] + r.stderr[-2000:])
    return tree


def webapps(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', WEBAPPS, 'show', WEBAPPS_BASE_REF + ':' + rel], capture_output=True, text=True).stdout
    with open(os.path.join(WEBAPPS, rel), encoding='utf-8') as f:
        return f.read()


def main():
    x2t = h.find_x2t(False)
    allfonts = os.path.join(h.FONTS, 'AllFonts.js')
    pw = os.environ.get('RD_PLAYWRIGHT') or '/Users/osindero/dev/active/node_modules/playwright'
    for p, what in ((x2t, 'x2t'), (allfonts, 'fonts cache'), (pw, 'playwright')):
        if not os.path.exists(p):
            cannot('missing %s (%s)' % (what, p))

    tmp = tempfile.mkdtemp(prefix='rd2020-')
    try:
        tree = build_cell(tmp)
        os.makedirs(os.path.join(tmp, 'c'))
        conv = h.setup_x2t(os.path.join(tmp, 'c'), x2t, tree)
        book = os.path.join(tmp, 'book.xlsx')
        run([sys.executable, os.path.join(HERE, 'mkbook.py'), book])
        binf = os.path.join(tmp, 'Editor.bin')
        h.convert(conv, book, binf, 8194)

        def editor(route, mode):
            out = run(['node', os.path.join(HERE, 'paste_rt.js'), tree, binf, allfonts, route, mode], timeout=600)
            return json.loads(out.strip().splitlines()[-1])

        dest = {'numFormat': '0.00', 'font': 'Arial 9 i', 'runs': None}
        values = {'B3': 'Big red', 'B4': 'plain styled', 'B5': '125.5', 'B6': 'line1\nline2'}
        for route in ('internal', 'html'):
            on = editor(route, 'shortcut')
            got = {k: (v['text'], v['numFormat'], v['font'], v['runs']) for k, v in on['afterKeys'].items()}
            want = {k: (values[k], dest['numFormat'], dest['font'], None) for k in values}
            print('%s clipboard, option on, Ctrl+Shift+V: %s' % (route, json.dumps(got)))
            check('%s: option on - the keys are taken and the host asked to paste' % route,
                  on['keyResult'] == 'prevented' and on['native'] == 1, json.dumps([on['keyResult'], on['native']]))
            check('%s: option on - values only, Dest keeps Arial 9 italic and 0.00, no rich runs' % route,
                  got == want and not on['errors'], json.dumps(on['errors']))
            check('%s: option on - one Undo takes the paste back' % route,
                  all(v['text'] == '' for v in on['afterUndo'].values()))
            check('%s: option on - a following plain paste is a normal paste (runs kept)' % route,
                  on['plainAfter'] == 'Calibri 11 runs=2', on['plainAfter'])
            off = editor(route, 'shortcut-off')
            check('%s: option off - the keys are not taken, an ordinary paste happens (today)' % route,
                  off['keyResult'] == 'not prevented' and off['native'] == 0
                  and off['afterKeys']['B4']['font'] == 'Times New Roman 18 b'
                  and off['afterKeys']['B3']['runs'] == ['Courier New 20:"Big"', 'Times New Roman 14:" red"'],
                  json.dumps(off['afterKeys']))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # web-apps: the checkbox, its saved key, and the hand-off to sdkjs at load and on apply
    A = 'apps/spreadsheeteditor/main/'
    panels = webapps(A + 'app/view/FileMenuPanels.js')
    check('web-apps: Advanced settings has the checkbox, saved as sse-settings-paste-values-shortcut',
          'fms-chb-paste-values-shortcut' in panels and
          'setItem("sse-settings-paste-values-shortcut", this.chPasteValuesShortcut.isChecked() ? 1 : 0)' in panels)
    for c in ('Main.js', 'LeftMenu.js'):
        check('web-apps: %s hands the setting to asc_setPasteValuesShortcut' % c,
              'asc_setPasteValuesShortcut(value)' in webapps(A + 'app/controller/' + c))
    check('web-apps: en.json has the label', 'strPasteValuesShortcut"' in webapps(A + 'locale/en.json'))

    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

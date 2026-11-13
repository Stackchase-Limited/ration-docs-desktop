#!/usr/bin/env python3
"""
#1687 - PDF editor: a new text box can take the style of the last one (an option, off by default).

What there was: every text box drawn in the PDF editor (Insert > Text Box) started with the defaults -
common/Drawings/TrackObjects/NewShapeTracks.js getShape, textRect branch, gives a PDF text box no fill,
no line and an empty paragraph with no text properties - so font, size, colour, weight and the box's
fill, border and shadow had to be set again for each one (the reporter's complaint).

What now: File > Advanced settings "New text boxes use the last style" (pdfe-settings-textbox-last-style,
handed to sdkjs as asc_setTextBoxLastStyle). With it on, the text box being left (CPDFDoc.BlurActiveObject)
is remembered - fill, line, effects (shadow), the text properties where its text ends and its paragraph
alignment (CPDFDoc.RememberTextBoxStyle; with the option off nothing is kept) - and the next text box drawn gets them in getShape
(CPDFDoc.ApplyLastTextBoxStyle). Off, nothing changes.

This test runs REAL code: the sdkjs tree under test (RD_REPO; BASELINE=1: `git archive BASE_REF`) is
built (word bundle, which carries pdf/) and loaded in headless Chromium. On the real PDFEditorApi /
CPDFDoc / CGraphicObjects prototypes (stub instances: no document is opened; the viewer only gets
repaint calls) it draws a text box with the real NewShapeTrack("textRect").track/getShape (real
CPdfShape, CDrawingDocContent), styles it (yellow fill, 2 pt line, outer shadow, "Hello" in Courier New
24 bold, centred), leaves it with the real BlurActiveObject, and draws a second one.
Checked: option on -> the second box has the fill, line, shadow, centring, and Courier New 24 bold on
its empty run and paragraph mark (what typing uses); option off -> the second box is the default one,
as before. It also checks the web-apps wiring (checkbox, saved key, Main/LeftMenu hand-off) by reading
RD_WEBAPPS.

NOT claimed: the drag in the real viewer (StartAddShape -> StartTrackNewShapeState -> getShape) and
Undo of the new box - needs a GUI check; text boxes made by paste and FreeText annotations (not
affected by design); what a later edit of the old box does (the style is copied when it is left).

  python3 fork-fix-tests/issue-1687-pdf-textbox-last-style/extract_and_run.py
  RD_REPO=<sdkjs checkout> (default ../../sdkjs), RD_WEBAPPS=<web-apps> (default ../../web-apps),
  RD_FONTS, RD_PLAYWRIGHT, RD_CHROME. BASELINE=1 with BASE_REF / WEBAPPS_BASE_REF -> FAILS.
Exits 2 (CANNOT RUN) when the fonts cache or Playwright is missing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'sdkjs'))
WEBAPPS = os.environ.get('RD_WEBAPPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'web-apps'))
FONTS = os.environ.get('RD_FONTS') or '/Users/osindero/dev/active/rationdocs/.rd-work/fonts-cache'
BASE_REF = os.environ.get('BASE_REF', 'b264368ba6^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', 'bdc0d3f029^')
BASELINE = bool(os.environ.get('BASELINE'))

failures = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + detail) if detail and not cond else ''))
    if not cond:
        failures.append(name)


def build_word(tmp):
    tree = os.path.join(tmp, 'sdkjs')
    os.makedirs(tree)
    if BASELINE:
        arc = subprocess.run(['git', '-C', REPO, 'archive', BASE_REF], capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', tree], input=arc, check=True)
    else:
        for name in os.listdir(REPO):
            if name in ('.git', 'deploy', 'develop', 'build'):
                continue
            src = os.path.join(REPO, name)
            if subprocess.run(['cp', '-cR', src, tree], capture_output=True).returncode != 0:
                (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(tree, name))
        os.makedirs(os.path.join(tree, 'build'))
        for f in os.listdir(os.path.join(REPO, 'build')):
            p = os.path.join(REPO, 'build', f)
            if f != 'node_modules' and os.path.isfile(p):
                shutil.copy(p, os.path.join(tree, 'build', f))
    r = subprocess.run([sys.executable, 'build.py', '--beta=false', '--minimize', '--desktop', '--product', 'word'],
                       cwd=os.path.join(tree, 'build'), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(os.path.join(tree, 'deploy', 'sdkjs', 'word', 'sdk-all.js')):
        raise SystemExit('sdkjs build failed:\n' + r.stdout[-2000:] + r.stderr[-2000:])
    return tree


def webapps(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', WEBAPPS, 'show', WEBAPPS_BASE_REF + ':' + rel], capture_output=True, text=True).stdout
    with open(os.path.join(WEBAPPS, rel), encoding='utf-8') as f:
        return f.read()


def main():
    allfonts = os.path.join(FONTS, 'AllFonts.js')
    pw = os.environ.get('RD_PLAYWRIGHT') or '/Users/osindero/dev/active/node_modules/playwright'
    for p, what in ((allfonts, 'fonts cache'), (pw, 'playwright')):
        if not os.path.exists(p):
            print('CANNOT RUN: missing %s (%s)' % (what, p))
            sys.exit(2)

    tmp = tempfile.mkdtemp(prefix='rd1687-')
    try:
        tree = build_word(tmp)
        r = subprocess.run(['node', os.path.join(HERE, 'textbox_rt.js'), tree, allfonts], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            sys.stderr.write(r.stdout[-2000:] + r.stderr[-3000:])
            raise SystemExit('editor run failed')
        res = json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    default = {'fill': 'none', 'ln': None, 'shadow': False, 'paraEndPr': [None, None], 'jc': None,
               'runs': [['run', None, None, None], ['end', None, None, None]]}
    print('option on, second box: ' + json.dumps(res['on']['second']))
    check('a drawn text box starts with the defaults', res['off']['first'] == default and res['on']['first'] == default,
          json.dumps([res['off']['first'], res['on']['first']]))
    check('the PDF api has asc_setTextBoxLastStyle / asc_getTextBoxLastStyle', res['hasOption'])
    on = res['on']['second']
    check('option on: the next box has the last box\'s fill, line and shadow',
          on['fill'] == 'solid 255,255,0' and on['ln'] == 25400 and on['shadow'], json.dumps(on))
    check('option on: ...its text properties (Courier New 24 bold) on the empty run and the paragraph mark',
          on['runs'] == [['run', 24, True, 'Courier New'], ['end', 24, True, 'Courier New']] and on['paraEndPr'] == [24, True],
          json.dumps(on['runs']))
    check('option on: ...and its alignment (centred)', on['jc'] == 2, str(on['jc']))
    check('option off: the next box is the default one (today)', res['off']['second'] == default, json.dumps(res['off']['second']))
    check('option off: nothing is remembered; on: the box left is', not res['off']['remembered'] and res['on']['remembered'],
          json.dumps([res['off']['remembered'], res['on']['remembered']]))
    check('no script errors', not res['errors'], json.dumps(res['errors']))

    A = 'apps/pdfeditor/main/'
    panels = webapps(A + 'app/view/FileMenuPanels.js')
    check('web-apps: Advanced settings has the checkbox, saved as pdfe-settings-textbox-last-style',
          'fms-chb-textbox-last-style' in panels and
          'setBool("pdfe-settings-textbox-last-style", this.chTextBoxLastStyle.isChecked())' in panels)
    check('web-apps: Main.js hands it to asc_setTextBoxLastStyle at load',
          'asc_setTextBoxLastStyle(value)' in webapps(A + 'app/controller/Main.js'))
    check('web-apps: LeftMenu.js hands it over when settings are applied',
          'asc_setTextBoxLastStyle(!!Common.Utils.InternalSettings.get("pdfe-settings-textbox-last-style"))' in webapps(A + 'app/controller/LeftMenu.js'))
    check('web-apps: en.json has the label', 'txtTextBoxLastStyle"' in webapps(A + 'locale/en.json'))

    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

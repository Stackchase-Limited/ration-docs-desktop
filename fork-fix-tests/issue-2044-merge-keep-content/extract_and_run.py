#!/usr/bin/env python3
"""
#2044 - WPS-style "Merge and keep content" in the spreadsheet editor.

What there was: Merge / Merge & Center keep only the upper-left value (WorksheetView setSelectionInfo
"merge" -> Range.merge clears the rest, after the "data will be lost" warning that
getSelectionMergeInfo asks for). The reporter needs WPS's merge, which keeps every cell's content.

What now: the toolbar's Merge menu has "Merge and keep content" (web-apps view/Toolbar.js, both
layouts) = asc_mergeCells(c_oAscMergeOptions.MergeKeepContent). sdkjs collects the shown text of every
non-empty cell row by row, merges as Merge does, writes the texts joined by line breaks into the
upper-left cell as a string and turns on wrap. asc_mergeCellsDataLost reports no loss, so no warning.

This test runs REAL code: the sdkjs tree under test (RD_REPO; BASELINE=1: `git archive BASE_REF`) is
built (cell), a workbook is converted by x2t, and the cell editor runs in headless Chromium (stubbed
desktop host). On Src!B3:B6 - rich text "Big red", "plain styled" (Times 18 bold), 125.5 formatted
"$"#,##0.00, a two-line cell - it runs the menu's two calls (asc_mergeCellsDataLost, asc_mergeCells)
and then Undo. Checked: B3:B6 merged, B3 = "Big red\nplain styled\n$125.50\nline1\nline2" with wrap
on, no data-loss warning, one Undo restores the four cells; plain Merge still keeps only "Big red" and
still warns (unchanged). It also checks the web-apps menu item and en.json string (RD_WEBAPPS).

NOT claimed: the menu's look (GUI check); rich text formatting inside the joined text (not kept: the
merged cell has the upper-left cell's format); multi-range selections (only the last range is merged,
as for the other merge commands).

  python3 fork-fix-tests/issue-2044-merge-keep-content/extract_and_run.py
  RD_REPO=<sdkjs checkout> (default ../../sdkjs), RD_WEBAPPS=<web-apps> (default ../../web-apps),
  RD_X2T, RD_FONTS, RD_PLAYWRIGHT, RD_CHROME (see ../issue-2002-media-trim/media_c1.py)
  BASELINE=1 with BASE_REF / WEBAPPS_BASE_REF: there is no such option -> FAILS.
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
BASE_REF = os.environ.get('BASE_REF', 'aaa4ed4698^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', 'f6e57f4d84^')
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

    tmp = tempfile.mkdtemp(prefix='rd2044-')
    try:
        tree = build_cell(tmp)
        os.makedirs(os.path.join(tmp, 'c'))
        conv = h.setup_x2t(os.path.join(tmp, 'c'), x2t, tree)
        book = os.path.join(tmp, 'book.xlsx')
        run([sys.executable, os.path.join(HERE, 'mkbook.py'), book])
        binf = os.path.join(tmp, 'Editor.bin')
        h.convert(conv, book, binf, 8194)

        def editor(option):
            out = run(['node', os.path.join(HERE, 'merge_rt.js'), tree, binf, allfonts, option], timeout=600)
            return json.loads(out.strip().splitlines()[-1])

        before = {'B3': 'Big red', 'B4': 'plain styled', 'B5': '125.5', 'B6': 'line1\nline2', 'wrap': False, 'merged': None}
        k = editor('MergeKeepContent')
        print('Merge and keep content: ' + json.dumps(k['after']))
        check('the merge option MergeKeepContent exists', k['value'] == 4, str(k['value']))
        check('merge and keep content: B3:B6 merged, every text kept one per line, wrap on',
              k['after'] == {'B3': 'Big red\nplain styled\n$125.50\nline1\nline2', 'B4': '', 'B5': '', 'B6': '',
                             'wrap': True, 'merged': '2,1,5,1'} and not k['errors'], json.dumps([k['after'], k['errors']]))
        check('merge and keep content: no "data will be lost" warning', k['dataLost'] is False, str(k['dataLost']))
        check('merge and keep content: one Undo restores the cells', k['before'] == before and k['undone'] == before,
              json.dumps(k['undone']))
        m = editor('Merge')
        check('plain Merge unchanged: keeps the upper-left value only, warns',
              m['after'] == {'B3': 'Big red', 'B4': '', 'B5': '', 'B6': '', 'wrap': False, 'merged': '2,1,5,1'}
              and m['dataLost'] is True, json.dumps(m))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tb = webapps('apps/spreadsheeteditor/main/app/view/Toolbar.js')
    check('web-apps: both Merge menus offer MergeKeepContent with its caption',
          tb.count('value   : Asc.c_oAscMergeOptions.MergeKeepContent') == 2 and tb.count('caption : me.txtMergeKeepContent') == 2)
    check('web-apps: en.json has "Merge and keep content"',
          '"SSE.Views.Toolbar.txtMergeKeepContent": "Merge and keep content"' in webapps('apps/spreadsheeteditor/main/locale/en.json'))

    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
RD-0031 - a sheet copied to a new workbook could get the source's edits replayed on it
(our finding, from the #2045 triage lead).

Sheet tab > Move or Copy > "(new spreadsheet)": sdkjs copyToNewWorkbook writes the chosen
sheets' CURRENT state, the renderer stores it as EditorForAsLocal.bin in the source's
recovery folder (OpenWorkbook), and desktop-sdk cefview.cpp
CCefViewEditor::OpenCopyAsRecoverFile copies that folder and puts the binary in place of
Editor.bin. It kept the copied changes/changes0.json: the source's edits since it was
opened, recorded against its ORIGINAL Editor.bin. onlocaldocument_loadend
(client_renderer_wrapper.cpp) replays that file on top of the new binary, which already
holds those edits. sdkjs offsets change class ids by (binary size % 100)
(cell/api.js initGlobalObjects), so depending on the two sizes the replay is dropped
(unreadable), decodes as other classes, or applies cleanly to whatever sheet now has the
recorded sheet id - here, another sheet's inserted row and text land on the copy.
Fix: the copy's changes folder is deleted when a substitute binary is used.

Steps, all real code:
 1. x2t: a two-sheet xlsx -> Editor.bin. The real cell editor (headless Chromium, stubbed
    desktop host, sdkjs build from RD_SDKJS) opens it, types into Sheet1!A1, inserts a row
    on Sheet2 and types into its new A1, autosaves (the changes0.json the host writes) and
    runs copyToNewWorkbook([0]) (what OpenWorkbook receives). Sheet2's padding is chosen so
    both binaries give the same class-id offset - the case where the replay applies.
 2. The REAL OpenCopyAsRecoverFile, sliced from cefview.cpp (RD_REPO) by brace matching and
    compiled against stubs (file operations on a real temp folder), makes the new tab's
    recovery folder from that source folder.
 3. The real cell editor opens that folder the way onlocaldocument_loadend does (replays
    changes/changes0.json if it is there) and the copy's cells are checked.

Claimed: the new tab shows Sheet1 exactly as it was edited (no inserted row, no Sheet2
text); without the fix it shows Sheet2's row and text on it.
NOT claimed: the GUI flow (Move or Copy dialog, tab creation), word/slide "open binary as
new", the crypto compare path (EditorForCompare.bin) - same code path, not run here.

  python3 fork-fix-tests/rd-0031-copy-sheet-new-workbook/extract_and_run.py
  RD_REPO=<desktop-sdk checkout>  (default ../../desktop-sdk)
  RD_CORE=<core checkout>         (default ../../core; OfficeFileFormats.h)
  RD_SDKJS=<built sdkjs tree with deploy/> (default ../../sdkjs), RD_X2T, RD_FONTS,
  RD_PLAYWRIGHT, RD_CHROME (see ../issue-2002-media-trim/media_c1.py)
  BASELINE=1                      reads cefview.cpp from BASE_REF; must FAIL.
Exits 2 (CANNOT RUN) when x2t, the fonts cache, the sdkjs build or Playwright is missing.
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

REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '4b3f8ce5^')
BASELINE = bool(os.environ.get('BASELINE'))
CEFVIEW = 'ChromiumBasedEditors/lib/src/cefview.cpp'
FMT_XLSX, FMT_XLSY = 257, 8194


def read(rel):
    if BASELINE:
        return subprocess.check_output(['git', '-C', REPO, 'show', BASE_REF + ':' + rel]).decode('utf-8')
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


def braces(src, start):
    o = src.index('{', start)
    d = 0
    for i in range(o, len(src)):
        if src[i] == '{':
            d += 1
        elif src[i] == '}':
            d -= 1
            if d == 0:
                return src[start:i + 1]
    raise SystemExit('unbalanced braces')


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise SystemExit('command failed: ' + ' '.join(cmd[:3]))
    return r.stdout


STUBS = r'''
#include <string>
#include <vector>
#include <cstdio>
#include <filesystem>
#include <locale>
#include <codecvt>
#include "Common/OfficeFileFormats.h"
namespace fs = std::filesystem;
namespace NSStringUtils {
    void string_replace(std::wstring& t, const std::wstring& a, const std::wstring& b)
    { size_t p = 0; while ((p = t.find(a, p)) != std::wstring::npos) { t.replace(p, a.length(), b); p += b.length(); } }
}
namespace NSFile {
    std::wstring GetFileName(const std::wstring& s) { size_t p = s.find_last_of(L"/\\"); return p == std::wstring::npos ? s : s.substr(p + 1); }
    struct CFileBinary {
        static bool Exists(const std::wstring& p) { return fs::is_regular_file(p); }
        static bool Remove(const std::wstring& p) { return fs::remove(p); }
        static bool Copy(const std::wstring& a, const std::wstring& b) { return fs::copy_file(a, b, fs::copy_options::overwrite_existing); }
        static std::wstring CreateTempFileWithUniqueName(const std::wstring& root, const std::wstring& prefix)
        { std::wstring p = root + L"/" + prefix + L"_copy1"; FILE* f = fopen(fs::path(p).c_str(), "w"); if (f) fclose(f); return p; }
    };
}
namespace NSDirectory {
    bool Exists(const std::wstring& p) { return fs::is_directory(p); }
    void CopyDirectory(const std::wstring& a, const std::wstring& b) { fs::copy(a, b, fs::copy_options::recursive); }
    void DeleteDirectory(const std::wstring& p) { fs::remove_all(p); }
}
struct CInfo { std::wstring m_sRecoveryDir, m_sFileSrc; int m_nCurrentFileFormat = 0; bool m_bIsSaved = true; };
struct CLocalInfo { CInfo m_oInfo; };
struct CCefView;
struct CSettings { std::wstring recover_path, local_editors_path; };
struct CAppManagerInternal { std::wstring m_sAdditionalUrlParams; };
struct CAppManager {
    CSettings m_oSettings; CAppManagerInternal* m_pInternal = new CAppManagerInternal();
    CCefView* m_pSrc = nullptr; CCefView* GetViewById(int) { return m_pSrc; }
};
struct CCefViewInternal {
    CAppManager* m_pManager = nullptr; int m_nComparingMode = -1; CLocalInfo m_oLocalInfo;
    void LocalFile_Start() {}
};
struct CCefView { CCefViewInternal* m_pInternal = new CCefViewInternal(); };
struct CCefViewEditor : CCefView {
    std::wstring m_sLoaded;
    CAppManager* GetAppManager() { return m_pInternal->m_pManager; }
    std::wstring GetFileUrlParams(int, bool) { return L"filetype=xlsx"; }
    void load(const std::wstring& url) { m_sLoaded = url; }
    bool OpenCopyAsRecoverFile(const int& nIdSrc);
};
'''

MAIN = r'''
static std::wstring w(const char* s) { return std::wstring_convert<std::codecvt_utf8<wchar_t>>().from_bytes(s); }
static std::string u(const std::wstring& s) { return std::wstring_convert<std::codecvt_utf8<wchar_t>>().to_bytes(s); }
int main(int argc, char** argv)
{
    // argv: recover_path source_recovery_dir
    CAppManager app; app.m_oSettings.recover_path = w(argv[1]); app.m_oSettings.local_editors_path = L"/x/index.html";
    CCefView src; src.m_pInternal->m_pManager = &app; src.m_pInternal->m_oLocalInfo.m_oInfo.m_sRecoveryDir = w(argv[2]);
    src.m_pInternal->m_oLocalInfo.m_oInfo.m_sFileSrc = L"/home/u/book.xlsx";
    src.m_pInternal->m_oLocalInfo.m_oInfo.m_nCurrentFileFormat = AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSX;
    app.m_pSrc = &src;
    CCefViewEditor v; v.m_pInternal->m_pManager = &app;
    bool ok = v.OpenCopyAsRecoverFile(1);
    printf("%d\n%s\n", ok ? 1 : 0, u(v.m_pInternal->m_oLocalInfo.m_oInfo.m_sRecoveryDir).c_str());
    return 0;
}
'''

failures = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('  ' + detail) if detail and not cond else ''))
    if not cond:
        failures.append(name)


def cannot(what):
    print('CANNOT RUN: ' + what)
    sys.exit(2)


def main():
    x2t = h.find_x2t(False)
    allfonts = os.path.join(h.FONTS, 'AllFonts.js')
    cell = os.path.join(h.SDKJS, 'deploy', 'sdkjs', 'cell', 'sdk-all-min.js')
    pw = os.environ.get('RD_PLAYWRIGHT') or '/Users/osindero/dev/active/node_modules/playwright'
    for p, what in ((x2t, 'x2t'), (allfonts, 'fonts cache'), (cell, 'sdkjs cell build'), (pw, 'playwright')):
        if not os.path.exists(p):
            cannot('missing %s (%s)' % (what, p))

    tmp = tempfile.mkdtemp(prefix='rd0031-')
    try:
        os.makedirs(os.path.join(tmp, 'c'))
        conv = h.setup_x2t(os.path.join(tmp, 'c'), x2t, h.SDKJS)

        def editor(*args):
            out = run(['node', os.path.join(HERE, 'cell_rt.js')] + list(args[:1]) + [h.SDKJS] + list(args[1:2]) + [allfonts] + list(args[2:]), timeout=600)
            return json.loads(out.strip().splitlines()[-1])

        def source(pad, name):
            book = os.path.join(tmp, name + '.xlsx')
            run([sys.executable, os.path.join(HERE, 'mkbook.py'), book, str(pad)])
            d = os.path.join(tmp, name)
            os.makedirs(os.path.join(d, 'changes'))
            os.makedirs(os.path.join(d, 'media'))
            h.convert(conv, book, os.path.join(d, 'Editor.bin'), FMT_XLSY)
            r = editor('source', os.path.join(d, 'Editor.bin'), os.path.join(tmp, name + '-out'), '0')
            shutil.move(os.path.join(tmp, name + '-out', 'changes0.json'), os.path.join(d, 'changes', 'changes0.json'))
            shutil.move(os.path.join(tmp, name + '-out', 'EditorForAsLocal.bin'), os.path.join(d, 'EditorForAsLocal.bin'))
            return d, r

        # 1. find the Sheet2 padding that gives the source binary the copy's class-id offset
        d0, _ = source(10, 'probe')
        src0 = os.path.getsize(os.path.join(d0, 'Editor.bin'))
        copy = os.path.getsize(os.path.join(d0, 'EditorForAsLocal.bin'))
        pad = 10 + ((copy - src0) % 100) // 2
        if (copy - src0) % 2:
            cannot('binary sizes of different parity (%d, %d): cannot align the offsets' % (src0, copy))
        d, r = source(pad, 'book')
        sizes = (os.path.getsize(os.path.join(d, 'Editor.bin')), os.path.getsize(os.path.join(d, 'EditorForAsLocal.bin')))
        print('source Editor.bin %d bytes, copy %d bytes (class-id offsets %d / %d)' % (sizes + (sizes[0] % 100, sizes[1] % 100)))
        edited = r['edited'][0]['cells']
        check('source session: Sheet1 edited, Sheet2 got the row', edited.get('A1') == 'typed on Sheet1'
              and r['edited'][1]['cells'].get('A1') == 'typed on Sheet2', json.dumps(r['edited']))

        # 2. the real OpenCopyAsRecoverFile makes the new tab's folder
        src = read(CEFVIEW)
        fn = braces(src, src.index('bool CCefViewEditor::OpenCopyAsRecoverFile(const int& nIdSrc)'))
        assert 'EditorForAsLocal.bin' in fn, 'sliced the wrong function'
        cpp = os.path.join(tmp, 'copy.cpp')
        with open(cpp, 'w') as f:
            f.write(STUBS + fn + MAIN)
        run(['c++', '-std=c++17', '-Wno-deprecated-declarations', '-I' + CORE, cpp, '-o', os.path.join(tmp, 'copy')])
        rec = os.path.join(tmp, 'recover')
        os.makedirs(rec)
        out = run([os.path.join(tmp, 'copy'), rec, d]).split('\n')
        newdir = out[1]
        check('OpenCopyAsRecoverFile made the new folder', out[0] == '1' and os.path.isfile(os.path.join(newdir, 'Editor.bin')))
        with open(os.path.join(newdir, 'Editor.bin'), 'rb') as a, open(os.path.join(d, 'EditorForAsLocal.bin'), 'rb') as b:
            check('the new Editor.bin is the copied sheets binary', a.read() == b.read())
        ch = os.path.join(newdir, 'changes', 'changes0.json')
        check('the source edits are not left in the new folder to be replayed', not os.path.exists(ch))

        # 3. open it as onlocaldocument_loadend does
        t = editor('open', os.path.join(newdir, 'Editor.bin'), ch if os.path.exists(ch) else '-')
        print('new tab: ' + json.dumps(t['sheets']))
        want = {'A1': 'typed on Sheet1', 'B1': '11', 'A2': 'S1 row2', 'B2': '12'}
        check('new tab shows Sheet1 as edited, nothing of Sheet2 on it',
              len(t['sheets']) == 1 and t['sheets'][0]['cells'] == want and not t['errors'], json.dumps(t))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', len(failures)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

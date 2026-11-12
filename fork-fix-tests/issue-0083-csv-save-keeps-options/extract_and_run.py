#!/usr/bin/env python3
"""
#83 - "Change CSV delimiter/separator when saving". The part of it that is a data
integrity bug: a csv opened with a semicolon delimiter or a non-UTF-8 code page
(chosen in the open dialog) was written back by Ctrl+S as a comma-separated UTF-8
file - every other program then reads it wrong. Checked by running x2t: a
windows-1251 semicolon csv opened with the dialog's options and saved with the
parameters the desktop sent came out as UTF-8 with a BOM and commas.

Cause: desktop-sdk ChromiumBasedEditors/lib/src/fileconverter.h,
CASCFileConverterFromEditor::ThreadProc always wrote <m_nCsvTxtEncoding>46 and the
format's delimiter (4 = comma for CSV); the options the user chose on open
(on_setadvancedoptions in cefview.cpp) went to the open conversion only and were
then forgotten.

Fix: on_setadvancedoptions keeps the csv elements (CsvOptions_FromAdvanced) in
CAscLocalFileInfo::m_sCsvOptions; the save writes them back
(CsvOptions_ForSave). A format picked in Save As (LocalFile_SaveStart with a type)
clears them, so it is written with that format's own options - today's behaviour -
and LocalFile_SaveEnd takes over what was saved. Also: SCSV ("CSV File,
semicolon-separated") is now offered in Save As (cefview.cpp
LocalFile_GetSupportSaveFormats, was commented out), the cheapest step towards
choosing the delimiter on save.

How it is tested: the REAL code is extracted by brace matching / statement
slicing and compiled against small stubs:
  - the #83 block of the on_setadvancedoptions handler (cefview.cpp),
  - the `if (nType != -1)` statement of LocalFile_SaveStart (cefview.cpp),
  - the csv part of the save parameters in CASCFileConverterFromEditor::ThreadProc
    plus the helpers it calls (fileconverter.h),
  - the SCSV entry of LocalFile_GetSupportSaveFormats.
Scenarios: open with windows-1251 + ';' then Ctrl+S; open with a custom '|'; Save As
CSV after that (must be comma/UTF-8 again); a file with no open options (xlsx Save As
CSV); and TSV. If x2t and a fonts cache are available (RD_X2T, RD_FONTS; defaults
.rd-work/payload/converter and the test app's fonts cache), the Ctrl+S parameters
are also handed to the real x2t: open the 1251/';' file, save with them, and the
output must be byte-identical to the input.
With BASELINE=1 (sources from `git show $BASE_REF:`) the save parameters say 46/comma
and SCSV is not offered: the test FAILS.

  ./extract_and_run.py            RD_REPO (default ../../desktop-sdk), must PASS
  BASELINE=1 ./extract_and_run.py BASE_REF, must FAIL

NOT claimed: the CEF IPC and the open dialog itself (that the web-apps CSV dialog
sends these elements is read from sdkjs cell/Local/api.js asc_setAdvancedOptions);
the macOS/Windows/Linux Save As panels' new SCSV entry (desktop-apps) needs a GUI
check. Encoding loss is possible by design: a character typed into a windows-1251
file that 1251 cannot hold is lost on Ctrl+S, as in other spreadsheet programs -
Save As CSV writes UTF-8 as before.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk')))
CORE = os.path.abspath(os.environ.get('RD_CORE', os.path.join(HERE, '..', '..', 'core')))
BASE_REF = os.environ.get('BASE_REF', '6afd78af^')
BASELINE = bool(os.environ.get('BASELINE'))
CEFVIEW = 'ChromiumBasedEditors/lib/src/cefview.cpp'
FILECONV = 'ChromiumBasedEditors/lib/src/fileconverter.h'
RDWORK = os.path.abspath(os.path.join(HERE, '..', '..', '..', '.rd-work'))
X2T_DIR = os.environ.get('RD_X2T', os.path.join(RDWORK, 'payload', 'converter'))
FONTS = os.environ.get('RD_FONTS', os.path.expanduser(
    '~/Library/Application Support/com.stackchase.rationdocs.test/data/fonts'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', SDK, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(SDK, rel), encoding='utf-8').read()


def brace_match(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces from offset %d' % start)


def statement(text, start):
    """an if statement: braced body, or up to the first ';'"""
    head_end = text.index(')', start) + 1
    rest = text[head_end:]
    if rest.lstrip().startswith('{'):
        return brace_match(text, start)
    return text[start:text.index(';', head_end) + 1]


cef = read(CEFVIEW)
fc = read(FILECONV)

# 1. on_setadvancedoptions: the #83 block (absent on the baseline)
at = cef.find('message_name == "on_setadvancedoptions"')
if at == -1:
    raise SystemExit('on_setadvancedoptions handler not found')
handler = brace_match(cef, at)
m = re.search(r'\n\s*if \(m_pParent->m_pInternal->m_oConverterToEditor\.m_sComparingFile\.empty\(\)\)', handler)
record_block = brace_match(handler, m.start() + 1) if m else ''

# 2. LocalFile_SaveStart: the `if (nType != -1)` statement
at = cef.find('void LocalFile_SaveStart(')
save_start = brace_match(cef, at)
m = re.search(r'if \(nType != -1\)', save_start)
savestart_stmt = statement(save_start, m.start())

# 3. LocalFile_SaveEnd: the statements that take over the saved file's info
at = cef.find('void CCefView_Private::LocalFile_SaveEnd(')
save_end = brace_match(cef, at)
m = re.search(r'm_oLocalInfo\.m_oInfo\.m_sFileSrc = m_oConverterFromEditor\.m_oInfo\.m_sFileSrc;', save_end)
end_stop = save_end.index('CheckLockLocalFile();', m.start())
saveend_stmts = save_end[m.start():end_stop]

# 4. the csv part of the save parameters
at = fc.find('class CASCFileConverterFromEditor')
conv = fc[at:]
s0 = conv.index('oBuilder.WriteString(L"/AllFonts.js</m_sAllFontsPath>')
s1 = conv.index('if (!m_oInfo.m_sOldPassword.empty()', s0)
save_params = conv[s0:s1]

helpers = ''
for name in ('static std::wstring CsvOptions_FromAdvanced(', 'static std::wstring CsvOptions_ForSave('):
    p = fc.find(name)
    if p != -1:
        helpers += brace_match(fc, p) + '\n'

# 5. the spreadsheet save formats offered
at = cef.find('LocalFile_GetSupportSaveFormats(')
formats = brace_match(cef, at)
offers_scsv = re.search(r'^\s*arFormats\.push_back\(AVS_OFFICESTUDIO_FILE_SPREADSHEET_SCSV\);', formats, re.M) is not None

HARNESS = r'''
#include <string>
#include <stdio.h>
#include "Common/OfficeFileFormats.h"

%(helpers)s

struct CStringBuilder { std::wstring s; void WriteString(const std::wstring& w) { s += w; } };
struct CRITICAL_SECTION {};
struct CTemporaryCS { CTemporaryCS(CRITICAL_SECTION*) {} };
struct CInfo { int m_nCurrentFileFormat = 0; std::wstring m_sFileSrc; std::wstring m_sCsvOptions; };
struct CLocalInfo { CRITICAL_SECTION m_oCS; CInfo m_oInfo; };
struct CToEditor { std::wstring m_sAdditionalConvertation; std::wstring m_sComparingFile; };
struct CFromEditor { CInfo m_oInfo; };
struct CPrivate { CLocalInfo m_oLocalInfo; CToEditor m_oConverterToEditor; CFromEditor m_oConverterFromEditor; };
struct CParent { CPrivate* m_pInternal; };

struct View
{
    CPrivate oPriv; CParent oParent{&oPriv}; CParent* m_pParent = &oParent;
    CLocalInfo& m_oLocalInfo = oPriv.m_oLocalInfo;
    CFromEditor& m_oConverterFromEditor = oPriv.m_oConverterFromEditor;

    void OnSetAdvancedOptions(const std::wstring& sArg)   /* the handler's #83 block */
    {
        m_pParent->m_pInternal->m_oConverterToEditor.m_sAdditionalConvertation = sArg;
        %(record_block)s
    }
    void SaveStart(int nType)                              /* SetupOptions + the real if */
    {
        m_oConverterFromEditor.m_oInfo = m_oLocalInfo.m_oInfo;
        %(savestart_stmt)s
    }
    std::wstring SaveParams()                              /* the real csv part of ThreadProc */
    {
        CStringBuilder oBuilder; std::wstring sParams = L"<m_sFontDir>F</m_sFontDir>";
        CInfo& m_oInfo = m_oConverterFromEditor.m_oInfo;
        %(save_params)s
        return oBuilder.s;
    }
    void SaveEnd()                                         /* saved: the real take-over */
    {
        %(saveend_stmts)s
    }
};

static std::string A(const std::wstring& w) { std::string s; for (wchar_t c : w) s += (char)c; return s; }
static std::string csvpart(const std::wstring& p)
{
    std::wstring r; size_t i = p.find(L"<m_nCsv");
    while (i != std::wstring::npos) { size_t e = p.find(L">", p.find(L"</", i)); r += p.substr(i, e + 1 - i); i = p.find(L"<m_nCsv", e); }
    return A(r);
}
static int failures = 0;
static void expect(const char* what, const std::string& got, const std::string& want)
{
    bool ok = got == want;
    printf("  %%-52s %%s  %%s\n", what, got.c_str(), ok ? "ok" : ("FAILED, want " + want).c_str());
    if (!ok) failures++;
}

int main(int argc, char** argv)
{
    const int CSV = AVS_OFFICESTUDIO_FILE_SPREADSHEET_CSV, TSV = AVS_OFFICESTUDIO_FILE_SPREADSHEET_TSV;
    printf("#83 csv save parameters:\n");
    {
        View v; v.m_oLocalInfo.m_oInfo.m_nCurrentFileFormat = CSV;
        v.OnSetAdvancedOptions(L"<m_nCsvTxtEncoding>1251</m_nCsvTxtEncoding><m_nCsvDelimiter>2</m_nCsvDelimiter>");
        v.SaveStart(-1);
        std::string p = csvpart(v.SaveParams());
        expect("opened 1251 + ';', Ctrl+S", p, "<m_nCsvTxtEncoding>1251</m_nCsvTxtEncoding><m_nCsvDelimiter>2</m_nCsvDelimiter>");
        if (argc > 1) { FILE* f = fopen(argv[1], "w"); fputs(A(v.SaveParams()).c_str(), f); fclose(f); }
        v.SaveEnd();
        v.SaveStart(-1);
        expect("  ... and Ctrl+S again", csvpart(v.SaveParams()), p);
        v.SaveStart(CSV); v.SaveEnd();
        expect("  ... then Save As CSV (explicit format)", csvpart(v.SaveParams()), "<m_nCsvTxtEncoding>46</m_nCsvTxtEncoding><m_nCsvDelimiter>4</m_nCsvDelimiter>");
        v.SaveStart(-1);
        expect("  ... then Ctrl+S on what Save As wrote", csvpart(v.SaveParams()), "<m_nCsvTxtEncoding>46</m_nCsvTxtEncoding><m_nCsvDelimiter>4</m_nCsvDelimiter>");
    }
    {
        View v; v.m_oLocalInfo.m_oInfo.m_nCurrentFileFormat = CSV;
        v.OnSetAdvancedOptions(L"<m_nCsvTxtEncoding>46</m_nCsvTxtEncoding><m_nCsvDelimiter>0</m_nCsvDelimiter><m_nCsvDelimiterChar>|</m_nCsvDelimiterChar>");
        v.SaveStart(-1);
        expect("opened UTF-8 + custom '|', Ctrl+S", csvpart(v.SaveParams()), "<m_nCsvTxtEncoding>46</m_nCsvTxtEncoding><m_nCsvDelimiter>0</m_nCsvDelimiter><m_nCsvDelimiterChar>|</m_nCsvDelimiterChar>");
    }
    {
        View v; v.m_oLocalInfo.m_oInfo.m_nCurrentFileFormat = AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSX;
        v.OnSetAdvancedOptions(L"<m_sPassword>x</m_sPassword>");
        v.SaveStart(CSV);
        expect("xlsx (password) Save As CSV - unchanged", csvpart(v.SaveParams()), "<m_nCsvTxtEncoding>46</m_nCsvTxtEncoding><m_nCsvDelimiter>4</m_nCsvDelimiter>");
    }
    {
        View v; v.m_oLocalInfo.m_oInfo.m_nCurrentFileFormat = TSV;
        v.OnSetAdvancedOptions(L"<m_nCsvTxtEncoding>1252</m_nCsvTxtEncoding><m_nCsvDelimiter>1</m_nCsvDelimiter>");
        v.SaveStart(-1);
        expect("tsv opened 1252, Ctrl+S", csvpart(v.SaveParams()), "<m_nCsvTxtEncoding>1252</m_nCsvTxtEncoding><m_nCsvDelimiter>1</m_nCsvDelimiter>");
    }
    {
        View v; v.m_oLocalInfo.m_oInfo.m_nCurrentFileFormat = CSV;
        v.SaveStart(AVS_OFFICESTUDIO_FILE_SPREADSHEET_SCSV);
        expect("Save As SCSV", csvpart(v.SaveParams()), "<m_nCsvTxtEncoding>46</m_nCsvTxtEncoding><m_nCsvDelimiter>2</m_nCsvDelimiter>");
    }
    return failures ? 1 : 0;
}
''' % dict(helpers=helpers, record_block=record_block, savestart_stmt=savestart_stmt,
           save_params=save_params, saveend_stmts=saveend_stmts)

tmp = tempfile.mkdtemp(prefix='rd83-')
try:
    src = os.path.join(tmp, 't.cpp')
    exe = os.path.join(tmp, 't')
    open(src, 'w').write(HARNESS)
    cxx = shutil.which('clang++') or shutil.which('g++')
    subprocess.run([cxx, '-std=c++17', '-w', '-I', CORE, src, '-o', exe], check=True)
    params_file = os.path.join(tmp, 'save_params.xml')
    r = subprocess.run([exe, params_file])
    failures = r.returncode != 0

    print('#83 Save As offers SCSV (semicolon csv):  %s' % ('yes  ok' if offers_scsv else 'no  FAILED'))
    failures = failures or not offers_scsv

    x2t = os.path.join(X2T_DIR, 'x2t')
    if os.path.exists(x2t) and os.path.exists(os.path.join(FONTS, 'font_selection.bin')):
        # the real converter: open a windows-1251 ';' csv with the dialog's options, then
        # save it with the Ctrl+S parameters produced above
        csv_in = os.path.join(tmp, 'in.csv')
        open(csv_in, 'wb').write('Name;Город;Amount\nA;Привет;1,5\nB;Мир;2\n'.encode('cp1251'))
        env = dict(os.environ, DYLD_FRAMEWORK_PATH=X2T_DIR, DYLD_LIBRARY_PATH=X2T_DIR, LD_LIBRARY_PATH=X2T_DIR)

        def x2t_run(src_, dst, fmt, extra):
            os.makedirs(os.path.join(tmp, 'x2ttmp'), exist_ok=True)
            p = os.path.join(tmp, 'p.xml')
            open(p, 'w').write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert>'
                               '<m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo><m_nFormatTo>%d</m_nFormatTo>'
                               '<m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath><m_sTempDir>%s/x2ttmp</m_sTempDir>'
                               '%s</TaskQueueDataConvert>' % (src_, dst, fmt, FONTS, tmp, extra))
            return subprocess.run([x2t, p], env=env, capture_output=True).returncode

        rc1 = x2t_run(csv_in, os.path.join(tmp, 'Editor.bin'), 8194,
                      '<m_sFontDir>%s</m_sFontDir><m_nCsvTxtEncoding>1251</m_nCsvTxtEncoding><m_nCsvDelimiter>2</m_nCsvDelimiter>' % FONTS)
        # the slice starts inside the m_sAllFontsPath element; the harness writes its own
        saved = open(params_file).read().replace('/AllFonts.js</m_sAllFontsPath>', '', 1)
        saved = saved.replace('<m_sFontDir>F</m_sFontDir>', '<m_sFontDir>%s</m_sFontDir>' % FONTS)
        out = os.path.join(tmp, 'out.csv')
        rc2 = x2t_run(os.path.join(tmp, 'Editor.bin'), out, 260, saved)
        same = rc1 == 0 and rc2 == 0 and open(out, 'rb').read() == open(csv_in, 'rb').read()
        head = open(out, 'rb').read()[:24] if os.path.exists(out) else b''
        print('#83 x2t: 1251 ";" csv opened, Ctrl+S -> %s  %s' % (head, 'identical  ok' if same else 'differs  FAILED'))
        failures = failures or not same
    else:
        print('#83 x2t round trip skipped (no x2t at %s or no fonts cache at %s)' % (X2T_DIR, FONTS))

    print('FAIL' if failures else 'PASS')
    sys.exit(1 if failures else 0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

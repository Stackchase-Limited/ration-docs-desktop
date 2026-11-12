#!/usr/bin/env python3
"""
#982 - "Add ability to export file in another format without changing file
format". In the desktop app, Save As was the only way to write a document in
another format, and it made the written file the open document: after Save As
CSV a workbook was a CSV (title, path, format, file lock), and the next Ctrl+S
wrote CSV again. Only formats the editor cannot switch to (a docx saved as
pdf, images) left the open document alone. The online editors have "Save Copy
as...", but the item was hidden in the desktop app.

Where: desktop-sdk cefview.cpp LocalFileSaveEnd_CheckSaveAs decides after a
Save As whether the written file becomes the open document (true for any
format LocalFile_IsSupportEditFormat accepts, e.g. xlsx -> csv, docx -> odt).

Fix, three repos:
- web-apps: File > "Save Copy as..." (existing, translated item) is shown in
  the desktop document, spreadsheet, presentation and PDF editors; it calls
  asc_DownloadAs with asc_CDownloadOptions.asc_setIsSaveCopy(true).
- sdkjs: DesktopOfflineAppDocumentStartSave (word/pdf, cell, slide, visio)
  adds "savecopy=true;" to the Save As parameters for such options.
- desktop-sdk: onlocaldocument_onsavestart reads it into m_bIsSaveCopy;
  LocalFileSaveEnd_CheckSaveAs then answers "not the current file" - the
  existing Save As to pdf path: the file is written and added to recents, the
  open document keeps its path, format and lock and stays modified. The flag
  is cleared in LocalFile_SaveEnd.

This test:
- compiles the REAL LocalFileSaveEnd_CheckSaveAs and LocalFile_IsSupportEditFormat
  (brace matched from cefview.cpp) with the REAL core OfficeFileFormats.h into
  a stub CCefView_Private and asks it about xlsx -> csv, docx -> odt, docx ->
  pdf with and without the copy flag; compiles the REAL two lines of
  onlocaldocument_onsavestart that parse the parameters; checks by text that
  LocalFile_SaveEnd clears the flag;
- runs js_checks.js: the REAL asc_CDownloadOptions, the REAL
  DesktopOfflineAppDocumentStartSave of the four editors with a recording
  AscDesktopEditor.LocalFileSave, and the REAL web-apps FileMenu visibility
  statement and clickMenuFileItem of the four editors.

  RD_REPO=<desktop-sdk> RD_SDKJS=<sdkjs> RD_WEBAPPS=<web-apps> RD_CORE=<core>
  (defaults ../../<name>). BASELINE=1 reads desktop-sdk at BASE_REF, sdkjs at
  SDKJS_BASE_REF and web-apps at WEBAPPS_BASE_REF -> must FAIL (a copy to csv
  becomes the open document; no savecopy parameter; no menu item).

NOT claimed: the save dialog and the whole save in the running app (GUI check:
open an xlsx, File > Save Copy as > CSV, the tab must still say .xlsx and
Ctrl+S must write the xlsx); that x2t writes the copy (unchanged path).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
def repo(env, name):
    return os.environ.get(env) or os.path.normpath(os.path.join(HERE, '..', '..', name))
SDK = repo('RD_REPO', 'desktop-sdk')
SDKJS = repo('RD_SDKJS', 'sdkjs')
WEBAPPS = repo('RD_WEBAPPS', 'web-apps')
CORE = repo('RD_CORE', 'core')
BASELINE = bool(os.environ.get('BASELINE'))
# Pinned to the parents of the commits that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '37781973^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', 'ab8d889574^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', '08a278ff9c^')

CEFVIEW = 'ChromiumBasedEditors/lib/src/cefview.cpp'
if BASELINE:
    src = subprocess.check_output(['git', '-C', SDK, 'show', BASE_REF + ':' + CEFVIEW], text=True)
else:
    src = open(os.path.join(SDK, CEFVIEW), encoding='utf-8').read()

def braced(text, start):
    i = text.index('{', start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise ValueError('unbalanced')

check_save_as = braced(src, src.index('bool CCefView_Private::LocalFileSaveEnd_CheckSaveAs()'))
is_edit = braced(src, src.index('bool LocalFile_IsSupportEditFormat(int nFormat)'))
save_end = braced(src, src.index('void CCefView_Private::LocalFile_SaveEnd(int nError'))
on_start = braced(src, src.index('message_name == "onlocaldocument_onsavestart"'))
parse = [l.strip() for l in on_start.splitlines() if 'saveas=true' in l or 'savecopy=true' in l]
parse = [l.replace('m_pParent->m_pInternal->', 'p->') for l in parse]

cpp = r'''
#include <string>
#include <cstdio>
#include "Common/OfficeFileFormats.h"
struct Info { int m_nCurrentFileFormat; };
struct LocalInfo { Info m_oInfo; };
struct Converter { Info m_oInfo; };
class CCefView_Private
{
public:
	LocalInfo m_oLocalInfo;
	Converter m_oConverterFromEditor;
	bool m_bIsSaveCopy = false;
	bool LocalFile_IsSupportEditFormat(int nFormat) %s
	bool LocalFileSaveEnd_CheckSaveAs();
};
bool CCefView_Private::LocalFileSaveEnd_CheckSaveAs() %s

static bool ParseCopy(const std::string& sParams)
{
	CCefView_Private o, *p = &o;
	%s
	(void)bIsSaveAs;
	return p->m_bIsSaveCopy;
}
static const char* Run(int from, int to, bool copy)
{
	CCefView_Private o;
	o.m_oLocalInfo.m_oInfo.m_nCurrentFileFormat = from;
	o.m_oConverterFromEditor.m_oInfo.m_nCurrentFileFormat = to;
	o.m_bIsSaveCopy = copy;
	return o.LocalFileSaveEnd_CheckSaveAs() ? "becomes the open doc" : "open doc unchanged";
}
int main()
{
	printf("xlsx -> csv, Save As|%%s\n", Run(AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSX, AVS_OFFICESTUDIO_FILE_SPREADSHEET_CSV, false));
	printf("xlsx -> csv, Save Copy as|%%s\n", Run(AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSX, AVS_OFFICESTUDIO_FILE_SPREADSHEET_CSV, true));
	printf("docx -> odt, Save As|%%s\n", Run(AVS_OFFICESTUDIO_FILE_DOCUMENT_DOCX, AVS_OFFICESTUDIO_FILE_DOCUMENT_ODT, false));
	printf("docx -> odt, Save Copy as|%%s\n", Run(AVS_OFFICESTUDIO_FILE_DOCUMENT_DOCX, AVS_OFFICESTUDIO_FILE_DOCUMENT_ODT, true));
	printf("docx -> pdf, Save As|%%s\n", Run(AVS_OFFICESTUDIO_FILE_DOCUMENT_DOCX, AVS_OFFICESTUDIO_FILE_CROSSPLATFORM_PDF, false));
	printf("params saveas=true;savecopy=true; sets the flag|%%d\n", ParseCopy("saveas=true;savecopy=true;"));
	printf("params saveas=true; sets the flag|%%d\n", ParseCopy("saveas=true;"));
	printf("params savecopy=true; without saveas sets the flag|%%d\n", ParseCopy("savecopy=true;"));
	return 0;
}
''' % (is_edit, check_save_as, '\n\t'.join(parse) if len(parse) == 2 else 'bool bIsSaveAs = false; /* no savecopy parsing */')

want = {
    'xlsx -> csv, Save As': 'becomes the open doc',
    'xlsx -> csv, Save Copy as': 'open doc unchanged',
    'docx -> odt, Save As': 'becomes the open doc',
    'docx -> odt, Save Copy as': 'open doc unchanged',
    'docx -> pdf, Save As': 'open doc unchanged',
    'params saveas=true;savecopy=true; sets the flag': '1',
    'params saveas=true; sets the flag': '0',
    'params savecopy=true; without saveas sets the flag': '0',
}

failures = 0
sys.stdout.reconfigure(line_buffering=True)
print('desktop-sdk ' + ('@ ' + BASE_REF if BASELINE else SDK))
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, 't.cpp'), 'w') as f:
        f.write(cpp)
    exe = os.path.join(tmp, 't')
    subprocess.check_call(['c++', '-std=c++11', '-I' + CORE, os.path.join(tmp, 't.cpp'), '-o', exe])
    for line in subprocess.check_output([exe], text=True).splitlines():
        what, got = line.split('|')
        ok = want.pop(what) == got
        failures += not ok
        print('  %-66s %-24s %s' % (what, got, 'ok' if ok else 'FAILED'))
    assert not want, want

cleared = re.search(r'LocalFileSaveEnd_CheckSaveAs\(\);\s*m_bIsSaveCopy = false;', save_end) is not None
failures += not cleared
print('  %-66s %-24s %s' % ('LocalFile_SaveEnd clears the copy flag', cleared, 'ok' if cleared else 'FAILED'))

js = subprocess.run(['node', os.path.join(HERE, 'js_checks.js'),
                     SDKJS, SDKJS_BASE_REF if BASELINE else '', WEBAPPS, WEBAPPS_BASE_REF if BASELINE else ''])
failures += js.returncode != 0

print('\nFAILED' if failures else '\nok - Save Copy as writes another format and leaves the open document as it was')
sys.exit(1 if failures else 0)

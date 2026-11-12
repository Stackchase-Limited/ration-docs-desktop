#!/usr/bin/env python3
"""
#517 - "Choose default saving format in Settings". People who keep their files
in OpenDocument had to change the type in the save dialog of every new
document: desktop-sdk cefview.cpp (onlocaldocument_onsavestart) always
preselected the editor's own format, m_nCurrentFileFormat - docx/xlsx/pptx
for a new document (CCefViewEditor::CreateLocalFile).

Added as an OPTION, default unchanged:
- web-apps: Advanced settings > "Format for new documents" in the document,
  spreadsheet and presentation editors (desktop, editing): Office Open XML
  (default) or OpenDocument; one setting, app-settings-new-file-odf. Main.js
  (load) and LeftMenu.applySettings pass ODT/ODS/ODP or 0 to the api.
- sdkjs: asc_setNewFileSaveFormat (common/Local/common.js); the desktop
  DesktopOfflineAppDocumentStartSave of word/cell/slide adds
  "newformat=<type>;" when set.
- desktop-sdk: CreateLocalFile marks the view as a new document
  (m_bIsNewLocalFile, cleared when a save succeeds); for the first save of
  such a document with all formats on offer, onsavestart preselects the
  format (LocalFile_GetNewFileSaveFormat: only if it is in the offered list)
  and gives the suggested name its extension (LocalFile_ChangeExtension):
  macOS selects the type (ASCSavePanelWithFormatController original type),
  Windows/Linux the filter matching the name's extension (cfiledialog).

This test compiles the REAL LocalFile_GetNewFileSaveFormat and
LocalFile_ChangeExtension and the REAL #517 block of onsavestart (brace
matched from cefview.cpp) with the REAL core GetExtensionByType (brace matched
from OfficeFileFormatChecker2.cpp) and OfficeFileFormats.h against a stub
dialog-data object, and checks by text that CreateLocalFile sets and
LocalFile_SaveEnd clears the flag. js_checks.js runs the REAL sdkjs setter and
save-start functions and the REAL web-apps load/apply statements.

  RD_REPO=<desktop-sdk> RD_SDKJS=<sdkjs> RD_WEBAPPS=<web-apps> RD_CORE=<core>
  BASELINE=1 -> desktop-sdk at BASE_REF, sdkjs at SDKJS_BASE_REF, web-apps at
  WEBAPPS_BASE_REF: must FAIL (docx always preselected, no setting).

NOT claimed: the dialogs as drawn on each platform and the settings panel
(GUI check: set OpenDocument, File > New document, Ctrl+S -> "ODT" selected
and name ends .odt); that ODF round trips are lossless (upstream x2t, and the
thread notes ODP arrows - that is why the default stays OOXML).
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
BASE_REF = os.environ.get('BASE_REF', '3ce41d06^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', 'b5d8ce9cd5^')
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', 'ed400de638^')

CEFVIEW = 'ChromiumBasedEditors/lib/src/cefview.cpp'
if BASELINE:
    src = subprocess.check_output(['git', '-C', SDK, 'show', BASE_REF + ':' + CEFVIEW], text=True)
else:
    src = open(os.path.join(SDK, CEFVIEW), encoding='utf-8').read()
checker = open(os.path.join(CORE, 'Common/OfficeFileFormatChecker2.cpp'), encoding='utf-8', errors='replace').read()

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

def func(sig):
    at = src.find(sig)
    return None if at < 0 else sig + ' ' + braced(src, at)

get_fmt = func('static int LocalFile_GetNewFileSaveFormat(const std::string& sParams, const std::vector<int>& arFormats)') \
    or 'static int LocalFile_GetNewFileSaveFormat(const std::string&, const std::vector<int>&) { return 0; }'
change_ext = func('static std::wstring LocalFile_ChangeExtension(const std::wstring& sName, const std::wstring& sExt)') \
    or 'static std::wstring LocalFile_ChangeExtension(const std::wstring& s, const std::wstring&) { return s; }'
on_start = braced(src, src.index('message_name == "onlocaldocument_onsavestart"'))
m = re.search(r'if \(bIsNeedSave && nSaveFileType == 0 && m_pParent->m_pInternal->m_bIsNewLocalFile\)', on_start)
block = (m.group(0) + braced(on_start, m.start())) if m else '/* no #517 block */'
ext_body = braced(checker, checker.index('std::wstring COfficeFileFormatChecker::GetExtensionByType(int type)'))

cpp = r'''
#include <string>
#include <vector>
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include "Common/OfficeFileFormats.h"
static std::wstring RealGetExtensionByType(int type) %(ext)s
struct COfficeFileFormatChecker { std::wstring GetExtensionByType(int t) { return RealGetExtensionByType(t); } };
struct Dialog
{
	int type; std::wstring path; std::vector<int> formats;
	void put_FileType(int t) { type = t; }
	void put_Path(const std::wstring& p) { path = p; }
	const std::wstring& get_Path() { return path; }
	std::vector<int>& get_SupportFormats() { return formats; }
};
struct Internal { bool m_bIsNewLocalFile; };
struct Parent { Internal* m_pInternal; };
%(get_fmt)s
%(change_ext)s
static void Run(const char* what, bool bIsNeedSave, bool bNew, int nSaveFileType, const std::string& sParams, int cur, const wchar_t* name, const std::vector<int>& offered)
{
	Internal in = { bNew }; Parent par = { &in }; Parent* m_pParent = &par;
	Dialog o; Dialog* pData = &o;
	pData->put_FileType(cur); pData->put_Path(name); pData->formats = offered;
	%(block)s
	std::string n(o.path.begin(), o.path.end());
	printf("%%s|%%d %%s\n", what, o.type, n.c_str());
}
int main()
{
	std::vector<int> doc = { AVS_OFFICESTUDIO_FILE_DOCUMENT_DOCX, AVS_OFFICESTUDIO_FILE_DOCUMENT_ODT, AVS_OFFICESTUDIO_FILE_CROSSPLATFORM_PDF };
	std::vector<int> cell = { AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSX, AVS_OFFICESTUDIO_FILE_SPREADSHEET_ODS };
	const int DOCX = AVS_OFFICESTUDIO_FILE_DOCUMENT_DOCX, XLSX = AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSX;
	Run("new docx, ODT chosen", true, true, 0, "newformat=67;", DOCX, L"Document1.docx", doc);
	Run("new xlsx, ODS chosen, Save As", true, true, 0, "saveas=true;newformat=259;", XLSX, L"Book1.xlsx", cell);
	Run("new docx, nothing chosen", true, true, 0, "", DOCX, L"Document1.docx", doc);
	Run("new docx, chosen format not offered", true, true, 0, "newformat=259;", DOCX, L"Document1.docx", doc);
	Run("saved docx, Save As, ODT chosen", false, false, 0, "saveas=true;newformat=67;", DOCX, L"/h/a.docx", doc);
	Run("recovered docx (not new), ODT chosen", true, false, 0, "newformat=67;", DOCX, L"a.docx", doc);
	Run("new docx, Save As PDF only", true, true, AVS_OFFICESTUDIO_FILE_CROSSPLATFORM_PDF, "newformat=67;", DOCX, L"Document1.docx", doc);
	return 0;
}
''' % {'ext': ext_body, 'get_fmt': get_fmt, 'change_ext': change_ext, 'block': block}

want = {
    'new docx, ODT chosen': '67 Document1.odt',
    'new xlsx, ODS chosen, Save As': '259 Book1.ods',
    'new docx, nothing chosen': '65 Document1.docx',
    'new docx, chosen format not offered': '65 Document1.docx',
    'saved docx, Save As, ODT chosen': '65 /h/a.docx',
    'recovered docx (not new), ODT chosen': '65 a.docx',
    'new docx, Save As PDF only': '65 Document1.docx',
}

sys.stdout.reconfigure(line_buffering=True)
failures = 0
print('desktop-sdk ' + ('@ ' + BASE_REF if BASELINE else SDK))
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, 't.cpp'), 'w') as f:
        f.write(cpp)
    exe = os.path.join(tmp, 't')
    subprocess.check_call(['c++', '-std=c++11', '-w', '-I' + CORE, os.path.join(tmp, 't.cpp'), '-o', exe])
    for line in subprocess.check_output([exe], text=True).splitlines():
        what, got = line.split('|')
        ok = want.pop(what) == got
        failures += not ok
        print('  %-66s %-24s %s' % (what, got, 'ok' if ok else 'FAILED'))
    assert not want, want

create = braced(src, src.index('void CCefViewEditor::CreateLocalFile(const AscEditorType& nFileFormatSrc, const std::wstring& sName'))
save_end = braced(src, src.index('void CCefView_Private::LocalFile_SaveEnd(int nError'))
for what, ok in (('CreateLocalFile marks the view as a new document', 'm_bIsNewLocalFile = true;' in create),
                 ('a successful save clears it', re.search(r'if \(bIsSaved\)\s*m_bIsNewLocalFile = false;', save_end) is not None)):
    failures += not ok
    print('  %-66s %-24s %s' % (what, ok, 'ok' if ok else 'FAILED'))

js = subprocess.run(['node', os.path.join(HERE, 'js_checks.js'),
                     SDKJS, SDKJS_BASE_REF if BASELINE else '', WEBAPPS, WEBAPPS_BASE_REF if BASELINE else ''])
failures += js.returncode != 0
print('\nFAILED' if failures else '\nok - a new document can be offered in the chosen default format; default unchanged')
sys.exit(1 if failures else 0)

#!/usr/bin/env python3
"""
#619 - opening a template (.dotx, .ott, .xltx, .ots, .potx, .otp and the
macro-enabled .dotm/.xltm/.potm) edited the template in place, so Save wrote
straight over it. Word, Excel, PowerPoint and LibreOffice instead start a new
untitled document based on the template.

Cause: CCefViewEditor::OpenLocalFile (desktop-sdk/ChromiumBasedEditors/lib/src/
cefview.cpp) is where every shell lands for a local file - macOS NSCefView
openFileWithName, Windows/Linux CTabPanel::openLocalFile, double click, Open
dialog, Recent, command line, ascdesktop://external/. It never looked at the
format: a template got m_sFileSrc = the template path and m_bIsSaved, so Save
(Ctrl+S) converted back into the template. The code that does the right thing
already existed - CreateLocalFile(etUndefined, name, templatePath), used by the
start page's template gallery - it was just never reached for a file.

Fix: OpenLocalFile first asks IsTemplateFileFormat(); for a template (not a cloud
crypt download, not an explicit mode=view) it calls CreateLocalFile with the
template as source and the name "<template name>.docx/.xlsx/.pptx"
(GetDocumentNameFromTemplate), and returns.

How it is tested: the REAL IsTemplateFileFormat and GetDocumentNameFromTemplate
and the REAL guard statement at the top of OpenLocalFile (the `if` that calls
IsTemplateFileFormat, located inside the brace-matched OpenLocalFile body) are
compiled against a stub CCefViewEditor whose CreateLocalFile records its call,
the real core OfficeFileFormats.h constants and the real NSFile::GetFileName
(core File.cpp). Reaching the end of the guard = "opened in place".
With BASELINE=1 the sources come from `git show $BASE_REF:` - there OpenLocalFile
has no such guard, so every template opens in place and the test FAILS.

  ./extract_and_run.py             RD_REPO (default ../../desktop-sdk), must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF, must FAIL

What is NOT claimed: CreateLocalFile itself (template -> Editor.bin through x2t,
new untitled tab, Save asking for a path) is the existing start-page path and is
not run here; nor is format detection (COfficeFileFormatChecker maps the OOXML
template content types and the OpenDocument template mimetypes to these
constants). Binary .dot/.xlt/.pot are detected as DOC/XLS/PPT and still open in
place. The shells' tab de-duplication still knows the tab by the template path,
so opening the same template again while the new document is unsaved focuses
that tab instead of starting a second document. Needs a GUI check.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk')))
CORE = os.path.abspath(os.path.join(HERE, '..', '..', 'core'))
CEFVIEW = 'ChromiumBasedEditors/lib/src/cefview.cpp'
BASE_REF = os.environ.get('BASE_REF', '946e4d8f^')
BASELINE = bool(os.environ.get('BASELINE'))


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


src = read(CEFVIEW)
at = src.find('void CCefViewEditor::OpenLocalFile(')
if at == -1:
    raise SystemExit('CCefViewEditor::OpenLocalFile not found in %s' % CEFVIEW)
open_local = brace_match(src, at)
if 'LocalFile_Start()' not in open_local:
    raise SystemExit('extracted OpenLocalFile does not look right')

helpers = ''
guard = ''
for name in ('static bool IsTemplateFileFormat(', 'static std::wstring GetDocumentNameFromTemplate('):
    p = src.find(name)
    if p != -1:
        helpers += brace_match(src, p) + '\n'
g = re.search(r'\n\s*if \([^\n]*IsTemplateFileFormat\(', open_local)
if g:
    guard = brace_match(open_local, g.start() + 1)

if not guard:
    # the baseline: nothing at the top of OpenLocalFile looks at the format
    helpers = ''

HARNESS = r'''
#include <string>
#include <vector>
#include <stdio.h>
#include "core/Common/OfficeFileFormats.h"
#include "core/DesktopEditor/common/File.h"

enum class AscEditorType { etDocument = 0, etPresentation = 1, etSpreadsheet = 2, etUndefined = 255 };

%(helpers)s

struct CInternal { std::wstring m_sCloudCryptSrc; };
struct CCefViewEditor
{
    CInternal  oInternal;
    CInternal* m_pInternal = &oInternal;
    bool bCreated = false;
    std::wstring sCreatedName, sCreatedTemplate;

    void CreateLocalFile(const AscEditorType&, const std::wstring& sName = L"", const std::wstring& sTemplatePath = L"")
    {
        bCreated = true; sCreatedName = sName; sCreatedTemplate = sTemplatePath;
    }
    /* the real guard from the top of OpenLocalFile; falling through = opened in place */
    void OpenLocalFile(const std::wstring& sFilePath, const int& nFileFormat_, const std::wstring& params)
    {
        (void)sFilePath; (void)nFileFormat_; (void)params;
        %(guard)s
    }
};

static int failures = 0;
static std::string A(const std::wstring& w) { std::string s; for (wchar_t c : w) s += (char)c; return s; }

static void scenario(const char* what, const std::wstring& path, int format, const std::wstring& params,
                     const char* crypt, bool wantNew, const std::wstring& wantName)
{
    CCefViewEditor v;
    if (crypt) v.oInternal.m_sCloudCryptSrc = L"https://portal/doc";
    v.OpenLocalFile(path, format, params);
    bool ok = (v.bCreated == wantNew) && (!wantNew || (v.sCreatedName == wantName && v.sCreatedTemplate == path));
    printf("  %%-46s -> %%-32s %%s\n", what,
           v.bCreated ? ("new untitled \"" + A(v.sCreatedName) + "\"").c_str() : "opens the file itself",
           ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

int main()
{
    printf("#619 OpenLocalFile on a local file:\n");
    scenario("Letter.dotx (Word template)",        L"/Users/u/Templates/Letter.dotx", AVS_OFFICESTUDIO_FILE_DOCUMENT_DOTX, L"", 0, true, L"Letter.docx");
    scenario("Macro.dotm",                         L"/u/Macro.dotm",  AVS_OFFICESTUDIO_FILE_DOCUMENT_DOTM, L"", 0, true, L"Macro.docx");
    scenario("Brief.ott (OpenDocument template)",  L"/u/Brief.ott",   AVS_OFFICESTUDIO_FILE_DOCUMENT_OTT,  L"", 0, true, L"Brief.docx");
    scenario("Budget.xltx",                        L"/u/Budget.xltx", AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLTX, L"", 0, true, L"Budget.xlsx");
    scenario("Budget.xltm",                        L"/u/Budget.xltm", AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLTM, L"", 0, true, L"Budget.xlsx");
    scenario("Sheet.ots",                          L"/u/Sheet.ots",   AVS_OFFICESTUDIO_FILE_SPREADSHEET_OTS,  L"", 0, true, L"Sheet.xlsx");
    scenario("Deck.potx",                          L"C:/t/Deck.potx", AVS_OFFICESTUDIO_FILE_PRESENTATION_POTX, L"&lang=en", 0, true, L"Deck.pptx");
    scenario("Deck.potm",                          L"/u/Deck.potm",   AVS_OFFICESTUDIO_FILE_PRESENTATION_POTM, L"", 0, true, L"Deck.pptx");
    scenario("Slides.otp",                         L"/u/Slides.otp",  AVS_OFFICESTUDIO_FILE_PRESENTATION_OTP,  L"", 0, true, L"Slides.pptx");
    scenario("my.report.v2.dotx (dots in the name)", L"/u/my.report.v2.dotx", AVS_OFFICESTUDIO_FILE_DOCUMENT_DOTX, L"", 0, true, L"my.report.v2.docx");
    printf("  not templates / not to be redirected:\n");
    scenario("Report.docx",                        L"/u/Report.docx", AVS_OFFICESTUDIO_FILE_DOCUMENT_DOCX, L"", 0, false, L"");
    scenario("Report.odt",                         L"/u/Report.odt",  AVS_OFFICESTUDIO_FILE_DOCUMENT_ODT,  L"", 0, false, L"");
    scenario("Budget.xlsx",                        L"/u/Budget.xlsx", AVS_OFFICESTUDIO_FILE_SPREADSHEET_XLSX, L"", 0, false, L"");
    scenario("Letter.dotx with mode=view",         L"/u/Letter.dotx", AVS_OFFICESTUDIO_FILE_DOCUMENT_DOTX, L"&mode=view", 0, false, L"");
    scenario("Letter.dotx, cloud crypt download",  L"/tmp/OL1.dotx",  AVS_OFFICESTUDIO_FILE_DOCUMENT_DOTX, L"", "crypt", false, L"");
    scenario("empty path (cloud crypt start)",     L"",               AVS_OFFICESTUDIO_FILE_DOCUMENT_DOTX, L"", 0, false, L"");
    printf("%%s\n", failures ? "FAIL" : "PASS");
    return failures ? 1 : 0;
}
'''

d = tempfile.mkdtemp(prefix='rd619_')
os.symlink(CORE, os.path.join(d, 'core'))
cpp = os.path.join(d, 'harness.cpp')
with open(cpp, 'w') as f:
    f.write(HARNESS % {'helpers': helpers, 'guard': guard})
exe = os.path.join(d, 'harness')
MAC = sys.platform == 'darwin'
cmd = ['clang++', '-std=c++14'] + (['-D_MAC'] if MAC else []) + ['-D_LINUX',
       '-include', 'sys/stat.h', '-include', 'stdlib.h', '-include', 'unistd.h',
       '-Wno-writable-strings', '-Wno-deprecated-declarations',
       '-I', d, '-o', exe, cpp,
       os.path.join(CORE, 'DesktopEditor/common/File.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/Directory.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/SystemUtils.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/StringBuilder.cpp'),
       os.path.join(CORE, 'DesktopEditor/common/Base64.cpp')]
if MAC:
    cmd += ['-framework', 'CoreFoundation']
c = subprocess.run(cmd, capture_output=True, text=True)
if c.returncode != 0:
    sys.stderr.write(c.stdout + c.stderr)
    raise SystemExit('the harness did not build (sources kept in %s)' % d)

print('sources: %s%s' % ('git show %s:' % BASE_REF if BASELINE else '', os.path.join(SDK, CEFVIEW)))
if not guard:
    print('OpenLocalFile has no template check: a template is always opened (and saved) in place')
sys.stdout.flush()
rc = subprocess.run([exe]).returncode
sys.exit(1 if rc else 0)

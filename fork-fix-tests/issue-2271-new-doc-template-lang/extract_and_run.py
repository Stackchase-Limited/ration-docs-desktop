#!/usr/bin/env python3
"""
#2271 - "Ability to save default page layout": users re-do the page setup of
every new document. Part of that is a real defect: a new blank document came
out as US Letter with 1" margins (and en-US proofing language) for users whose
language has its own blank template with A4 and metric margins.

CAscApplicationManager::GetNewFilePath (desktop-sdk applicationmanager.cpp)
takes the blank from <converter>/empty/<lang>/new.<ext>, <lang> being the
editors' "lang" URL parameter, and falls back to en-US/ when that folder does
not exist. The macOS app sends "xx-XX" built from the bare system language when
no UI language was picked (ASCLinguist appLanguageCode: "ja" -> "ja-JA",
"zh" -> "zh-ZH", "sv" -> "sv-SV") and offers Norwegian as "no-NO"; the
templates are ja-JP, zh-CN, sv-SE, nb-NO. Now a missing folder falls back to
the first sorted folder of the same language ("no" = "nb"); English stays
en-US, an exact folder (de-DE, en-GB) is used as before.

This compiles the real GetNewFilePath plus the real NSUrlParse::GetUrlValue,
NSCommon::makeUpper and NSCommon::makeLowerW from utils.h, with the kernel's
NSDirectory/NSFile replaced by std::filesystem stand-ins, and runs it against
the real document-templates/new tree (the folder the build copies to
converter/empty), reading w:pgSz from the docx it picks.

  RD_REPO       desktop-sdk checkout (default ../../desktop-sdk)
  RD_TEMPLATES  blank templates (default ../../document-templates/new)
  BASELINE=1    read the sources from BASE_REF (default ee8f1fdf^) - must FAIL.

NOT claimed: what language code the Windows/Linux app sends (its own list may
already use full codes); the "save my page setup as the default" feature
itself is not implemented here (see the issue triage note). Needs clang++
with C++17.
"""
import os, re, shutil, subprocess, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
TEMPLATES = os.environ.get('RD_TEMPLATES') or os.path.normpath(os.path.join(HERE, '..', '..', 'document-templates', 'new'))
BASELINE = os.environ.get('BASELINE') == '1'
BASE_REF = os.environ.get('BASE_REF', 'ee8f1fdf^')


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              check=True, capture_output=True, text=True).stdout
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


def brace_match(text, start):
    i = text.index('{', start)
    depth = 0
    while True:
        c = text[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1


def extract(text, anchor):
    start = text.index(anchor)
    return text[start:brace_match(text, start)]


src = read('ChromiumBasedEditors/lib/src/applicationmanager.cpp')
utils = read('ChromiumBasedEditors/lib/src/utils.h')
fn = extract(src, 'std::wstring CAscApplicationManager::GetNewFilePath(')
helpers = '\n'.join(extract(utils, a) for a in (
    'static void makeUpper(std::string& url)', 'static void makeLowerW(std::wstring& url)'))
geturl = extract(utils, 'static std::wstring GetUrlValue(')

cpp = r'''
#include <string>
#include <vector>
#include <algorithm>
#include <filesystem>
#include <iostream>
#include <codecvt>
#include <locale>
namespace fs = std::filesystem;
// stand-ins for core/DesktopEditor/common/{Directory,File}.h
namespace NSDirectory {
	bool Exists(const std::wstring& p) { return fs::is_directory(fs::path(p)); }
	std::vector<std::wstring> GetDirectories(std::wstring d) {
		std::vector<std::wstring> r;
		for (auto& e : fs::directory_iterator(fs::path(d))) if (e.is_directory()) r.push_back(d + L"/" + e.path().filename().wstring());
		return r;
	}
}
namespace NSFile {
	std::wstring GetFileName(const std::wstring& p) { auto n = p.rfind(L'/'); return n == std::wstring::npos ? p : p.substr(n + 1); }
	struct CFileBinary { static bool Exists(const std::wstring& p) { return fs::is_regular_file(fs::path(p)); } };
}
namespace NSCommon {
''' + helpers + r'''
}
namespace NSUrlParse {
''' + geturl + r'''
}
enum class AscEditorType { etDocument, etPresentation, etSpreadsheet, etDocumentMasterForm, etDocumentMasterOForm, etPdf, etDraw, etUndefined };
struct Internal { std::wstring m_sAdditionalUrlParams; };
struct Settings { std::string country = "RU"; std::wstring file_converter_path; };
class CAscApplicationManager {
public:
	Settings m_oSettings; Internal* m_pInternal;
	std::wstring GetNewFilePath(const AscEditorType& nFileFormat);
};
''' + fn + r'''
int main(int argc, char** argv) {
	std::wstring_convert<std::codecvt_utf8<wchar_t>> cv;
	Internal in; CAscApplicationManager m; m.m_pInternal = &in;
	m.m_oSettings.file_converter_path = cv.from_bytes(argv[1]);
	for (int i = 2; i < argc; i += 2) {
		in.m_sAdditionalUrlParams = cv.from_bytes(argv[i]);
		AscEditorType t = std::string(argv[i + 1]) == "pptx" ? AscEditorType::etPresentation : AscEditorType::etDocument;
		std::cout << cv.to_bytes(m.GetNewFilePath(t)) << "\n";
	}
}
'''

tmp = tempfile.mkdtemp(prefix='rd2271-')
conv = os.path.join(tmp, 'converter')
os.makedirs(conv)
os.symlink(TEMPLATES, os.path.join(conv, 'empty'))
with open(os.path.join(tmp, 't.cpp'), 'w') as f:
    f.write(cpp)
exe = os.path.join(tmp, 't')
subprocess.run(['clang++', '-std=c++17', '-w', '-o', exe, os.path.join(tmp, 't.cpp')], check=True)

# (lang URL parameter as the app sends it, file kind, expected template folder, expected page)
CASES = [
    ('lang=ja-JA', 'docx', 'ja-JP', 'A4'),            # macOS, system language Japanese
    ('lang=zh-ZH&username=x', 'docx', 'zh-CN', 'A4'),  # Chinese; parameter in the middle of the list
    ('lang=sv-SV', 'docx', 'sv-SE', 'A4'),
    ('lang=no-NO', 'docx', 'nb-NO', 'A4'),            # Norwegian from the app's language list
    ('lang=ko-KO', 'pptx', 'ko-KR', None),            # presentations follow the same rule
    ('lang=de-DE', 'docx', 'de-DE', 'A4'),            # exact folder: unchanged
    ('lang=en-GB', 'docx', 'en-GB', 'A4'),
    ('lang=en-EN', 'docx', 'en-US', 'Letter'),        # bare English: en-US as before
    ('lang=en', 'docx', 'en-US', 'Letter'),
    ('lang=xx-XX', 'docx', 'en-US', 'Letter'),        # no template for the language
    ('username=x', 'docx', 'en-US', 'Letter'),        # no lang at all
]
args = [exe, conv]
for p, k, _, _ in CASES:
    args += [p, k]
out = subprocess.run(args, check=True, capture_output=True, text=True).stdout.split('\n')

fails = 0
for (p, k, want, page), got in zip(CASES, out):
    folder = os.path.basename(os.path.dirname(got))
    size = ''
    if k == 'docx':
        with zipfile.ZipFile(got) as z:
            w = re.search(r'<w:pgSz w:w="(\d+)"', z.read('word/document.xml').decode()).group(1)
        size = {'12240': 'Letter', '11906': 'A4'}.get(w, w)
    ok = folder == want and (page is None or size == page) and got.endswith('new.' + k)
    fails += not ok
    print('%s %-24s %s -> %s/new.%s %s' % ('ok  ' if ok else 'FAIL', p, k, folder, k, size))

print('%s: %d/%d cases' % ('FAILED' if fails else 'PASSED', len(CASES) - fails, len(CASES)) +
      (' (BASELINE %s)' % BASE_REF if BASELINE else ''))
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if fails else 0)

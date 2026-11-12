#!/usr/bin/env python3
"""
#141 - "Adobe Typekit fonts not working" (Windows): fonts activated from Adobe
Fonts (Typekit) in the Creative Cloud app never appear in the font list.

Creative Cloud does not install those fonts: it keeps the files in its own
folder, %APPDATA%\\Adobe\\CoreSync\\plugins\\livetype\\r, and loads them into the
session itself, so they are neither under the registry key
HKLM\\...\\CurrentVersion\\Fonts nor in a fonts directory. On Windows
CApplicationFonts::GetSetupFontFiles (core DesktopEditor/fontengine/
ApplicationFonts.cpp) reads exactly those: the registry key, C:\\Windows\\Fonts,
the per-user %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts and the Store CloudFonts
folder. The reporters' workaround (a symlink to that folder inside the app's
fonts directory) shows that the files themselves load fine. Now the CoreSync
folder under CSIDL_APPDATA is scanned with the per-user folders.

This compiles the REAL GetSetupFontFiles (brace-extracted, built with _WIN32
defined on this machine against stubs for the Win32 calls: SHGetSpecialFolderPathW
answers C:\\Users\\u\\AppData\\..., the registry enumeration is empty, the
directory listers record which folders were asked for and return one font in
each) and checks that a font in the CoreSync folder is returned, and that the
folders scanned before are still scanned.

NOT claimed: that every Creative Cloud version uses this folder (2018-2024
reports and the thread's workaround say livetype\\r); macOS needs no change -
GetInstalledFontsMac lists every font CoreText has activated
(CTFontManagerCopyAvailableFontURLs), which is how Creative Cloud activates
them there; no real Windows run (needs a Windows build with Creative Cloud).

  python3 fork-fix-tests/issue-0141-adobe-fonts-windows/extract_and_run.py
  RD_REPO=<core checkout> (default ../../core)   BASELINE=1 reads BASE_REF and must fail.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
SRC = 'DesktopEditor/fontengine/ApplicationFonts.cpp'
BASE_REF = os.environ.get('BASE_REF', 'a60044ddd3^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def extract(text, marker):
    at = text.index(marker)
    i = text.index('{', at)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[at:j + 1]
    raise RuntimeError('unbalanced braces after ' + marker)


STUBS = r'''
#include <string>
#include <vector>
#include <map>
#include <cstdio>
#include <cwchar>
// the function's Windows branch is selected after the standard headers (libc++ breaks if _WIN32 is set for them)
#define _WIN32 1
typedef unsigned long DWORD; typedef int BOOL; typedef void* HWND; typedef void* HKEY;
#define FALSE 0
#define MAX_PATH 260
#define ERROR_SUCCESS 0L
#define HKEY_LOCAL_MACHINE ((HKEY)1)
enum { CSIDL_APPDATA = 0x1a, CSIDL_LOCAL_APPDATA = 0x1c, CSIDL_FONTS = 0x14 };
enum { VER_PLATFORM_WIN32_NT = 2 };
struct OSVERSIONINFO { DWORD dwOSVersionInfoSize; DWORD dwPlatformId; };
static BOOL GetVersionEx(OSVERSIONINFO* v) { v->dwPlatformId = VER_PLATFORM_WIN32_NT; return 1; }
static BOOL SHGetSpecialFolderPathW(HWND, wchar_t* out, int csidl, BOOL) {
    const wchar_t* p = csidl == CSIDL_APPDATA ? L"C:\\Users\\u\\AppData\\Roaming"
                     : csidl == CSIDL_LOCAL_APPDATA ? L"C:\\Users\\u\\AppData\\Local"
                     : csidl == CSIDL_FONTS ? L"C:\\Windows\\Fonts" : nullptr;
    if (!p) return 0;
    wcscpy(out, p); return 1;
}
static BOOL GetUserNameW(wchar_t* b, DWORD* n) { wcscpy(b, L"u"); *n = 2; return 1; }
static long GetNextNameValue(HKEY, const std::wstring&, std::wstring&, std::wstring&) { return 259L; }
static std::vector<std::wstring> g_asked;
namespace NSFile { struct CFileBinary { bool OpenFile(const std::wstring&) { return false; } void CloseFile() {} }; }
namespace NSDirectory {
    static void GetFiles2(std::wstring dir, std::vector<std::wstring>& out, bool = false) {
        g_asked.push_back(dir); out.push_back(dir + L"\\font.otf");
    }
    static std::vector<std::wstring> GetFiles(std::wstring dir, bool r = false) {
        std::vector<std::wstring> v; GetFiles2(dir, v, r); return v;
    }
}
'''

MAIN = r'''
int main() {
    std::vector<std::wstring> files = GetSetupFontFiles(true);
    for (auto& d : g_asked) printf("scanned %ls\n", d.c_str());
    for (auto& f : files) printf("font %ls\n", f.c_str());
    return 0;
}
'''


def main():
    text = read(SRC)
    func = extract(text, 'std::vector<std::wstring> CApplicationFonts::GetSetupFontFiles(')
    func = func.replace('CApplicationFonts::GetSetupFontFiles(', 'GetSetupFontFiles(', 1)
    func = func.replace('const bool& bIsUseUserFonts', 'const bool& bIsUseUserFonts = true', 1)
    tmp = tempfile.mkdtemp(prefix='rd141-')
    cpp = os.path.join(tmp, 't.cpp')
    exe = os.path.join(tmp, 't')
    with open(cpp, 'w', encoding='utf-8') as f:
        f.write(STUBS + '\nstatic ' + func + '\n' + MAIN)
    cc = subprocess.run(['c++', '-std=c++17', '-w', cpp, '-o', exe],
                        capture_output=True, text=True)
    if cc.returncode:
        print(cc.stderr)
        print('FAIL: harness did not compile')
        return 1
    out = subprocess.run([exe], capture_output=True, text=True, check=True).stdout
    fonts = [l[5:] for l in out.splitlines() if l.startswith('font ')]
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(('ok   ' if cond else 'FAIL ') + msg)
        ok = ok and cond

    adobe = 'C:\\Users\\u\\AppData\\Roaming\\Adobe\\CoreSync\\plugins\\livetype\\r\\font.otf'
    check(adobe in fonts, 'a font activated by Adobe Fonts (CoreSync livetype\\r) is in the list')
    for kept in ['C:\\Windows\\Fonts\\font.otf',
                 'C:\\Users\\u\\AppData\\Local\\Microsoft\\Windows\\Fonts\\font.otf',
                 'C:\\Users\\u\\AppData\\Local\\Microsoft\\FontCache\\4\\CloudFonts\\font.otf']:
        check(kept in fonts, 'still scanned: ' + kept.rsplit('\\', 1)[0])
    check(len(fonts) == len(set(fonts)), 'no font listed twice')
    print('PASS' if ok else 'FAILED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

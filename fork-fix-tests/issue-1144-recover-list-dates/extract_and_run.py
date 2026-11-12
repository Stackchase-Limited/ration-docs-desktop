#!/usr/bin/env python3
"""
#1144 - "Add dates of modification to the 'Recover files' list".

The start page's Recover list already has a date column ("Autosaved") and the
list JSON already has a "modifyed" field per file (Recovers_Dump writes
CAscEditorFileInfo::m_sDate) - but Recovers_Load never set m_sDate, so every
recovered file came with modifyed:"" and the column was empty: a list of bare
names, as the report says.

Now Recovers_Load sets it from the last modification of the recovery folder's
changes/changes0.json - the changes the editor wrote before it went away - in
the format the Recent list uses (dd.mm.yyyy hh:mm, local time), through the new
CAscEditorFileInfo::UpdateDateFromFile (core's NSFile::CFileBinary::GetTime).

This compiles the real CAscEditorFileInfo class and the real
CApplicationManagerAdditional-side Recovers_Load (applicationmanager_p.h), lifted
out by brace matching, with core's real File/Directory code, and stand-ins for
the critical section, the settings, the recovery locker and the XML reader of
asc_name.info. It builds two recovery folders on disk, sets changes0.json's
modification time, and checks the date each entry gets.

NOT claimed: the start page rendering (unchanged: it prints `date` as given);
Windows (GetTime has a Windows branch that fills the same fields; not run here).

BASELINE=1 reads applicationmanager_p.h from BASE_REF (the parent of the fix):
the dates stay empty, so it fails.
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk')))
CORE = os.path.abspath(os.environ.get('RD_CORE', os.path.join(HERE, '..', '..', 'core')))
APP = 'ChromiumBasedEditors/lib/src/applicationmanager_p.h'
BASE_REF = os.environ.get('BASE_REF', 'bdbd5c35^')
BASELINE = bool(os.environ.get('BASELINE'))
COMMON = ['File.cpp', 'Directory.cpp', 'SystemUtils.cpp', 'StringBuilder.cpp', 'StringExt.cpp', 'Path.cpp', 'Base64.cpp']


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


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
    raise SystemExit('unbalanced braces')


def extract(text, anchor):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit('%r not found - the extractor needs updating' % anchor)
    return brace_match(text, at)


HARNESS = r'''
#include "DesktopEditor/common/File.h"
#include "DesktopEditor/common/Directory.h"
#include "Common/OfficeFileFormats.h"
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <regex>
#include <stdio.h>
#include <time.h>

typedef unsigned char BYTE;
struct CRITICAL_SECTION_STUB {};
struct CTemporaryCS { CTemporaryCS(CRITICAL_SECTION_STUB *) {} };
namespace NSSystem {
    enum class LockType { ltNone, ltLocked };
    struct CLocalFileLocker { static LockType IsLocked(const std::wstring&) { return LockType::ltNone; } };
}
namespace XmlUtils {
    /* asc_name.info is <info type="65" name="Report.docx"/>; a regex is enough for the stand-in */
    struct CXmlNode {
        std::string text;
        bool FromXmlFile(const std::wstring& f) {
            std::ifstream in(U_TO_UTF8(f)); std::stringstream ss; ss << in.rdbuf(); text = ss.str(); return !text.empty(); }
        std::wstring GetAttribute(const std::wstring& n) {
            std::smatch m; std::string re = U_TO_UTF8(n) + "=\"([^\"]*)\"";
            return std::regex_search(text, m, std::regex(re)) ? UTF8_TO_U(m[1].str()) : L""; }
        int ReadAttributeInt(const std::wstring& n) { return std::stoi(U_TO_UTF8(GetAttribute(n))); }
    };
}

%(info)s;

struct Settings { std::wstring recover_path; };
struct Main { Settings m_oSettings; };
struct Manager {
    Main * m_pMain;
    CRITICAL_SECTION_STUB m_oCS_LocalFiles;
    std::vector<CAscEditorFileInfo> m_arRecovers;
    %(load)s
};

static int failures = 0;
static std::wstring expected(time_t t) {
    struct tm * l = localtime(&t); char b[64];
    snprintf(b, sizeof b, "%%02d.%%02d.%%d %%02d:%%02d", l->tm_mday, l->tm_mon + 1, l->tm_year + 1900, l->tm_hour, l->tm_min);
    return UTF8_TO_U(std::string(b));
}

int main(int argc, char ** argv) {
    Main main; std::string root(argv[1]); main.m_oSettings.recover_path = UTF8_TO_U(root);
    Manager m; m.m_pMain = &main;
    m.Recovers_Load();
    time_t t1 = (time_t)atol(argv[2]), t2 = (time_t)atol(argv[3]);
    if (m.m_arRecovers.size() != 2) { printf("  expected 2 recovered files, got %%d\nFAILED\n", (int)m.m_arRecovers.size()); return 1; }
    for (auto & r : m.m_arRecovers) {
        std::wstring want = r.m_sPath.find(L"Budget") != std::wstring::npos ? expected(t1) : expected(t2);
        bool ok = r.m_sDate == want;
        printf("  %%-14s modifyed=\"%%ls\"  %%s\n", U_TO_UTF8(NSFile::GetFileName(r.m_sPath)).c_str(), r.m_sDate.c_str(),
               ok ? "ok" : ("FAILED (want \"" + U_TO_UTF8(want) + "\")").c_str());
        if (!ok) failures++;
    }
    printf("\n%%s\n", failures ? "FAILED" : "ok - each recovered file carries the time of its last autosaved change");
    return failures ? 1 : 0;
}
'''


def main():
    if platform.system() not in ('Darwin', 'Linux'):
        print('skipped: macOS/Linux only')
        return 0
    text = read(APP)
    info = extract(text, 'class CAscEditorFileInfo\n')
    load = extract(text, 'void Recovers_Load()')
    d = tempfile.mkdtemp(prefix='rd1144_')
    try:
        rec = os.path.join(d, 'recover')
        times = []
        for folder, name, typ, age in (('a1', 'Budget.xlsx', 257, 3 * 86400 + 4000), ('b2', 'Report.docx', 65, 7200)):
            f = os.path.join(rec, folder)
            os.makedirs(os.path.join(f, 'changes'))
            with open(os.path.join(f, 'Editor.bin'), 'wb') as fh:
                fh.write(b'XLSY;v5;0;' if name.endswith('xlsx') else b'DOCY;v5;0;')
            with open(os.path.join(f, 'asc_name.info'), 'w') as fh:
                fh.write('<info type="%d" name="%s"/>' % (typ, name))
            ch = os.path.join(f, 'changes', 'changes0.json')
            with open(ch, 'w') as fh:
                fh.write('[]')
            t = int(time.time()) - age
            os.utime(ch, (t, t))
            times.append(t)
        common = os.path.join(CORE, 'DesktopEditor', 'common')
        defs = ['-D_LINUX', '-D_MAC', '-DMAC', '-DLINUX'] if platform.system() == 'Darwin' else ['-D_LINUX', '-DLINUX']
        libs = ['-framework', 'CoreFoundation'] if platform.system() == 'Darwin' else []
        cxx = os.environ.get('CXX', 'c++')
        with open(os.path.join(d, 'h.cpp'), 'w') as fh:
            fh.write(HARNESS % {'info': info, 'load': load})
        objs = []
        for i, unit in enumerate([os.path.join(d, 'h.cpp')] + [os.path.join(common, c) for c in COMMON]):
            obj = os.path.join(d, 'u%d.o' % i)
            c = subprocess.run([cxx, '-std=c++14', '-w', '-c', '-include', 'sys/stat.h', '-include', 'unistd.h',
                                '-I', CORE] + defs + [unit, '-o', obj], capture_output=True, text=True)
            if c.returncode != 0:
                sys.stderr.write(c.stdout + c.stderr)
                raise SystemExit('harness did not compile: %s' % unit)
            objs.append(obj)
        exe = os.path.join(d, 'h')
        c = subprocess.run([cxx] + objs + libs + ['-o', exe], capture_output=True, text=True)
        if c.returncode != 0:
            sys.stderr.write(c.stdout + c.stderr)
            raise SystemExit('harness did not link')
        print('#1144 %s: %s' % ('BASELINE ' + BASE_REF if BASELINE else 'source', REPO), flush=True)
        return subprocess.run([exe, rec, str(times[0]), str(times[1])]).returncode
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
#482 follow-up (ours): x2t's csv reader and the sheet row limit (1048576).

Before core 9eed63b760:
  - CSVReader::Impl::Read stopped on m_arrItems.size() > 1048576, i.e. after
    row 1048577 was already in: the editor (csv -> Editor.bin) got 1048577 rows;
  - csv -> xlsx reads into the xml cache (readToxmlCache_), which leaves
    m_arrItems empty, so the limit never fired: every row went into the xlsx
    and Read returned 0 (no ROWLIMITS);
  - a sheet of exactly 1048576 rows followed by blank lines got extra rows;
  - fromSpreadsheet (ASCConverters.cpp) replaced the read's ROWLIMITS (94) /
    CELLLIMITS (96) by the 0 of the following write, so csv -> xlsx exited 0
    even when rows or cell text were cut.

What runs: the REAL CSVReader.cpp of RD_REPO (or BASE_REF) is compiled with
x2t's flags and linked, ahead of the libBinDocument.a that holds the old one,
against the core libraries of the main build (RD_CORE_LIB); a small driver
calls CSVReader::Read on generated csv files both ways (Editor.bin path:
rows counted in m_arrItems; xlsx path: written with CXlsx::Write as
csv2xlsx_dir does, rows counted in sheet1.xml). The tail of fromSpreadsheet
(the block that calls fromXlsxDir) is lifted out by brace matching and run with
a stub fromXlsxDir.

  RD_REPO      core checkout (default ../../core)
  RD_CORE_LIB  core build/lib/mac_arm64 of a full build (default: RD_REPO's, then ../../core's)
  BASELINE=1   compile the sources at BASE_REF (default 9eed63b760^); must FAIL

NOT claimed: the whole x2t (that was checked by relinking x2t: see the commit);
encodings/delimiters other than UTF-8 and comma; macOS arm64 only (the Linux
compile was syntax-only).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '9eed63b760^')
BASELINE = bool(os.environ.get('BASELINE'))
MAIN_CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
LIMIT = 1048576

results = []


def report(ok, what):
    results.append(ok)
    print(('ok   ' if ok else 'FAIL ') + what)


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig').read()


def find_lib():
    for d in (os.environ.get('RD_CORE_LIB'), os.path.join(REPO, 'build', 'lib', 'mac_arm64'),
              os.path.join(MAIN_CORE, 'build', 'lib', 'mac_arm64')):
        if d and os.path.isfile(os.path.join(d, 'libBinDocument.a')):
            return d
    sys.exit('libBinDocument.a not found; set RD_CORE_LIB')


def block(text, start):
    a = text.find(start)
    if a < 0:
        return None
    i = text.find('{', a)
    depth = 0
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    return None


DRIVER = r'''
#include "OOXML/Binary/Sheets/Reader/CSVReader.h"
#include "OOXML/XlsxFormat/Xlsx.h"
#include "OOXML/XlsxFormat/Worksheets/Worksheet.h"
#include "OOXML/DocxFormat/ContentTypes.h"
#include "Common/OfficeFileErrorDescription.h"
#include "DesktopEditor/common/File.h"
#include <cstdio>
int main(int argc, char** argv)
{
	std::wstring sFile = NSFile::CUtf8Converter::GetUnicodeStringFromUTF8((BYTE*)argv[1], strlen(argv[1]));
	bool bCache = argv[2][0] == '1';
	CSVReader oReader;
	oReader.readToxmlCache_ = bCache;
	OOX::Spreadsheet::CXlsx oXlsx;
	_UINT32 nRes = oReader.Read(sFile, oXlsx, 46, L",", -1);
	long nRows = -1;
	if (!bCache)
		nRows = (long)oXlsx.m_arWorksheets[0]->m_oSheetData->m_arrItems.size();
	else
	{
		std::wstring sDir = NSFile::CUtf8Converter::GetUnicodeStringFromUTF8((BYTE*)argv[3], strlen(argv[3]));
		oXlsx.PrepareToWrite();
		OOX::CContentTypes oContentTypes;
		oXlsx.Write(sDir, oContentTypes);
	}
	printf("%d %ld\n", nRes == 0 ? 0 : (int)(nRes - AVS_ERROR_FIRST - AVS_FILEUTILS_ERROR_FIRST), nRows);
	return 0;
}
'''


def x2t_libs():
    mk = open(os.path.join(MAIN_CORE, 'X2tConverter', 'build', 'Qt', 'Makefile.mac_arm64')).read().replace('\\\n', ' ')
    libs = re.search(r'^LIBS\s*=\s*(.*)$', mk, re.M).group(1)
    # x2t's own objects too (format checker etc.), except the one with main()
    objs = [o for o in re.search(r'^OBJECTS\s*=\s*(.*)$', mk, re.M).group(1).split() if not o.endswith('/main.o')]
    return objs + libs.replace('$(SUBLIBS)', '').split()


def main():
    print(('BASELINE ' + BASE_REF) if BASELINE else ('repo ' + REPO))
    lib = find_lib()
    sdk = subprocess.run(['xcrun', '--show-sdk-path'], capture_output=True, text=True).stdout.strip()
    inc = os.path.join(REPO, 'OOXML', 'Projects', 'Linux', 'BinDocument')
    flags = ['-std=gnu++11', '-w', '-O1', '-stdlib=libc++', '-isysroot', sdk, '-fvisibility=hidden', '-fvisibility-inlines-hidden',
             '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC', '-DCRYPTOPP_DISABLE_ASM', '-DUNICODE', '-D_UNICODE',
             '-DSOLUTION_ASCOFFICEDOCXFILE2', '-DDONT_WRITE_EMBEDDED_FONTS', '-DAVS_USE_CONVERT_PPTX_TOCUSTOM_VML',
             '-D_LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION',
             '-I' + inc, '-I' + os.path.join(MAIN_CORE, 'Common', '3dParty', 'boost', 'build', 'mac_arm64', 'include'),
             '-I' + os.path.join(REPO, 'MsBinaryFile', 'XlsFile', 'Format'), '-I' + os.path.join(REPO, 'MsBinaryFile', 'Common', 'common_xls'),
             '-I' + os.path.join(REPO, 'OOXML', 'XlsbFormat'), '-I' + REPO,
             '-I' + os.path.join(REPO, 'OOXML', 'Binary', 'Sheets', 'Reader')]
    with tempfile.TemporaryDirectory() as work:
        csvr = os.path.join(work, 'CSVReader.o')
        src = read('OOXML/Binary/Sheets/Reader/CSVReader.cpp')
        r = subprocess.run(['c++', '-c', '-x', 'c++', '-', '-o', csvr] + flags, input=src, capture_output=True, text=True)
        if r.returncode:
            sys.exit('CSVReader.cpp compile failed:\n' + r.stderr[-3000:])
        drv = os.path.join(work, 'drv.cpp')
        open(drv, 'w').write(DRIVER)
        exe = os.path.join(work, 'drv')
        r = subprocess.run(['c++', drv, csvr, '-o', exe] + flags + ['-L' + lib] + x2t_libs() +
                           ['-F' + lib, '-Wl,-rpath,' + lib], capture_output=True, text=True,
                           cwd=os.path.join(MAIN_CORE, 'X2tConverter', 'build', 'Qt'))
        if r.returncode:
            sys.exit('driver link failed:\n' + r.stderr[-3000:])

        def csv(name, rows, tail=''):
            p = os.path.join(work, name)
            with open(p, 'w') as f:
                f.write(''.join('%d,r\n' % i for i in range(1, rows + 1)) + tail)
            return p

        def run(path, cache):
            out = os.path.join(work, 'x' + str(len(os.listdir(work))))
            os.makedirs(out)
            res = subprocess.run([exe, path, '1' if cache else '0', out], capture_output=True, text=True, timeout=1800)
            code, rows = map(int, res.stdout.split())
            if cache:
                sheet = os.path.join(out, 'xl', 'worksheets', 'sheet1.xml')
                rows = open(sheet, encoding='utf-8').read().count('<row ') if os.path.exists(sheet) else -1
            return code, rows

        over, exact, blank = csv('over.csv', LIMIT + 1), csv('exact.csv', LIMIT), csv('blank.csv', LIMIT, '\n\n')
        for cache, what in ((False, 'csv -> Editor.bin'), (True, 'csv -> xlsx')):
            c, n = run(over, cache)
            report(c == 94 and n == LIMIT, '%s, %d rows: code %d, %d rows kept (want 94, %d)' % (what, LIMIT + 1, c, n, LIMIT))
            c, n = run(exact, cache)
            report(c == 0 and n == LIMIT, '%s, exactly %d rows: code %d, %d rows (control)' % (what, LIMIT, c, n))
            c, n = run(blank, cache)
            report(c == 0 and n == LIMIT, '%s, %d rows + 2 blank lines: code %d, %d rows (want 0, %d)' % (what, LIMIT, c, n, LIMIT))

        # fromSpreadsheet: the read's code must survive the write
        asc = read('X2tConverter/src/ASCConverters.cpp')
        fs = block(asc, '_UINT32 fromSpreadsheet(')
        tail = None
        if fs:
            k = fs.rfind('if (SUCCEEDED_X2T(nRes))')
            tail = block(fs[k:], 'if (SUCCEEDED_X2T(nRes))') if k >= 0 else None
        if not tail:
            sys.exit('fromSpreadsheet tail not found')
        t = r'''
#include <cstdio>
#include <string>
typedef unsigned int _UINT32;
#define SUCCEEDED_X2T(n) (0 == (n) || 94 == (n) || 96 == (n))
struct P { std::wstring f; std::wstring* m_sFileTo = &f; int* m_nFormatTo = nullptr; int fr = 0; int* m_nFormatFrom = &fr; bool m_bMacro = false;
	void changeFormatFromPost(int, bool) {} };
_UINT32 fromXlsxDir(const std::wstring&, const std::wstring&, int, P&, int&) { return 0; }
_UINT32 run(_UINT32 nRes) { P params; int convertParams = 0; std::wstring sXlsxDir; int nFormatTo = 0;
TAIL
	return nRes; }
int main() { printf("%u %u %u\n", run(94), run(96), run(0)); }
'''.replace('TAIL', tail)
        tp = os.path.join(work, 'tail.cpp')
        open(tp, 'w').write(t)
        r = subprocess.run(['c++', '-std=c++11', '-w', tp, '-o', tp + '.x'], capture_output=True, text=True)
        if r.returncode:
            sys.exit('fromSpreadsheet stub compile failed:\n' + r.stderr[-2000:])
        a, b, c = subprocess.run([tp + '.x'], capture_output=True, text=True).stdout.split()
        report((a, b, c) == ('94', '96', '0'), 'fromSpreadsheet after a successful write returns the read code: 94->%s 96->%s 0->%s' % (a, b, c))
    ok = all(results)
    print('PASSED' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


main()

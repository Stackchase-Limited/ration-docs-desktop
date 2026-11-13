#!/usr/bin/env python3
"""
RD-0106 (found by corpus determinism checks; no upstream issue): an .xlsb sheet whose BrtWsProp
record is short (ends after the tab colour) got a made-up <sheetPr syncRef="..."> - a different
cell every run (seen: DU29165, DT30125) - in xlsx output and Editor.bin.

Cause: XLSB::WsProp::readFields (OOXML/XlsbFormat/Biff12_records/WsProp.cpp) reads rwSync/colSync
and the local flags; CFRecord::loadAnyData leaves a value it cannot read untouched (it returns
false, no exception), the constructor initialises nothing, so the heap garbage in rwSync/colSync
(!= 0xFFFFFFFF) became syncRef. Fix: flags start at 0 and rwSync/colSync at 0xFFFFFFFF ("none",
what writeFields writes) before the reads.

What runs: the REAL WsProp::readFields, extracted by brace matching, against a stub CFRecord whose
>> behaves as CFRecord's (a read past the end leaves the target unchanged), on a WsProp
constructed in memory filled with 0xAA (heap garbage, as MallocPreScribble gives): a full record,
a record that ends after the tab colour, and one that ends after the flags. Checked: syncRef is
empty unless the record holds a sync cell, and the full record's syncRef is read.
Also, only if RD_X2T is set (RD_X2T_BASE with BASELINE=1): a real xlsb with its WsProp cut to
11 bytes is converted to xlsx twice, once with MallocPreScribble=1; checked: no syncRef, same
output. RD_FONTS / RD_X2T_LIBS as in rd-0105. RD_XLSB=<an xlsb with a BrtWsProp> (default
core/OOXML/test/ExampleFiles/xlsb2xlsx/simple1.xlsb).
NOT claimed: other short BIFF12 records.

  RD_REPO=<core checkout> (default ../../core); BASELINE=1 reads BASE_REF and must FAIL.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'a6cdb71117^')
BASELINE = bool(os.environ.get('BASELINE'))
REL = 'OOXML/XlsbFormat/Biff12_records/WsProp.cpp'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(src, start):
    a = src.find(start)
    if a < 0:
        sys.exit(repr(start) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


DRIVER = r"""
#include <cstdio>
#include <cstring>
#include <string>
#include <new>
typedef unsigned short _UINT16; typedef unsigned char BYTE; typedef int _INT32; typedef unsigned int _UINT32;
#define GETBIT(from, num) ((from & (1 << num)) != 0)
namespace XLS {
  // as CFRecord::loadAnyData: a value past the end of the record is left as it was
  struct CFRecord { const unsigned char* d; size_t n, p; CFRecord(const unsigned char* d_, size_t n_) : d(d_), n(n_), p(0) {}
    template<class T> CFRecord& operator>>(T& v) { if (p + sizeof(T) <= n) { memcpy(&v, d + p, sizeof(T)); p += sizeof(T); } return *this; } };
}
struct CellRef { int r, c; CellRef(int r_, int c_, bool, bool) : r(r_), c(c_) {}
  operator std::wstring() const { return L"R" + std::to_wstring(r) + L"C" + std::to_wstring(c); } };
struct Color { void readFields(XLS::CFRecord& rec) { unsigned char b[8]; for (int i = 0; i < 8; ++i) rec >> b[i]; } };
struct XLNullableWideString { std::wstring s; };
inline XLS::CFRecord& operator>>(XLS::CFRecord& r, XLNullableWideString&) { return r; }
namespace XLSB {
  struct WsProp {
    bool fShowAutoBreaks, fPublish, fDialog, fApplyStyles, fRowSumsBelow, fColSumsRight, fFitToPage, fShowOutlineSymbols,
         fSyncHoriz, fSyncVert, fAltExprEval, fAltFormulaEntry, fFilterMode, fCondFmtCalc;
    Color brtcolorTab; _INT32 rwSync; _INT32 colSync; XLNullableWideString strName; std::wstring syncRef;
    WsProp() {}   // as the real one: initialises nothing
    void readFields(XLS::CFRecord& record);
  };
@@FN@@
}
int main(int argc, char** argv) {
  // flags1 flags2 | colour (8) | rwSync colSync | strName
  unsigned char full[] = {0xc9,0x04,0x02, 0x40,0,0,0,0,0,0,0, 5,0,0,0, 2,0,0,0, 0xff,0xff,0xff,0xff};
  size_t lens[] = { sizeof full, 11, 3 };
  for (size_t L : lens) {
    alignas(XLSB::WsProp) unsigned char mem[sizeof(XLSB::WsProp)];
    memset(mem, 0xAA, sizeof mem);
    XLSB::WsProp* w = new (mem) XLSB::WsProp();
    XLS::CFRecord rec{full, L};
    w->readFields(rec);
    printf("%zu %ls\n", L, w->syncRef.empty() ? L"-" : w->syncRef.c_str());
    w->~WsProp();
  }
  return 0;
}
"""


def run_extracted():
    fn = block(read(REL), 'void WsProp::readFields(XLS::CFRecord& record)')
    work = tempfile.mkdtemp(prefix='rd0106-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@FN@@', fn))
    r = subprocess.run(['c++', '-std=gnu++14', '-w', p, '-o', p[:-4]], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    out = dict(l.split(' ', 1) for l in subprocess.run([p[:-4]], capture_output=True, text=True).stdout.split('\n') if l)
    fails = 0
    for L, want, label in (('23', 'R5C2', 'full record: its sync cell is read'),
                           ('11', '-', 'record ends after the tab colour: no syncRef'),
                           ('3', '-', 'record ends after the flags: no syncRef')):
        ok = out.get(L) == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s: %s%s' % (label, out.get(L), '' if ok else '  (want %s)' % want))
    shutil.rmtree(work, ignore_errors=True)
    return fails


def recs_cut(data, rt, newlen):
    i = 0; out = b''; done = False
    while i < len(data):
        s = i; t = data[i]; i += 1
        if t & 0x80: t = (t & 0x7f) | ((data[i] & 0x7f) << 7); i += 1
        n = 0; sh = 0
        for _ in range(4):
            b = data[i]; i += 1; n |= (b & 0x7f) << sh; sh += 7
            if not b & 0x80: break
        hdr = data[s:i]; body = data[i:i + n]; i += n
        if t == rt and not done:
            out += hdr[:2 if hdr[0] & 0x80 else 1] + bytes([newlen]) + body[:newlen]; done = True
        else:
            out += hdr + body
    return out if done else None


def x2t(exe, src, dst, fmt, work, env_extra=None):
    td = tempfile.mkdtemp(dir=work)
    fonts = ''
    if os.environ.get('RD_FONTS'):
        fd = os.path.join(work, 'fonts')
        if not os.path.isdir(fd):
            shutil.copytree(os.environ['RD_FONTS'], fd)
        fonts = '<m_sFontDir>%s</m_sFontDir><m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath>' % (fd, fd)
    p = os.path.join(td, 'params.xml')
    open(p, 'w').write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo>'
                       '<m_nFormatTo>%d</m_nFormatTo>%s<m_sTempDir>%s</m_sTempDir></TaskQueueDataConvert>' % (src, dst, fmt, fonts, td))
    env = dict(os.environ, **(env_extra or {}))
    if os.environ.get('RD_X2T_LIBS'):
        env['DYLD_FRAMEWORK_PATH'] = env['LD_LIBRARY_PATH'] = os.environ['RD_X2T_LIBS']
    return subprocess.run([exe, p], capture_output=True, env=env, timeout=120).returncode


def run_x2t(exe):
    src = os.environ.get('RD_XLSB') or os.path.join(REPO, 'OOXML/test/ExampleFiles/xlsb2xlsx/simple1.xlsb')
    if not os.path.exists(src):
        print('skip x2t end-to-end: no %s' % src)
        return 0
    work = tempfile.mkdtemp(prefix='rd0106-x2t-')
    cut = os.path.join(work, 'short.xlsb')
    zi = zipfile.ZipFile(src); zo = zipfile.ZipFile(cut, 'w', zipfile.ZIP_DEFLATED); found = False
    for it in zi.infolist():
        d = zi.read(it.filename)
        if re.match(r'xl/worksheets/sheet\d+\.bin$', it.filename) and not found:
            c = recs_cut(d, 147, 11)
            if c is not None: d = c; found = True
        zo.writestr(it, d)
    zo.close()
    if not found:
        print('skip x2t end-to-end: no BrtWsProp in %s' % src)
        return 0
    outs = []
    for k, env in (('a', None), ('b', {'MallocPreScribble': '1'})):
        o = os.path.join(work, k + '.xlsx')
        rc = x2t(exe, cut, o, 0x0101, work, env)
        outs.append(re.findall(r'<sheetPr[^>]*>', zipfile.ZipFile(o).read('xl/worksheets/sheet1.xml').decode()) if not rc else ['rc=%d' % rc])
    ok = outs[0] == outs[1] and 'syncRef' not in ' '.join(outs[0])
    print(('ok   ' if ok else 'FAIL ') + 'x2t short-WsProp xlsb -> xlsx (twice, once scribbled): %s' % ' | '.join(sorted(set(sum(outs, [])))))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


def main():
    fails = run_extracted()
    print('(%s)' % ('baseline ' + BASE_REF if BASELINE else 'working tree'))
    exe = os.environ.get('RD_X2T_BASE') if BASELINE else os.environ.get('RD_X2T')
    if exe:
        fails += run_x2t(exe)
    else:
        print('skip x2t end-to-end (set RD_X2T, and RD_X2T_BASE for BASELINE=1)')
    print('%s: %d failure(s)' % ('BASELINE' if BASELINE else 'FIX', fails))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

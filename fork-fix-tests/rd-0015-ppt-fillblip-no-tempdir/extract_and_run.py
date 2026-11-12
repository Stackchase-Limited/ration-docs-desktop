#!/usr/bin/env python3
"""
RD-0015 (our corpus run, no upstream issue): opening a .ppt whose shape
properties carry a fill picture inline (fillBlip with the blip record in the
property table, as Apache OpenOffice writes them) crashed x2t (SIGSEGV).

Found on POI's "119877_all type background_save_by_AOO.ppt": the release x2t
dies with SIGSEGV on open; the AddressSanitizer x2t shows SEGV at address 0x17
in CRecordOfficeArtBlip::ReadFromStream
(MsBinaryFile/PptFile/Records/Drawing/ArtBlip.cpp), called from
CProperty::ComplexFromStream (MsBinaryFile/Common/Vml/PPTShape/ElementSettings.cpp).

Cause: for an ODRAW::fillBlip property ComplexFromStream reads the inline blip
with a local `PPT::CRecordOfficeArtBlip art_blip;` only to step over it (the
result is thrown away). Such a record has no m_pCommonInfo (NULL), but
ReadFromStream writes the picture to m_pCommonInfo->tempPath for every blip
type. Fix: without m_pCommonInfo, ReadFromStream steps over the record's RecLen
bytes - what a full read consumes - and returns.

What runs: the REAL CRecordOfficeArtBlip::ReadFromStream is lifted out of
ArtBlip.cpp by brace matching (git show BASE_REF:... with BASELINE=1) and
compiled with -fsanitize=address with the real PPTFileDefines.h and small
stand-ins for the record base class, POLE stream, StreamUtils, metafile/
picture helpers and NSFile::CFileBinary. It reads a 40-byte JPEG blip record
from a memory stream on an object without m_pCommonInfo, as ComplexFromStream
does. Passes when ASan reports nothing and the stream is positioned after the
record (40 bytes).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read ArtBlip.cpp at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0015 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '7bdeb60fa3^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def block(text, start):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    b = text.find('{', a)
    depth = 0
    for i in range(b, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
    sys.exit('unbalanced braces after %r' % start)


DRIVER = r'''
#include <cstdio>
#include <cstring>
#include <string>
#include <map>
#include <vector>
#include <algorithm>
typedef unsigned char BYTE; typedef unsigned short WORD; typedef unsigned int _UINT32; typedef long LONG;
#define TRUE 1
#define FILE_SEPARATOR_STR L"/"
#include "PPTFileDefines.h"
namespace POLE { struct Stream { std::vector<BYTE> d; size_t pos = 0;
    unsigned long long read(BYTE* p, unsigned long long n) { size_t k = std::min<size_t>(n, d.size() - std::min(pos, d.size())); if (k) memcpy(p, d.data() + pos, k); pos += n; return k; }
    void seek(unsigned long long p) { pos = p; } unsigned long long tell() { return pos; } }; }
namespace StreamUtils { inline void StreamSkip(long n, POLE::Stream* s) { s->pos += n; } }
namespace CRYPT { struct Decryptor { void Decrypt(char*, long, int) {} }; }
namespace Gdiplus { struct ENHMETAHEADER3 {}; struct WmfPlaceableFileHeader { char b[22]; }; }
namespace NSFile { struct CFileBinary { bool CreateFileW(const std::wstring&) { return false; } void WriteFile(const BYTE*, long) {}
    void CloseFile() {} static bool Remove(const std::wstring&) { return true; } }; }
struct CMetaHeader { unsigned int cbSave = 0, cbSize = 0; BYTE compression = 0xFE;
    void FromStream(POLE::Stream* s, CRYPT::Decryptor*) { s->pos += 34; }
    void ToEMFHeader(Gdiplus::ENHMETAHEADER3*) {} void ToWMFHeader(Gdiplus::WmfPlaceableFileHeader*) {} };
struct CMetaFileBuffer { bool m_bIsValid = false; std::wstring m_sExtension;
    void SetHeader(BYTE* p, long) { delete[] p; } void SetData(BYTE* p, unsigned, unsigned, bool, int) { delete[] p; }
    unsigned ToBuffer(BYTE*& p) { p = NULL; return 0; } void ToFile(NSFile::CFileBinary*) {} };
struct CBgraFrame { bool OpenFile(const std::wstring&) { return false; } bool SaveFile(const std::wstring&, int) { return false; } };
namespace PPT {
    struct SRecordHeader { BYTE RecVersion = 0; unsigned short RecInstance = 0, RecType = 0; unsigned int RecLen = 0; };
    struct _commonInfo { std::wstring tempPath; };
    struct CPPTUserInfo { CRYPT::Decryptor* m_pDecryptor = NULL; };
    struct CPPTDocumentInfo { std::vector<CPPTUserInfo*> m_arUsers; std::map<int, std::wstring> m_mapStoreImageFile; };
    struct CUnknownRecord { _commonInfo* m_pCommonInfo = NULL; };
    struct CRecordOfficeArtBlip : CUnknownRecord { CPPTDocumentInfo* m_pDocumentInfo = NULL; std::wstring m_fileName;
        void ReadFromStream(SRecordHeader& oHeader, POLE::Stream* pStream); };
}
using namespace PPT;
@@READ@@
int main() {
    POLE::Stream s; s.d.assign(40, 0xAB);
    SRecordHeader h; h.RecType = RECORD_TYPE_ESCHER_BLIP_JPEG; h.RecInstance = 0x046A; h.RecLen = 40;
    CRecordOfficeArtBlip art_blip;          /* as CProperty::ComplexFromStream: no common info */
    art_blip.ReadFromStream(h, &s);
    printf("POS=%zu\n", s.pos);
    return 0;
}
'''


def main():
    src = read('MsBinaryFile/PptFile/Records/Drawing/ArtBlip.cpp')
    fn = block(src, 'void CRecordOfficeArtBlip::ReadFromStream(SRecordHeader & oHeader, POLE::Stream* pStream)')
    work = tempfile.mkdtemp(prefix='rd0015-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(DRIVER.replace('@@READ@@', fn))
    exe = os.path.join(work, 'drv')
    inc = '-I' + os.path.join(REPO, 'MsBinaryFile', 'PptFile', 'Reader')
    r = subprocess.run(['c++', '-std=gnu++11', '-fsanitize=address', '-g', '-w', inc, p, '-o', exe],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    r = subprocess.run([exe], capture_output=True, text=True, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
    out = r.stdout + r.stderr
    a = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    ok = r.returncode == 0 and not a and 'POS=40' in out
    print(('ok   ' if ok else 'FAIL ') + 'inline fillBlip JPEG record without common info (%s): %s' % (
        'baseline ' + BASE_REF if BASELINE else 'working tree',
        ('ASan ' + a.group(1)) if a else ('stepped over, stream at 40' if ok else out.strip()[-300:])))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
ONLYOFFICE 10.0 security backports in core (x2t), the ones we wrote or ported
ourselves rather than cherry-picked clean. Each case lifts the REAL code out of
core and runs it under AddressSanitizer with minimal stubs.

1. libxml2 CVE-2022-23308 ("Fixed CVE-2022-23308 vulnerability during document
   conversion"). Our vendored libxml2 (DesktopEditor/xml/libxml2, 2.9.2-era)
   decided in xmlAddID whether the attribute outlives the call from
   ctxt->vstateNr, which is 0 when the reader does not validate - how every
   x2t reader runs. The ID table kept a pointer to an attribute the reader then
   freed into its node cache. Case: the whole vendored libxml2 is compiled
   (DesktopEditor/xml/build/qt/libxml2_all*.c, the defines of libxml2.pri) and
   a document with an xml:id is streamed; afterwards xmlGetID() must not hand
   back an attribute that is no longer in the tree.
2. PPT metafile blips ("out-of-bounds read when processing PPT metafiles, which
   led to memory disclosure in the resulting PPTX"; no upstream commit - ours).
   CMetaFileBuffer::SetData/ToBuffer (PptFile/Reader/ReadStructures.cpp) are
   compiled with the REAL SetData call of ArtBlip.cpp's EMF branch; a 64-byte
   uncompressed blip that declares cbSize 100000 must not be copied out as
   100000 bytes.
3. DOC piece table ("out-of-bounds read when parsing the piece table in DOC
   files"; the constructor is unchanged in v10 - ours). The REAL
   PieceTable::PieceTable (DocFile/PieceTable.cpp) with the REAL
   FormatUtils::BytesToInt32 runs on a 8-byte Clx whose PlcPcd claims 1000
   bytes.
4. XPS font key ("stack buffer overflow when processing fonts in XPS files";
   upstream ea2e501405, cherry-picked). The REAL XPS::CFontList::GetFontKey /
   GetIntegerFromHex (XpsLib/FontList.h) fill a 16-byte stack key from an
   obfuscated font's file name; a 64-hex-digit name must not overrun it.

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; every case must FAIL
  BASE_REF                  default: the parent of the first of these commits
                            on wip/v10-security (the integrator re-pins it)

NOT claimed: a full x2t conversion of a crafted file (x2t was not rebuilt; the
upstream cherry-picks in the same branch - DOC CHPX/font table, WMF ClipBuffer,
EMF PolyBezier, HWP media path, circular styles, PDF image masks, ZipEmbed -
are not exercised here); that libxml2's reader reaches xmlGetID inside x2t
(the dangling entry is shown, not a crash in a converter). macOS clang with
-fsanitize=address; Linux was syntax-checked separately.
"""
import os
import re
import subprocess
import sys
import tarfile
import io
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
# Pinned to the parent of the first commit of these fixes, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'c5d814c502^')
BASELINE = bool(os.environ.get('BASELINE'))
ASAN = ['-fsanitize=address', '-fno-omit-frame-pointer', '-g', '-w']


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig').read()


def block(text, start, what='{'):
    a = text.find(start)
    if a < 0:
        sys.exit('%r not found - the extractor needs updating' % start)
    a = text.rfind('\n', 0, a) + 1     # from the start of the line (return type)
    b = text.find(what, a)
    depth, i = 0, b
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == "'":
            i += 1
            while text[i] != "'":
                i += 2 if text[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[a:i + 1]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


def build_run(work, name, src, extra=(), lang='c++'):
    p = os.path.join(work, name + ('.cpp' if lang == 'c++' else '.c'))
    open(p, 'w').write(src)
    exe = os.path.join(work, name)
    cmd = (['c++', '-std=c++11'] if lang == 'c++' else ['cc']) + ASAN + ['-o', exe, p] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('compile of %s failed:\n%s' % (name, r.stderr[-3000:]))
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:abort_on_error=0')
    r = subprocess.run([exe], capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    m = re.search(r'ERROR: AddressSanitizer: ([\w-]+)', out)
    return r.returncode, r.stdout.strip(), (m.group(1) if m else None)


results = []


def report(name, ok, detail):
    results.append(ok)
    print(('ok   ' if ok else 'FAIL ') + name + ': ' + detail)


# ---------------------------------------------------------------- 1 libxml2
def case_libxml2(work):
    root = os.path.join(work, 'xmlsrc')
    os.makedirs(root)
    if BASELINE:
        tar = subprocess.run(['git', '-C', REPO, 'archive', BASE_REF, 'DesktopEditor/xml/libxml2',
                              'DesktopEditor/xml/build/qt'], capture_output=True, check=True).stdout
        tf = tarfile.open(fileobj=io.BytesIO(tar))
        tf.extractall(root, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
        x = os.path.join(root, 'DesktopEditor', 'xml')
    else:
        x = os.path.join(REPO, 'DesktopEditor', 'xml')
    pri = open(os.path.join(x, 'build', 'qt', 'libxml2.pri')).read()
    defs = ['-D' + d for d in re.findall(r'\b(LIBXML_\w+|IN_LIBXML|HAVE_VA_COPY)\b', pri)]
    inc = ['-I' + os.path.join(x, 'libxml2', 'include'), '-I' + os.path.join(x, 'libxml2', 'include', 'libxml'),
           '-I' + os.path.join(x, 'build', 'qt')]
    objs = []
    for unit in ('libxml2_all', 'libxml2_all2'):
        o = os.path.join(work, unit + '.o')
        r = subprocess.run(['cc', '-c'] + ASAN + ['-include', 'unistd.h'] + defs + inc +
                           [os.path.join(x, 'build', 'qt', unit + '.c'), '-o', o], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit('libxml2 compile failed:\n' + r.stderr[-3000:])
        objs.append(o)
    src = r'''
#include <stdio.h>
#include <string.h>
#include <libxml/xmlreader.h>
#include <libxml/valid.h>
int main(void) {
    /* x2t's readers: xmlReaderForMemory, options 0 (no validation) */
    const char *x = "<r><e xml:id=\"a\"/><f/><h k=\"1\"/><i/><g/></r>";
    xmlTextReaderPtr r = xmlReaderForMemory(x, strlen(x), NULL, NULL, 0);
    while (xmlTextReaderRead(r) == 1)
        if (!strcmp((const char*)xmlTextReaderConstName(r), "g")) break;
    xmlDocPtr d = xmlTextReaderCurrentDoc(r);   /* stops further freeing */
    xmlAttrPtr a = xmlGetID(d, (const xmlChar*)"a");
    if (a == NULL || (void*)a == (void*)d) { printf("SAFE\n"); return 0; }
    int found = 0;
    for (xmlNodePtr c = xmlDocGetRootElement(d)->children; c; c = c->next)
        for (xmlAttrPtr p = c->properties; p; p = p->next) if (p == a) found = 1;
    printf(found ? "SAFE-IN-TREE\n" : "DANGLING\n");
    return 0;
}
'''
    rc, out, asan = build_run(work, 'xmlid', src, objs + inc + defs + ['-lz', '-liconv', '-lm'], lang='c')
    ok = rc == 0 and asan is None and out.startswith('SAFE')
    report('libxml2: a streamed xml:id leaves no freed attribute in the ID table', ok,
           'xmlGetID after the element was freed -> %s%s' % (out, (' / ASan ' + asan) if asan else ''))


# ---------------------------------------------------------------- 2 PPT blip
def case_ppt(work):
    h = read('MsBinaryFile/PptFile/Reader/ReadStructures.h')
    c = read('MsBinaryFile/PptFile/Reader/ReadStructures.cpp')
    art = read('MsBinaryFile/PptFile/Records/Drawing/ArtBlip.cpp')
    cls = block(h, 'class CMetaFileBuffer') + ';'
    fns = '\n'.join(block(c, 'CMetaFileBuffer::' + f) for f in
                    ('CMetaFileBuffer()', '~CMetaFileBuffer()', 'SetHeader(', 'SetData(', 'ToBuffer('))
    emf = block(art, 'case RECORD_TYPE_ESCHER_BLIP_EMF:')
    call = re.search(r'oMetaFile\.SetData\((.*?)\);', emf, re.S)
    if not call:
        sys.exit('SetData call not found in ArtBlip.cpp EMF branch')
    src = r'''
#include <cstdio>
#include <cstring>
#include <string>
#include <new>
#include <algorithm>
typedef unsigned char BYTE; typedef long LONG; typedef unsigned long ULONG;
#define RELEASEARRAYOBJECTS(p) { if (p) { delete[] p; p = NULL; } }
namespace NSFile { class CFileBinary { public: void WriteFile(BYTE*, LONG) {} }; }
namespace NSZip { bool Decompress(const BYTE*, ULONG, BYTE*, ULONG&) { return false; } }
CLS
FNS
struct MetaHeader { unsigned int cbSave, cbSize; BYTE compression; };
int main() {
    /* EMF blip record: RecLen - lOffset = 64 bytes of data, header says 100000 */
    int nDataSize = 64;
    BYTE* pData = new BYTE[nDataSize]();
    MetaHeader oMetaHeader = { 64, 100000, 0xFE };   /* 0xFE: not compressed */
    CMetaFileBuffer oMetaFile;
    oMetaFile.SetData(CALL);
    BYTE* out = NULL;
    int n = oMetaFile.ToBuffer(out);
    printf("copied=%d\n", n);
    return 0;
}
'''.replace('CLS', cls).replace('FNS', fns).replace('CALL', call.group(1))
    rc, out, asan = build_run(work, 'pptblip', src)
    ok = rc == 0 and asan is None and out == 'copied=64'
    report('PPT: a blip declaring more bytes than its record holds is not copied past the record', ok,
           '64-byte record, cbSize 100000 -> %s%s' % (out or '(crashed)', (' / ASan ' + asan) if asan else ''))


# ---------------------------------------------------------------- 3 DOC piece table
def case_piecetable(work):
    c = read('MsBinaryFile/DocFile/PieceTable.cpp')
    fu = read('MsBinaryFile/Common/Base/FormatUtils.h')
    ctor = block(c, 'PieceTable::PieceTable (')
    b2i = block(fu, 'static inline int BytesToInt32(')
    src = r'''
#include <cstdio>
#include <cstring>
#include <list>
#include <map>
#include <vector>
#define RELEASEARRAYOBJECTS(p) { if (p) { delete[] p; p = NULL; } }
#define ENCODING_UTF16 1200
typedef int _INT32;
typedef std::pair<int, int> Int_Pair;
struct FormatUtils { B2I };
namespace POLE { struct Stream { std::vector<unsigned char> d; size_t p = 0;
    size_t size() { return d.size(); } void seek(size_t n) { p = n; }
    size_t read(unsigned char* b, size_t n) { size_t k = 0; while (k < n && p < d.size()) b[k++] = d[p++]; return k; } }; }
struct FileInformationBlock { struct { unsigned int fcClx, lcbClx; } m_FibWord97; struct { int fcMac; } m_FibBase; int m_CodePage; };
struct PieceDescriptor { unsigned int fc; int cpStart, cpEnd, code_page;
    PieceDescriptor(unsigned char* b, int, int cp) : fc(b[2] | b[3] << 8), cpStart(0), cpEnd(0), code_page(cp) {} };
namespace DocFileFormat {
struct PieceTable {
    std::list<PieceDescriptor> Pieces; std::map<int, int>* FileCharacterPositions; std::map<int, int>* CharacterPositions;
    std::list<PieceDescriptor>::iterator m_carriageIter;
    PieceTable(FileInformationBlock* fib, POLE::Stream* tableStream, POLE::Stream* wordStream);
};
CTOR
}
int main() {
    /* Clx of 8 bytes: Pcdt (type 2) whose lcb says the PlcPcd is 1000 bytes long */
    POLE::Stream table, word;
    table.d = { 0x02, 0xE8, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00 };
    word.d.assign(4096, 0);
    FileInformationBlock fib; fib.m_FibWord97.fcClx = 0; fib.m_FibWord97.lcbClx = 8;
    fib.m_FibBase.fcMac = 0; fib.m_CodePage = 1252;
    DocFileFormat::PieceTable t(&fib, &table, &word);
    printf("pieces=%d\n", (int)t.Pieces.size());
    return 0;
}
'''.replace('B2I', b2i).replace('CTOR', ctor)
    rc, out, asan = build_run(work, 'piecetable', src)
    ok = rc == 0 and asan is None
    report('DOC: a PlcPcd longer than its Clx is not read past the Clx', ok,
           '8-byte Clx, lcb 1000 -> %s%s' % (out or '(crashed)', (' / ASan ' + asan) if asan else ''))


# ---------------------------------------------------------------- 4 XPS font key
def case_xps(work):
    h = read('XpsFile/XpsLib/FontList.h')
    key = block(h, 'void GetFontKey(')
    hexf = block(h, 'int GetIntegerFromHex(')
    hexd = block(h, 'int GetIntegerFromHexChar(') if 'GetIntegerFromHexChar(' in h else ''
    src = r'''
#include <cstdio>
#include <string>
#include <sstream>
#include <iostream>
struct K {
HEXD
HEXF
KEY
};
int main() {
    std::wstring name;
    for (int i = 0; i < 64; i++) name += L"0123456789ABCDEF"[i % 16];
    name += L".odttf";
    name = name.substr(0, 64);
    unsigned char sKey[16];
    K().GetFontKey(name, sKey);
    printf("key-ok\n");
    return 0;
}
'''.replace('HEXD', hexd).replace('HEXF', hexf).replace('KEY', key)
    rc, out, asan = build_run(work, 'xpskey', src)
    ok = rc == 0 and asan is None and out == 'key-ok'
    report('XPS: a long obfuscated-font name does not overrun the 16-byte key', ok,
           '64 hex digits -> %s%s' % (out or '(crashed)', (' / ASan ' + asan) if asan else ''))


with tempfile.TemporaryDirectory() as work:
    case_xps(work)
    case_piecetable(work)
    case_ppt(work)
    case_libxml2(work)

failed = results.count(False)
print('%d case(s) FAILED' % failed if failed else 'all cases passed')
sys.exit(1 if failed else 0)

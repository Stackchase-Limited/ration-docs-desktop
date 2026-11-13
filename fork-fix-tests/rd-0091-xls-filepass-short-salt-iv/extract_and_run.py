#!/usr/bin/env python3
"""
RD-0091 (our crafted-input audit, no upstream issue): an encrypted .xls whose
FilePass record ends before its salt (2 bytes "0100", or 4 bytes "01000400")
made x2t read 16 bytes from an empty buffer - ASan heap-buffer-overflow READ of
size 16 in CBC_Decryption's constructor, from DecryptCipher
(OfficeCryptReader/source/CryptTransform.cpp) via ECMADecryptor::SetPassword
and GlobalsSubstream's default-password try.

Cause: the short header leaves the ECMA crypt data at its defaults (AES-CBC,
saltSize 16, empty salt); SetPassword passes the salt as the iv and the CBC
mode copies a whole block from it.
Fix: DecryptCipher zero-pads an iv shorter than 16 bytes before any cipher
reads it.

What runs: the REAL class _buf and the REAL DecryptCipher from
CryptTransform.cpp, with the REAL CRYPT_METHOD enums from CryptTransform.h,
-fsanitize=address. Crypto++ is replaced by a stand-in that does what the real
modes do with the iv - CBC/CFB copy one 16/8-byte block from it at
construction, ECB ignores it - and "decrypts" by XOR with that block, so the
output shows which iv bytes were used. NOT claimed: real AES output.
Cases: AES-CBC with an empty iv (the crafted file's salt) and with a 1-byte iv
(before: over-read; now zero-padded, output = input), and with a full 16-byte
iv (unchanged, output = input XOR iv).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0091 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '8a74f585e9^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig', 'replace')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig', errors='replace').read()


def func(src, sig, frm=0):
    """sig ... its brace-matched body (the REAL code)."""
    a = src.find(sig, frm)
    if a < 0:
        sys.exit(repr(sig) + ' not found - the extractor needs updating')
    i = src.find('{', a); depth = 0
    while True:
        if src[i] == '{': depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0: return src[a:i + 1]
        i += 1


def span(src, start, end, frm=0):
    """The statements from `start` up to (not including) `end` (the REAL code)."""
    a = src.find(start, frm)
    b = src.find(end, a + len(start)) if a >= 0 else -1
    if a < 0 or b < 0:
        sys.exit(repr(start) + ' .. ' + repr(end) + ' not found - the extractor needs updating')
    return src[a:b]


def build_run(code, cases, tag):
    """Compile with ASan, run each (arg, label, expected stdout); print ok/FAIL; return #failures."""
    work = tempfile.mkdtemp(prefix=tag + '-')
    p = os.path.join(work, 'drv.cpp')
    open(p, 'w').write(code)
    exe = p[:-4]
    r = subprocess.run(['c++', '-std=gnu++14', '-fsanitize=address', '-g', '-w', p, '-o', exe], capture_output=True, text=True)
    if r.returncode:
        sys.exit('build failed:\n' + r.stderr[-3000:])
    fails = 0
    for arg, label, want in cases:
        r = subprocess.run([exe, arg], capture_output=True, text=True,
                           env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:alloc_dealloc_mismatch=0:allocator_may_return_null=1'))
        m = re.search(r'ERROR: AddressSanitizer: (out of memory|requested allocation size|[\w-]+)', r.stderr)
        ok = r.returncode == 0 and not m and r.stdout.strip() == want
        fails += not ok
        print(('ok   ' if ok else 'FAIL ') + '%s (%s): %s' % (label, 'baseline ' + BASE_REF if BASELINE else 'working tree',
              ('ASan ' + m.group(1)) if m else (r.stdout.strip() or r.stderr.strip()[-200:] or 'rc=%d' % r.returncode)))
    return fails



S = 'OfficeCryptReader/source/'

STUB = r"""
#include <cstdio>
#include <cstring>
#include <string>
#include <algorithm>
typedef unsigned short UTF16; typedef unsigned int UTF32;
enum ConversionResult { conversionOK }; enum ConversionFlags { strictConversion };
static ConversionResult ConvertUTF32toUTF16(const UTF32**, const UTF32*, UTF16**, UTF16*, ConversionFlags) { return conversionOK; }
namespace CryptoPP {
typedef unsigned char byte;
struct Cipher { Cipher(const byte*, size_t) {} };
struct AES { struct Decryption : Cipher { using Cipher::Cipher; }; };
struct DES { struct Decryption : Cipher { using Cipher::Cipher; }; };
struct Blowfish {};
struct CBC_Decryption {}; struct ECB_OneWay {};
struct StreamTransformation { byte reg[16]; StreamTransformation() { memset(reg, 0, 16); } virtual ~StreamTransformation() {}
  void ProcessData(byte* o, const byte* i, size_t n) { for (size_t k = 0; k < n; k++) o[k] = i[k] ^ reg[k % 16]; } };
// the real modes: CBC/CFB copy one block of the iv when constructed, ECB never reads it
template<class M> struct CipherModeFinalTemplate_ExternalCipher : StreamTransformation {
  template<class C> CipherModeFinalTemplate_ExternalCipher(C&, const byte* iv) { memcpy(reg, iv, 16); } };
template<> struct CipherModeFinalTemplate_ExternalCipher<ECB_OneWay> : StreamTransformation {
  template<class C> CipherModeFinalTemplate_ExternalCipher(C&, const byte*) {} };
template<class C> struct CFB_Mode { struct Decryption : StreamTransformation { Decryption(const byte*, size_t, const byte* iv) { memcpy(reg, iv, 8); } }; };
struct ArraySink { byte* p; size_t n; ArraySink(byte* p_, size_t n_) : p(p_), n(n_) {} };
struct StreamTransformationFilter {
  enum BlockPaddingScheme { NO_PADDING, ZEROS_PADDING, PKCS_PADDING, ONE_AND_ZEROS_PADDING, W3C_PADDING, DEFAULT_PADDING };
  StreamTransformation& m; ArraySink* s;
  StreamTransformationFilter(StreamTransformation& m_, ArraySink* s_, BlockPaddingScheme) : m(m_), s(s_) {}
  ~StreamTransformationFilter() { delete s; }
  void Put(const byte* d, size_t n) { m.ProcessData(s->p, d, std::min(n, s->n)); } void MessageEnd() {} };
struct ARC4 { struct Decryption { void ProcessData(byte* o, const byte* i, size_t n) { memcpy(o, i, n); } void SetKey(const byte*, size_t) {} }; };
}
using namespace CryptoPP;
"""


def main():
    cpp = read(S + 'CryptTransform.cpp'); h = read(S + 'CryptTransform.h')
    code = STUB + func(h, 'namespace CRYPT_METHOD') + '\n' + span(cpp, 'class _buf', 'bool operator==(const _buf& oBuf1') + '\n'
    code += 'ARC4::Decryption rc4Decryption;\n' + func(cpp, 'bool DecryptCipher(') + r"""
int main(int argc, char** argv) {
  std::string m = argv[1];
  std::string salt = m == "empty" ? std::string() : m == "one" ? std::string("\x01", 1) : std::string("\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10", 16);
  _buf key(16, true), iv(salt), inp(16, true), out;
  for (int i = 0; i < 16; i++) inp.ptr[i] = (unsigned char)(0xA0 + i);
  DecryptCipher(key, iv, inp, out, CRYPT_METHOD::AES_CBC);
  for (int i = 0; i < out.size; i++) printf("%02x", out.ptr[i]); printf("\n");
  return 0;
}
"""
    fails = build_run(code, [('empty', 'AES-CBC, empty iv (FilePass without salt)', 'a0a1a2a3a4a5a6a7a8a9aaabacadaeaf'),
                             ('one', 'AES-CBC, 1-byte iv', 'a1a1a2a3a4a5a6a7a8a9aaabacadaeaf'),
                             ('full', 'AES-CBC, 16-byte iv (unchanged)', 'a1a3a1a7a1a3a1afa1a3a1a7a1a3a1bf')], 'rd0091')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

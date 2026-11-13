#!/usr/bin/env python3
"""
RD-0092 (our crafted-input audit, no upstream issue): an encrypted .xls with a
BoundSheet8 record shorter than 4 bytes made x2t decrypt past the record.
Crafted POI files with the first BoundSheet8 cut to 2 bytes (the rest of its
bytes made into an unknown record), converted with the right password, under
ASan: xor-encryption-abc.xls - heap-buffer-overflow in XORCrypt::Decrypt
(read-modify-write past the 2-byte record); password.xls (RC4) and
35897-type4.xls (RC4 CryptoAPI) - new[] of 0xfffffffffffffffe bytes in
RC4Crypt::Decrypt / ECMADecryptor::Decrypt.

Cause (MsBinaryFile/XlsFile/Format/Binary/CFRecord.cpp, CFRecord::CFRecord):
a BIFF8 BoundSheet8 is decrypted from byte 4 on (lbPlyPos is in clear) with
Decrypt(data_ + 4, size_ - 4, ...); for a shorter record size_ - 4 wraps.
Fix: a BoundSheet8 of 4 bytes or less is not decrypted (nothing in it is).

What runs: the REAL "case rt_BoundSheet8:" branch of the decrypting switch in
CFRecord::CFRecord, -fsanitize=address, with a stand-in decryptor that does
what every real one does with its range - transforms each byte in place (here
XOR 0x01) - and reports the range. NOT claimed: real XOR/RC4 output.
Cases: BIFF8 BoundSheet8 of 2 bytes (before: decrypts ~2^64 bytes from past
the record; now untouched), of 4 bytes (nothing to decrypt either way), of 8 bytes (bytes 4-7
decrypted, unchanged), and a BIFF5 one of 2 bytes (whole record, unchanged).

  RD_REPO=<core checkout>   (default ../../core)
  BASELINE=1                read the sources at BASE_REF; must FAIL
  BASE_REF                  default: parent of the RD-0092 commit
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'be82c083d8^')
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



X = 'MsBinaryFile/XlsFile/Format/'

HEAD = r"""
#include <cstdio>
#include <cstring>
#include <string>
#include <memory>
struct Decryptor { void Decrypt(char* data, const size_t size, const unsigned long stream_pos, const size_t block_size) {
  if (size) printf("decrypt %lu+%lu ", (unsigned long)stream_pos, (unsigned long)size); for (size_t i = 0; i < size; i++) data[i] ^= 1; } };
struct GlobalWorkbookInfo { unsigned short Version; std::shared_ptr<Decryptor> decryptor; };
enum { rt_BoundSheet8 = 0x0085 };
static void decrypt(GlobalWorkbookInfo* global_info, char* data_, size_t size_, unsigned long rec_data_pos) {
  size_t block_size = 1024; unsigned short type_id_ = rt_BoundSheet8;
  switch (type_id_) {
"""


def main():
    ctor = func(read(X + 'Binary/CFRecord.cpp'), 'CFRecord::CFRecord(CFStreamPtr stream')
    code = HEAD + span(ctor, 'case rt_BoundSheet8:', 'default:') + r"""
    default: break; } }
int main(int argc, char** argv) {
  std::string m = argv[1]; GlobalWorkbookInfo g; g.decryptor.reset(new Decryptor); g.Version = m == "biff5" ? 0x0500 : 0x0600;
  size_t n = m == "biff8_4" ? 4 : m == "biff8_8" ? 8 : 2;
  char* data = new char[n]; for (size_t i = 0; i < n; i++) data[i] = (char)(0x10 + i);
  decrypt(&g, data, n, 100);
  for (size_t i = 0; i < n; i++) printf("%02x", (unsigned char)data[i]); printf("\n"); delete[] data; return 0;
}
"""
    fails = build_run(code, [('biff8_2', 'BIFF8 BoundSheet8 of 2 bytes', '1011'),
                             ('biff8_4', 'BIFF8 BoundSheet8 of 4 bytes (unchanged)', '10111213'),
                             ('biff8_8', 'BIFF8 BoundSheet8 of 8 bytes (unchanged)', 'decrypt 104+4 1011121315141716'),
                             ('biff5', 'BIFF5 BoundSheet of 2 bytes (unchanged)', 'decrypt 100+2 1110')], 'rd0092')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

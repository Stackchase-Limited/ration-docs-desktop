#!/usr/bin/env python3
"""
#1664 (security follow-up) - documents fed WebP and AVIF bytes to Chromium 109's
image decoders.

Our CEF 109 has the libwebp heap overflow that was exploited in the wild
(CVE-2023-4863) and an AVIF decoder (libavif/dav1d) with later memory bugs.
x2t copies a picture's bytes into the media folder unchanged, so a WebP stored
as word/media/image1.png (or an AVIF as image5.png) was loaded by the editor
from file:// with <img> and decoded as what it really is: in a copy of the
test app the editor received RIFF....WEBP and ftypavif bodies and drew both
(naturalWidth 64). Remote pictures (cloud documents, pasted HTML, plugins)
were the same, and servers sent WebP because Accept asked for it.

Now CAscClientHandler (desktop-sdk cefview.cpp) installs CImageGuardFilter
(image_guard.h) through GetResourceResponseFilter on every response except
top-level navigations/downloads, scripts, styles, fonts and workers, and
OnBeforeResourceLoad drops image/webp and image/avif from the Accept header
of http(s) requests. The filter holds back only the first bytes while they
can still be "RIFF" <size> "WEBP" or an ftyp box with an avif/avis brand, and
fails the response if they are; everything else passes byte for byte.

This compiles the REAL image_guard.h against the REAL CEF 109 headers in the
repository, and the REAL bodies of GetResourceResponseFilter and
OnBeforeResourceLoad (taken from cefview.cpp by brace matching) against a stub
request, and drives the filter the way CEF does (input in chunks, a small
output buffer, calls with empty input at the end of the response).

Claimed: WebP (lossy, lossless, extended, under a .png name) and AVIF (major
brand, compatible brand, avis) fail; PNG, JPEG, GIF, BMP, ICO, SVG, mp4/mov
(ftyp without an avif brand), WAV (RIFF but not WEBP), Editor.bin, empty and
tiny (1-11 byte) bodies and a 3 MB body come out identical, whatever the
chunking and output-buffer size; image, XHR, fetch, sub-frame, media and
favicon requests get the filter; Accept loses exactly image/webp and image/avif.
NOT claimed here (checked live in an APFS clone of the test app, see the
report): that CEF calls the filter for file:// and ascdesktop:// responses and
calls it once more with empty input at the end of a response (it does: 3-,
5-, 6- and 10-byte files arrived intact) - the driver below assumes it.

  RD_REPO=<desktop-sdk checkout>   (default ../../desktop-sdk)
  BASELINE=1                       read sources at BASE_REF; must FAIL
  BASE_REF                         default a000faca^ (the parent of the fix)
"""
import base64
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'a000faca^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'
CEF = os.path.join(REPO, SRC, 'cef/mac')  # vendored CEF 109 headers, not part of the fix


def read(rel, missing_ok=False):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            if missing_ok:
                return None
            sys.exit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    p = os.path.join(REPO, rel)
    if missing_ok and not os.path.exists(p):
        return None
    return open(p, encoding='utf-8').read()


def brace_body(text, start):
    """The text inside the braces of the block whose header contains `start`."""
    a = text.find(start)
    if a < 0:
        return None
    b = text.find('{', a)
    depth = 0
    i = b
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == '\\' else 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[b + 1:i]
        i += 1
    sys.exit('unbalanced braces after %r' % start)


B64 = {
    'webp-lossless': 'UklGRiIAAABXRUJQVlA4TBYAAAAvP8APAAfQ//5H/wNAQvj/Xovof+oH',
    'avif': 'AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUEAAADrbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAAAAAAAOcGl0bQAAAAAAAQAAAB5pbG9jAAAAAEQAAAEAAQAAAAEAAAETAAAAIgAAAChpaW5mAAAAAAABAAAAGmluZmUCAAAAAAEAAGF2MDFDb2xvcgAAAABqaXBycAAAAEtpcGNvAAAAFGlzcGUAAAAAAAAAQAAAAEAAAAAQcGl4aQAAAAADCAgIAAAADGF2MUOBIAAAAAAAE2NvbHJuY2x4AAEAAgAGgAAAABdpcG1hAAAAAAAAAAEAAQQBAoMEAAAAKm1kYXQSAAoGOBV//YJAMhYWQAYYYYQAtIPtMjTyOUJqGBn2I9mA',
    'png': 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABAAQMAAACQp+OdAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAAAGUExURf8AAP///0EdNBEAAAABYktHRAH/Ai3eAAAAB3RJTUUH6gsLAgslcK79tgAAAA9JREFUKM9jYBgFo4B8AAACQAABjMWrdwAAACV0RVh0ZGF0ZTpjcmVhdGUAMjAyNi0xMS0xMVQwMjoxMTozNyswMDowMOAe5WYAAAAldEVYdGRhdGU6bW9kaWZ5ADIwMjYtMTEtMTFUMDI6MTE6MzcrMDA6MDCRQ13aAAAAKHRFWHRkYXRlOnRpbWVzdGFtcAAyMDI2LTExLTExVDAyOjExOjM3KzAwOjAwxlZ8BQAAAABJRU5ErkJggg==',
    'jpeg': '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCABAAEADAREAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFgEBAQEAAAAAAAAAAAAAAAAAAAcI/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AnJD2bwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH//Z',
    'gif': 'R0lGODlhQABAAPAAAAAA/wAAACH5BAAAAAAALAAAAABAAEAAAAJFhI+py+0Po5y02ouz3rz7D4biSJbmiabqyrbuC8fyTNf2jef6zvf+DwwKh8Si8YhMKpfMpvMJjUqn1Kr1is1qt9yuF1AAADs=',
    'bmp': 'Qk1mAAAAAAAAADYAAAAoAAAABAAAAAQAAAABABgAAAAAADAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/AAD/',
}


def ftyp(major, compat, rest=b'\0\0\0\x08free'):
    box = major + b'\0\0\0\0' + b''.join(compat)
    return (8 + len(box)).to_bytes(4, 'big') + b'ftyp' + box + rest


BLOCK = {
    'webp lossless (VP8L)': base64.b64decode(B64['webp-lossless']),
    'webp lossy (VP8 )': b'RIFF\x24\0\0\0WEBPVP8 \x18\0\0\0' + bytes(28),
    'webp extended (VP8X)': b'RIFF\x24\0\0\0WEBPVP8X\x0a\0\0\0' + bytes(28),
    'webp, 12 bytes only': b'RIFF\0\0\0\0WEBP',
    'avif (avifenc, major brand)': base64.b64decode(B64['avif']),
    'avif as compatible brand': ftyp(b'mif1', [b'mif1', b'miaf', b'avif']),
    'avis sequence': ftyp(b'avis', [b'avis', b'msf1']),
    'avif brand after 30 others': ftyp(b'mif1', [b'abcd'] * 30 + [b'avif']),
}
PASS = {
    'png': base64.b64decode(B64['png']),
    'jpeg': base64.b64decode(B64['jpeg']),
    'gif': base64.b64decode(B64['gif']),
    'bmp': base64.b64decode(B64['bmp']),
    'ico': b'\0\0\x01\0\x01\0\x10\x10\0\0\x01\0\x20\0' + bytes(64),
    'svg': b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>',
    'mp4 (isom)': ftyp(b'isom', [b'isom', b'iso2', b'avc1', b'mp41']) + bytes(500),
    'mov (qt)': ftyp(b'qt  ', [b'qt  ']) + bytes(100),
    'heic': ftyp(b'heic', [b'mif1', b'heic']),
    'wav (RIFF, not WEBP)': b'RIFF\x24\0\0\0WAVEfmt ' + bytes(40),
    'Editor.bin': b'DOCY;v5;1234;' + bytes(300),
    'empty': b'',
    '1 byte': b'R',
    '3 bytes': b'abc',
    'RIFF then end (5 bytes)': b'RIFFx',
    'RIFF....WE then end (10 bytes)': b'RIFF\0\0\0\0WE',
    '6 bytes, ftyp prefix': b'\0\0\0\x18ft',
    '11 bytes, RIFF': b'RIFF\0\0\0\0WEB',
    'ftyp box cut short': b'\0\0\0\x40ftypmif1\0\0\0\0',
    'json': b'{"a":1}',
    '3 MB': os.urandom(3 * 1024 * 1024),
}

DRIVER = r'''
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "image_guard.h"

// the CEF side of a response filter: input in chunks of `in_chunk`, output buffer of `out_size`,
// then calls with empty input until the filter is done
static int Run(const std::string& in, size_t in_chunk, size_t out_size, std::string& out)
{
	CefRefPtr<CImageGuardFilter> f = new CImageGuardFilter();
	if (!f->InitFilter())
		return 2;
	std::vector<char> buf(out_size);
	size_t pos = 0;
	while (pos < in.size())
	{
		size_t n = std::min(in_chunk, in.size() - pos);
		size_t read = 0, written = 0;
		cef_response_filter_status_t st = f->Filter((void*)(in.data() + pos), n, read, buf.data(), out_size, written);
		if (RESPONSE_FILTER_ERROR == st)
			return 1;
		out.append(buf.data(), written);
		if (0 == read && 0 == written)
			return 3; // no progress
		pos += read;
	}
	for (int i = 0; i < 100000; ++i)
	{
		size_t read = 0, written = 0;
		cef_response_filter_status_t st = f->Filter(nullptr, 0, read, buf.data(), out_size, written);
		if (RESPONSE_FILTER_ERROR == st)
			return 1;
		out.append(buf.data(), written);
		if (RESPONSE_FILTER_DONE == st || 0 == written)
			break;
	}
	return 0;
}

static std::string ReadFile(const char* p)
{
	std::string s;
	FILE* f = fopen(p, "rb");
	char b[65536];
	size_t n;
	while ((n = fread(b, 1, sizeof(b), f)) > 0)
		s.append(b, n);
	fclose(f);
	return s;
}

// ---- the real bodies from cefview.cpp, against a stub request ----
struct Str { std::string s; std::string ToString() const { return s; } };
struct StubRequest
{
	cef_resource_type_t type;
	std::string url, accept, set_accept;
	bool set = false;
	cef_resource_type_t GetResourceType() { return type; }
	Str GetURL() { return Str{url}; }
	Str GetHeaderByName(const std::string& name) { return Str{name == "Accept" ? accept : ""}; }
	void SetHeaderByName(const std::string& name, const std::string& value, bool overwrite) { if (name == "Accept" && overwrite) { set = true; set_accept = value; } }
};
namespace client { struct ClientHandler { template <class A, class B, class C, class D> static cef_return_value_t OnBeforeResourceLoad(A, B, C, D) { return RV_CONTINUE; } }; }

static CefRefPtr<CefResponseFilter> RealGetResourceResponseFilter(void* browser, void* frame, StubRequest* request, void* response)
{
@@FILTER_BODY@@
}
static cef_return_value_t RealOnBeforeResourceLoad(void* browser, void* frame, StubRequest* request, void* callback)
{
@@ACCEPT_BODY@@
}

int main(int argc, char** argv)
{
	if (argc > 1 && 0 == strcmp(argv[1], "types"))
	{
#define T(x) {#x, x}
		struct { const char* name; cef_resource_type_t type; } list[] = {
			T(RT_MAIN_FRAME), T(RT_SUB_FRAME), T(RT_STYLESHEET), T(RT_SCRIPT), T(RT_IMAGE), T(RT_FONT_RESOURCE),
			T(RT_SUB_RESOURCE), T(RT_OBJECT), T(RT_MEDIA), T(RT_WORKER), T(RT_SHARED_WORKER), T(RT_PREFETCH),
			T(RT_FAVICON), T(RT_XHR), T(RT_PING), T(RT_SERVICE_WORKER), T(RT_CSP_REPORT), T(RT_PLUGIN_RESOURCE),
			T(RT_NAVIGATION_PRELOAD_MAIN_FRAME), T(RT_NAVIGATION_PRELOAD_SUB_FRAME)};
		for (auto& e : list)
		{
			StubRequest r; r.type = e.type;
			printf("%s %d\n", e.name, RealGetResourceResponseFilter(nullptr, nullptr, &r, nullptr) ? 1 : 0);
		}
		return 0;
	}
	if (argc > 3 && 0 == strcmp(argv[1], "accept"))
	{
		StubRequest r; r.type = RT_IMAGE; r.url = argv[2]; r.accept = argv[3];
		RealOnBeforeResourceLoad(nullptr, nullptr, &r, nullptr);
		printf("%s|%s\n", r.set ? "set" : "unchanged", r.set_accept.c_str());
		return 0;
	}
	// filter <file>: for several chunk/output sizes print "error" or "ok <identical>"
	std::string in = ReadFile(argv[2]);
	const size_t chunks[] = {1, 3, 7, 12, 64, 4096, 65536};
	const size_t outs[] = {1, 5, 64, 65536};
	for (size_t c : chunks)
		for (size_t o : outs)
		{
			if (in.size() > 100000 && (c < 4096 || o < 64))
				continue;
			std::string out;
			int r = Run(in, c, o, out);
			printf("%zu/%zu:%s ", c, o, 1 == r ? "error" : (0 == r ? (out == in ? "same" : "DIFFERENT") : "stuck"));
		}
	printf("\n");
	return 0;
}
'''

failures = 0


def check(name, ok, detail=''):
    global failures
    if ok:
        print('ok   ' + name)
    else:
        failures += 1
        print('FAIL ' + name + (': ' + detail if detail else ''))


def main():
    guard = read(SRC + 'image_guard.h', missing_ok=True)
    cefview = read(SRC + 'cefview.cpp')
    if guard is None:
        print('FAIL image_guard.h does not exist: nothing keeps WebP/AVIF bytes from the decoders')
    filter_body = brace_body(cefview, 'CefRefPtr<CefResponseFilter> GetResourceResponseFilter(')
    accept_body = brace_body(cefview, 'cef_return_value_t OnBeforeResourceLoad(')
    if filter_body is None:
        print('FAIL cefview.cpp has no GetResourceResponseFilter: CEF\'s default installs no filter')
    if accept_body is None:
        print('FAIL cefview.cpp has no OnBeforeResourceLoad: Accept still asks for image/webp,image/avif')
    if guard is None or filter_body is None or accept_body is None:
        sys.exit(1)

    with tempfile.TemporaryDirectory() as work:
        open(os.path.join(work, 'image_guard.h'), 'w').write(guard)
        open(os.path.join(work, 'driver.cpp'), 'w').write(
            DRIVER.replace('@@FILTER_BODY@@', filter_body).replace('@@ACCEPT_BODY@@', accept_body))
        exe = os.path.join(work, 'driver')
        r = subprocess.run(['c++', '-std=c++17', '-O1', '-DOVERRIDE=override', '-w', '-I', work, '-I', CEF,
                            '-o', exe, os.path.join(work, 'driver.cpp')], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit('compile failed:\n' + r.stderr[-4000:])

        def run(*args):
            return subprocess.run([exe] + list(args), capture_output=True, text=True, check=True).stdout.strip()

        for group, expect in ((BLOCK, 'error'), (PASS, 'same')):
            for name, data in group.items():
                p = os.path.join(work, 'in.bin')
                open(p, 'wb').write(data)
                res = run('filter', p).split()
                bad = [x for x in res if not x.endswith(':' + expect)]
                check('%s: %s' % ('fails' if expect == 'error' else 'passes unchanged', name), not bad,
                      ' '.join(bad[:6]))

        types = dict(line.split() for line in run('types').splitlines())
        for name in ('RT_SUB_FRAME', 'RT_IMAGE', 'RT_SUB_RESOURCE', 'RT_OBJECT', 'RT_MEDIA', 'RT_PREFETCH',
                     'RT_FAVICON', 'RT_XHR', 'RT_NAVIGATION_PRELOAD_SUB_FRAME'):
            check('%s requests get the filter' % name, types.get(name) == '1', str(types.get(name)))
        for name in ('RT_MAIN_FRAME', 'RT_STYLESHEET', 'RT_SCRIPT', 'RT_FONT_RESOURCE', 'RT_WORKER'):
            check('%s requests are left alone' % name, types.get(name) == '0', str(types.get(name)))

        CHROME = 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        out = run('accept', 'https://ds.example.com/x.png', CHROME)
        check('https Accept drops exactly image/avif and image/webp',
              out == 'set|image/apng,image/svg+xml,image/*,*/*;q=0.8', out)
        out = run('accept', 'http://127.0.0.1/x', 'image/webp')
        check('an Accept of only image/webp becomes */*', out == 'set|*/*', out)
        out = run('accept', 'http://127.0.0.1/x', 'text/html,application/xhtml+xml, Image/WebP;q=0.9 ,*/*')
        check('Accept matching ignores case, spaces and parameters',
              out == 'set|text/html,application/xhtml+xml,*/*', out)
        out = run('accept', 'https://x.example/a.js', '*/*')
        check('Accept without webp/avif is not touched', out.startswith('unchanged'), out)
        out = run('accept', 'file:///tmp/a.png', CHROME)
        check('file:// requests are not touched (no header to negotiate)', out.startswith('unchanged'), out)

    print('%d check(s) FAILED' % failures if failures else 'all checks passed')
    sys.exit(1 if failures else 0)


main()

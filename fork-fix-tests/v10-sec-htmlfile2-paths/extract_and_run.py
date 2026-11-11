#!/usr/bin/env python3
"""
ONLYOFFICE 10.0 follow-up 9f33a5b519 (bug #71375), hand-ported to our HtmlFile2:
HTML/EPUB conversion must not pull local files from outside the document in, and
must still take the EPUB's own files.

The desktop converts with allowPrivateIP=false (desktop-sdk fileconverter.h), which
is what makes HtmlFile2 check paths at all. Before the port:
  - CHTMLReader::ReadStyleFromNetwork loaded <link href="x.css"> as <src>/<href>
    with no check, so href="../../outside/leak.css" (or a ../ chain out of the
    temp folder an EPUB is unpacked into) put any local .css into the styles;
  - CHTMLReader::Clear(), which InitOOXMLTags() runs at the start of every
    conversion, cleared m_wsCoreDirectory, so the EPUB package root that EpubFile
    sets never reached the writer, and CopyImage checked against the chapter's own
    folder: the usual ../Images/x.png of an EPUB chapter was dropped.

What runs here is the REAL code, lifted out of core by brace matching:
HTMLReader.cpp SetCoreDirectory / Clear / GetRootDirectory (when present) /
ReadStyleFromNetwork, and Tags/OOXMLTags.cpp GetStatusUsingExternalLocalFiles /
CanUseThisPath / CopyImage plus the "Assume image by local path" block of
CImageOOXMLTag::Open. NSSystemPath / NSFile are the real ones from core's kernel
library; the XML reader, CSS calculator, downloader and writer are stubs that only
hand the code its inputs and record what it loads. Real files are laid out in a
temp folder (an HTML page with an outside stylesheet; an unpacked EPUB with
OEBPS/Text, OEBPS/Images, OEBPS/Styles and a stylesheet outside the package).

Cases (allowPrivateIP=false, as the desktop runs x2t):
  1. HTML page linking ../../outside/leak.css     -> must not be loaded
  2. HTML page linking sub/inside.css              -> loaded (control)
  3. EPUB chapter linking ../Styles/ok.css         -> loaded (control)
  4. EPUB chapter linking a ../ chain to leak.css  -> must not be loaded
  5. EPUB chapter <img src="../Images/red.png">    -> copied
  6. EPUB chapter <img src="/abs/outside/secret.png"> and a ../ chain to it -> not copied

  RD_REPO=<core checkout>  (default ../../core)
  RD_CORE_LIB=<dir holding kernel.framework> (default <RD_REPO>/build/lib/mac_arm64,
                then ../../core/build/lib/mac_arm64)
  BASELINE=1               read the sources at BASE_REF; must FAIL (cases 1, 4, 5)
  BASE_REF                 default 49f4979807^ (the integrator re-pins it)

NOT claimed: a whole x2t conversion (that was run by hand with the payload x2t and
this HtmlFile2: see the commit message); the MD writer (never reads images here);
the old converter in htmlfile2.cpp (only built with USE_OLD_HTML_CONVERTER).
macOS only (links kernel.framework); Linux was syntax-checked separately.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '49f4979807^')
BASELINE = bool(os.environ.get('BASELINE'))


def find_lib():
    for d in (os.environ.get('RD_CORE_LIB'), os.path.join(REPO, 'build', 'lib', 'mac_arm64'),
              os.path.normpath(os.path.join(HERE, '..', '..', 'core', 'build', 'lib', 'mac_arm64'))):
        if d and os.path.isdir(os.path.join(d, 'kernel.framework')):
            return d
    sys.exit('kernel.framework not found; set RD_CORE_LIB')


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig').read()


def block(text, start, optional=False):
    a = text.find(start)
    if a < 0:
        if optional:
            return ''
        sys.exit('%r not found - the extractor needs updating' % start)
    a = text.rfind('\n', 0, a) + 1
    i = text.find('{', a)
    depth = 0
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


reader = read('HtmlFile2/HTMLReader.cpp')
tags = read('HtmlFile2/Tags/OOXMLTags.cpp')

reader_fns = '\n'.join([
    block(reader, 'void CHTMLReader::SetCoreDirectory('),
    block(reader, 'std::wstring CHTMLReader::GetRootDirectory(', optional=True),
    block(reader, 'void CHTMLReader::Clear()'),
    block(reader, 'void CHTMLReader::ReadStyleFromNetwork('),
])
tag_fns = '\n'.join([
    block(tags, 'bool GetStatusUsingExternalLocalFiles()\n{'),
    block(tags, 'bool CanUseThisPath(const std::wstring& wsPath, const std::wstring& wsSrcPath, const std::wstring& wsCorePath, bool bIsAllowExternalLocalFiles)\n{'),
    block(tags, tags[tags.find('bool CopyImage(std::wstring wsImageSrc', tags.find('bool CanUseThisPath(const std::wstring& wsPath, const std::wstring& wsSrcPath, const std::wstring& wsCorePath, bool bIsAllowExternalLocalFiles)\n{')):].split('\n')[0] + '\n{'),
])
m = re.search(r'\t// Assume image by local path\n(\tif \(!bRes\)\n\t\{.*?\n\t\})\n', tags, re.S)
if not m:
    sys.exit('local image block of CImageOOXMLTag::Open not found')
image_block = m.group(1)

SRC = r'''
#include <cstdio>
#include <string>
#include <vector>
#include <map>
#include "DesktopEditor/common/File.h"
#include "DesktopEditor/common/Path.h"

namespace NSProcessEnv {
	namespace Converter { static const char* gc_allowPrivateIP = "allowPrivateIP"; }
	bool IsPresent(const char*) { return true; }        // the desktop always passes it
	bool GetBoolValue(const char*) { return false; }    // allowPrivateIP=false
}
namespace NSNetwork { namespace NSFileTransport {
	struct CFileDownloader {
		CFileDownloader(const std::wstring&, bool) {}
		void SetFilePath(const std::wstring&) {}
		bool DownloadSync() { return false; }
	};
}}

namespace HTML
{
struct CLightReader {
	std::wstring name, text;
	std::wstring GetName() { return name; }
	std::wstring GetText() { return text; }
};
struct CCss {
	std::vector<std::wstring> loaded;
	void AddStylesFromFile(const std::wstring& s) { if (NSFile::CFileBinary::Exists(s)) loaded.push_back(s); }
};
struct IWriterStub { virtual ~IWriterStub() {} };

class CHTMLReader {
public:
	CLightReader m_oLightReader;
	CCss m_oCSSCalculator;
	std::wstring m_wsTempDirectory, m_wsSrcDirectory, m_wsDstDirectory, m_wsBaseDirectory, m_wsCoreDirectory;
	IWriterStub* m_pWriter = nullptr;
	std::map<int, int> m_mTags;
	void* m_pTableElement = nullptr;
	void SetCoreDirectory(const std::wstring& wsPath);
	std::wstring GetRootDirectory() const;
	void Clear();
	void ReadStyleFromNetwork();
};

TAG_FNS

READER_FNS

// what CImageOOXMLTag::Open sees of the writer
struct CWriter {
	std::wstring src, base, core;
	std::wstring GetSrcPath() const { return src; }
	std::wstring GetBasePath() const { return base; }
	std::wstring GetCorePath() const { return core; }
};

bool LocalImage(CWriter* m_pWriter, std::wstring wsSrc, const std::wstring& wsImagePath)
{
	bool bRes = false;
	const std::wstring wsExtention = L"png";
	const bool bIsAllowExternalLocalFiles = GetStatusUsingExternalLocalFiles();
	if (!CanUseThisPath(wsSrc, m_pWriter->GetSrcPath(), m_pWriter->GetCorePath(), bIsAllowExternalLocalFiles))
		return false;    // Open() writes the alt text instead
IMAGE_BLOCK
	return bRes;
}
}

static std::wstring W(const char* s) { return NSFile::CUtf8Converter::GetUnicodeStringFromUTF8((BYTE*)s, strlen(s)); }

int main(int argc, char** argv)
{
	std::wstring root = W(argv[1]);
	int fails = 0;
	auto check = [&](bool ok, const char* what) { printf("%s %s\n", ok ? "ok  " : "FAIL", what); fails += !ok; };

	// --- plain HTML page: the reader as ConvertHTML2OOXML leaves it (no core directory)
	auto css = [&](const std::wstring& src, const std::wstring& core, const std::wstring& href) {
		HTML::CHTMLReader r;
		r.SetCoreDirectory(core);
		r.Clear();                    // InitOOXMLTags() -> Clear() before reading
		r.m_wsSrcDirectory = src;
		r.m_oLightReader.name = L"href";
		r.m_oLightReader.text = href;
		r.ReadStyleFromNetwork();
		return r.m_oCSSCalculator.loaded.size();
	};
	std::wstring page = root + L"/site/pages";
	check(0 == css(page, L"", L"../../outside/leak.css"), "HTML: <link href=\"../../outside/leak.css\"> is not loaded");
	check(1 == css(page, L"", L"sub/inside.css"), "HTML: <link href=\"sub/inside.css\"> is loaded (control)");

	// --- EPUB: EpubFile sets the package root (OEBPS) as core directory
	std::wstring oebps = root + L"/epub/OEBPS", text = oebps + L"/Text";
	std::wstring up; for (int i = 0; i < 30; ++i) up += L"../";
	std::wstring rootNoSlash = root.substr(1);
	check(1 == css(text, oebps, L"../Styles/ok.css"), "EPUB: <link href=\"../Styles/ok.css\"> is loaded (control)");
	check(0 == css(text, oebps, up + rootNoSlash + L"/outside/leak.css"), "EPUB: <link> with a ../ chain to a .css outside the package is not loaded");

	// images: the writer gets the reader's core directory after Clear(), as InitOOXMLTags hands it on
	HTML::CHTMLReader r;
	r.SetCoreDirectory(oebps);
	r.Clear();
	HTML::CWriter w{text, L"", r.m_wsCoreDirectory};
	std::wstring dst = root + L"/media/i";
	NSFile::CFileBinary::Remove(dst + L".png");
	bool b = HTML::LocalImage(&w, L"../Images/red.png", dst);
	check(b && NSFile::CFileBinary::Exists(dst + L".png"), "EPUB: <img src=\"../Images/red.png\"> is copied into the document");
	NSFile::CFileBinary::Remove(dst + L".png");
	bool b1 = HTML::LocalImage(&w, root + L"/outside/secret.png", dst);
	bool b2 = HTML::LocalImage(&w, up + rootNoSlash + L"/outside/secret.png", dst);
	check(!b1 && !b2 && !NSFile::CFileBinary::Exists(dst + L".png"), "EPUB: <img> at an absolute path / ../ chain outside the package is not copied");
	return fails ? 1 : 0;
}
'''


def main():
    lib = find_lib()
    print(('BASELINE ' + BASE_REF) if BASELINE else ('repo ' + REPO))
    src = SRC.replace('TAG_FNS', tag_fns).replace('READER_FNS', reader_fns).replace('IMAGE_BLOCK', image_block)
    # the baseline has no GetRootDirectory; give the stub class a body so it links
    if 'CHTMLReader::GetRootDirectory' not in reader_fns:
        src = src.replace('READER_FNS', '')
        src = src.replace('\tstd::wstring GetRootDirectory() const;\n', '')
    with tempfile.TemporaryDirectory() as work:
        root = os.path.join(work, 'files')
        for d in ('site/pages/sub', 'outside', 'epub/OEBPS/Text', 'epub/OEBPS/Images', 'epub/OEBPS/Styles', 'media'):
            os.makedirs(os.path.join(root, d))
        for rel, data in (('outside/leak.css', b'p { font-size: 47pt; }'), ('site/pages/sub/inside.css', b'p {}'),
                          ('epub/OEBPS/Styles/ok.css', b'h1 {}'), ('epub/OEBPS/Text/ch1.xhtml', b'<html/>'),
                          ('epub/OEBPS/Images/red.png', b'\x89PNG red'), ('outside/secret.png', b'\x89PNG secret')):
            open(os.path.join(root, rel), 'wb').write(data)
        p = os.path.join(work, 't.cpp')
        open(p, 'w').write(src)
        exe = os.path.join(work, 't')
        r = subprocess.run(['c++', '-std=c++11', '-w', '-g', '-fsanitize=address', '-DLINUX', '-D_LINUX', '-DMAC', '-D_MAC',
                            '-I' + REPO, p, '-o', exe, '-F' + lib, '-framework', 'kernel', '-Wl,-rpath,' + lib],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit('compile failed:\n' + r.stderr[-4000:])
        r = subprocess.run([exe, os.path.realpath(root)], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.stderr.strip():
            print(r.stderr.strip()[-2000:])
        print('PASSED' if r.returncode == 0 else 'FAILED')
        sys.exit(r.returncode)


main()

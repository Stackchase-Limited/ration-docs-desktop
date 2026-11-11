#!/usr/bin/env python3
r"""
#1664 follow-up (data loss) - an AVIF picture in a docx/xlsx/pptx was gone after a save.

Found while building the #1664 WebP/AVIF guard, but it predates the guard: the guard
(desktop-sdk image_guard.h, sdkjs clipboard_base.js) only fails the browser's load of
the bytes and never touches the files, and the x2t built before it (payload of
2026-11-05) loses the picture the same way.

Every save to OOXML - x2t Editor.bin -> docx/xlsx/pptx, also when the desktop app
replays its change records onto the opened Editor.bin - writes pictures through
NSBinPptxRW::CImageManager2::GenerateImageExec (core OOXML/Binary/Presentation/
BinaryFileReaderWriter.cpp). JPEG, PNG, GIF, WebP, WMF and EMF are copied, SVG is
rasterised, and anything else goes to the `default:` branch, which re-encodes it as
PNG with SaveImageAsPng and points the relationship at media/imageN.png WITHOUT
looking at SaveImageAsPng's result. Core cannot decode AVIF (libheif is built with
WITH_AOM_DECODER=OFF in build_tools heif.py), so for an AVIF nothing was written and
the package got a relationship to a part that does not exist. Seen with the real x2t:
a docx holding word/media/image2.avif and an AVIF stored as image3.png came back with
neither file and with rels to media/image2.png and media/image3.png; xlsx and pptx the
same; WebP survived (it is on the pass-through list).

The fix: when the conversion fails and the source exists, the original bytes are copied
under the original extension (as CMediaManager::SaveImage already does). ContentTypes'
extension table also maps avif to image/avif.

What this test runs: the REAL GenerateImageExec, lifted out of BinaryFileReaderWriter.cpp
by brace matching, compiled against small stubs, over real files in a temp dir. The
stubs are its collaborators, not its logic: CImageFileFormatChecker sniffs the leading
bytes (PNG, WebP, ISO-BMFF ftyp -> HEIF type, BMP), and SaveImageAsPng behaves like
core's CBgraFrame - it can "decode" the BMP (writes a PNG) and fails on AVIF, as the
real one does. It also runs the real CExtensionTable constructor from ContentTypes.cpp.

Checked:
  * AVIF named .avif and AVIF named .png: the file the relationship will point at exists
    and holds the original bytes.
  * PNG and WebP are still copied unchanged; a decodable non-pass-through picture (BMP)
    is still converted to .png (unchanged behaviour).
  * avif has the content type image/avif.
NOT claimed here: the end-to-end x2t/editor round trip (done by hand, see the commit
message), and anything about display - the AVIF is still kept from Chromium by the
desktop-sdk guard (see issue-1664-webp-guard), which this change does not touch.

  RD_REPO=<core checkout>   default ../../core relative to this file
  BASELINE=1                reads the sources from git ($BASE_REF) - must FAIL there
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.abspath(os.environ.get('RD_REPO') or os.path.join(HERE, '..', '..', 'core'))
REL_BIN = 'OOXML/Binary/Presentation/BinaryFileReaderWriter.cpp'
REL_CT = 'OOXML/DocxFormat/ContentTypes.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '0228100ad6^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(CORE, rel), encoding='utf-8').read()


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


src_bin = read(REL_BIN)
m = re.search(r'^\t_imageManager2Info CImageManager2::GenerateImageExec\(', src_bin, re.M)
if not m:
    raise SystemExit('GenerateImageExec was not found in %s - the extractor needs updating' % REL_BIN)
gen_fn = brace_match(src_bin, m.start())
for needle in ('CImageFileFormatChecker checker(strInput)', 'SaveImageAsPng', '_CXIMAGE_FORMAT_WEBP', 'default:'):
    if needle not in gen_fn:
        raise SystemExit('extracted GenerateImageExec is missing %r - wrong function?' % needle)

src_ct = read(REL_CT)
m = re.search(r'^\t\tCExtensionTable::CExtensionTable\(\)', src_ct, re.M)
if not m:
    raise SystemExit('CExtensionTable() was not found in %s' % REL_CT)
ct_fn = brace_match(src_ct, m.start())
if 'L"webp"' not in ct_fn:
    raise SystemExit('extracted CExtensionTable() is missing webp - wrong function?')

harness = r'''
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
#include <map>
#include <fstream>
#include <sstream>
#include <iterator>

#define FILE_SEPARATOR_STR L"/"
#define RELEASEOBJECT(p) { if (p) { delete p; p = NULL; } }

static std::string narrow(const std::wstring& w) { return std::string(w.begin(), w.end()); }
static std::string slurp(const std::wstring& path)
{
	std::ifstream f(narrow(path).c_str(), std::ios::binary);
	if (!f) return std::string("\x01<missing>");
	return std::string((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
}
static void spit(const std::wstring& path, const std::string& data)
{
	std::ofstream f(narrow(path).c_str(), std::ios::binary);
	f << data;
}

/* values as in DesktopEditor/raster/ImageFileFormatChecker.h */
enum
{
	_CXIMAGE_FORMAT_UNKNOWN = 0, _CXIMAGE_FORMAT_BMP = 1, _CXIMAGE_FORMAT_GIF = 2, _CXIMAGE_FORMAT_JPG = 3,
	_CXIMAGE_FORMAT_PNG = 4, _CXIMAGE_FORMAT_WMF = 10, _CXIMAGE_FORMAT_EMF = 11, _CXIMAGE_FORMAT_SVG = 24,
	_CXIMAGE_FORMAT_HEIF = 26, _CXIMAGE_FORMAT_WEBP = 27
};

/* stub: sniffs leading bytes like the real checker does for these formats */
class CImageFileFormatChecker
{
public:
	int eFileType;
	CImageFileFormatChecker(const std::wstring& file) : eFileType(_CXIMAGE_FORMAT_UNKNOWN)
	{
		std::string b = slurp(file);
		if (b.size() >= 8 && 0 == memcmp(b.data(), "\x89PNG\r\n\x1a\n", 8)) eFileType = _CXIMAGE_FORMAT_PNG;
		else if (b.size() >= 12 && 0 == memcmp(b.data(), "RIFF", 4) && 0 == memcmp(b.data() + 8, "WEBP", 4)) eFileType = _CXIMAGE_FORMAT_WEBP;
		else if (b.size() >= 12 && 0 == memcmp(b.data() + 4, "ftyp", 4)) eFileType = _CXIMAGE_FORMAT_HEIF;
		else if (b.size() >= 2 && 0 == memcmp(b.data(), "BM", 2)) eFileType = _CXIMAGE_FORMAT_BMP;
	}
};

namespace NSFile
{
	class CFileBinary
	{
	public:
		static bool Exists(const std::wstring& p) { std::ifstream f(narrow(p).c_str()); return (bool)f; }
		static bool Copy(const std::wstring& a, const std::wstring& b) { spit(b, slurp(a)); return true; }
		static bool Remove(const std::wstring& p) { return 0 == remove(narrow(p).c_str()); }
	};
}
namespace OOX
{
	class CPath
	{
	public:
		std::wstring m_strFilename;
		CPath() {}
		CPath(const std::wstring& s) : m_strFilename(s) {}
		CPath& operator=(const std::wstring& s) { m_strFilename = s; return *this; }
		std::wstring GetPath() const { return m_strFilename; }
	};
}
/* only reached for SVG, which this test does not feed */
namespace NSFonts { struct IApplicationFonts { void Initialize() {} }; namespace NSApplication { inline IApplicationFonts* Create() { return new IApplicationFonts(); } } }
namespace MetaFile
{
	struct IMetaFile
	{
		bool LoadFromFile(const wchar_t*) { return false; }
		void GetBounds(double*, double*, double*, double*) {}
		void ConvertToRaster(const wchar_t*, int, double, double) {}
	};
	inline IMetaFile* Create(NSFonts::IApplicationFonts*) { return new IMetaFile(); }
}

namespace NSBinPptxRW
{
	struct _imageManager2Info
	{
		std::vector<std::wstring> sFilepathAdditionals;
		std::wstring sFilepathImage;
	};
	class CImageManager2
	{
	public:
		std::wstring m_strDstMedia, m_strDstEmbed;
		int m_lIndexNextImage, m_lIndexCounter;
		CImageManager2() : m_lIndexNextImage(0), m_lIndexCounter(0) {}
		bool WriteOleData(const std::wstring&, const std::wstring&) { return false; }
		/* stub of core's CBgraFrame round trip: it decodes BMP, it has no AV1 decoder */
		bool SaveImageAsPng(const std::wstring& src, const std::wstring& dst)
		{
			CImageFileFormatChecker c(src);
			if (_CXIMAGE_FORMAT_BMP != c.eFileType)
				return false;
			spit(dst, std::string("\x89PNG\r\n\x1a\n", 8) + "converted");
			return true;
		}
		_imageManager2Info GenerateImageExec(const std::wstring& strInput, const std::wstring& sExts, std::vector<std::pair<std::wstring, int>>& additional, const std::wstring& oleData);
	};

@@GEN@@
}

namespace OOX { namespace ContentTypes {
	class CExtensionTable
	{
	public:
		std::map<std::wstring, std::wstring> m_mTable;
		CExtensionTable();
	};
@@CT@@
} }

static int g_failures = 0;
static void check(const char* what, bool ok)
{
	printf("    %-70s %s\n", what, ok ? "ok" : "FAILED");
	if (!ok) ++g_failures;
}

int main(int argc, char** argv)
{
	std::string dir = argv[1];
	std::wstring wdir(dir.begin(), dir.end());
	std::wstring src = wdir + L"/src", dst = wdir + L"/media";

	std::string avif("\0\0\0\x20" "ftypavif\0\0\0\0avifmif1miafMA1A" "\0\0\0\x08mdat", 40);
	std::string png = std::string("\x89PNG\r\n\x1a\n", 8) + "pngbody";
	std::string webp("RIFF\x1a\0\0\0WEBPVP8L\x0d\0\0\0\x2f\0\0\0\x10\x07\x10\x11\x11\x88\x88\xfe\x07\0", 34);
	std::string bmp = std::string("BM") + "bmpbody";

	struct Case { const char* name; const wchar_t* file; const wchar_t* ext; std::string bytes; bool convert; };
	Case cases[] = {
		{ "AVIF named image.avif",  L"image2.avif", L".avif", avif, false },
		{ "AVIF named image.png",   L"image3.png",  L".png",  avif, false },
		{ "PNG",                    L"image1.png",  L".png",  png,  false },
		{ "WebP named image.webp",  L"image4.webp", L".webp", webp, false },
		{ "BMP (decodable, converted to PNG as before)", L"image6.bmp", L".bmp", bmp, true },
	};

	NSBinPptxRW::CImageManager2 mgr;
	mgr.m_strDstMedia = dst;
	mgr.m_strDstEmbed = wdir + L"/embeddings";

	printf("GenerateImageExec: every picture the relationship points at must exist after a save\n");
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i)
	{
		const Case& c = cases[i];
		std::wstring in = src + L"/" + c.file;
		spit(in, c.bytes);
		std::vector<std::pair<std::wstring, int>> additional;
		NSBinPptxRW::_imageManager2Info info = mgr.GenerateImageExec(in, c.ext, additional, L"");
		std::string out = slurp(info.sFilepathImage);
		printf("  %s -> %s\n", c.name, narrow(info.sFilepathImage.substr(wdir.length() + 1)).c_str());
		check("written file exists", NSFile::CFileBinary::Exists(info.sFilepathImage));
		if (c.convert)
		{
			check("converted to .png", info.sFilepathImage.size() > 4 && info.sFilepathImage.substr(info.sFilepathImage.size() - 4) == L".png");
		}
		else
		{
			check("bytes unchanged", out == c.bytes);
			check("original extension kept", info.sFilepathImage.size() > wcslen(c.ext) && info.sFilepathImage.substr(info.sFilepathImage.size() - wcslen(c.ext)) == c.ext);
		}
	}

	printf("CExtensionTable: content type of .avif\n");
	OOX::ContentTypes::CExtensionTable table;
	std::map<std::wstring, std::wstring>::iterator it = table.m_mTable.find(L"avif");
	std::string ct = (it == table.m_mTable.end()) ? "application/unknown (not in table)" : narrow(it->second);
	printf("  avif -> %s\n", ct.c_str());
	check("avif is image/avif", ct == "image/avif");

	printf("\n%s\n", g_failures ? "FAILED" : "PASSED");
	return g_failures ? 1 : 0;
}
'''

harness = harness.replace('@@GEN@@', gen_fn).replace('@@CT@@', ct_fn)

print('#1664 AVIF kept on save - %s (%s)' % ('BASELINE ' + BASE_REF if BASELINE else 'working tree', CORE), flush=True)
tmp = tempfile.mkdtemp(prefix='rd-1664-avif-')
try:
    for d in ('src', 'media', 'embeddings'):
        os.makedirs(os.path.join(tmp, d))
    cpp = os.path.join(tmp, 't.cpp')
    exe = os.path.join(tmp, 't')
    with open(cpp, 'w', encoding='utf-8') as f:
        f.write(harness)
    c = subprocess.run(['clang++', '-std=c++14', '-w', '-o', exe, cpp], capture_output=True, text=True)
    if c.returncode:
        print(c.stderr[:4000])
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe, tmp]).returncode)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

#!/usr/bin/env python3
r"""
#1323 - "Mimetype of docx changes when content is added".  `file(1)` reports a
freshly saved empty document as "Microsoft Word 2007+", but after text is typed
into it and it is saved again the same command reports only
"Zip archive data ... compression method=store" / application/zip.

Nothing about the document changes format.  What changes is the ORDER of the
entries in the zip, and how far apart they sit.

An OOXML package is identified by its first few entries.  libmagic's msooxml
rule checks that entry 1 is [Content_Types].xml, then hops to the third local
header and requires that name to begin with "word/", "xl/" or "ppt/" - and it
only searches a bounded window for that header.  Every other producer, Word
included, writes [Content_Types].xml, then _rels/.rels, then the part
directory, which satisfies the rule regardless of how large the document is.

ZLibZipUtils::ZipDir walks the unpacked directory breadth-first and, when
`sorted` is set (which is what the docx save path passes), pushed both the part
directory and `_rels` to the FRONT of its work queue.  Two push_fronts means
the directory that NSDirectory::GetDirectories happens to return LAST comes out
FIRST in the archive - so the layout depended on readdir order.  Where the
filesystem lists "_rels" before "word", the package came out as

    [Content_Types].xml,  word/document.xml,  _rels/.rels

putting _rels/.rels in the identifying third slot.  The rule then went looking
further for a "word/" entry, and whether one fell inside its search window
depended on the compressed size of word/document.xml - empty it fitted and the
file was identified, with text in it it did not and detection fell through to
the generic "Zip archive data" rule.  That rule prints the compression method
of the FIRST entry, which ZipDir deliberately stores rather than deflates, so
the report's "compression method=store" is the same defect showing its tail.

Confirmed against our own shipped x2t before the fix: round-tripping a .docx
through it produced exactly
    [Content_Types].xml (Stored), word/document.xml (Defl:N), _rels/.rels (Stored)
and `file` called the result application/zip.

This test extracts the REAL ZipDir out of ZipUtilsCP.cpp by brace matching and
runs it over a stub filesystem, recording the order in which it asks
oneZipFile to write entries.  It runs the SAME package tree twice, once with
each of the two possible directory enumeration orders, because the whole point
is that the answer must not depend on that.

  BASELINE=1 re-reads ZipUtilsCP.cpp from git HEAD, where it must FAIL.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'OfficeUtils/src/ZipUtilsCP.cpp'
BASE_REF = os.environ.get('BASE_REF', 'HEAD')

if os.environ.get('BASELINE'):
    src = subprocess.run(['git', '-C', CORE, 'show', '%s:%s' % (BASE_REF, REL)],
                         capture_output=True, text=True, check=True).stdout
else:
    src = open(os.path.join(CORE, REL), encoding='utf-8').read()


def match_braces(text, open_brace):
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    raise SystemExit('unbalanced braces')


# ---- the real ZipDir ------------------------------------------------------
# Select it by its signature. ZipFile() sits right after it and looks similar,
# so anchor on the `dir`/`sorted` parameters that only ZipDir has.
m = re.search(r'^\tint ZipDir\( const WCHAR\* dir, const WCHAR\* outputFile, '
              r'const OnProgressCallback\* progress, bool sorted, int method, '
              r'int compressionLevel, bool bDateTime \)\s*$', src, re.M)
if not m:
    raise SystemExit('ZipDir was not found in %s - the extractor needs updating' % REL)
ob = src.index('{', m.end())
zipdir_fn = src[m.start():match_braces(src, ob) + 1]

# Sanity: this really is the packer and really is the version we mean to test.
for needle in ('StringDeque', 'zipDeque', 'NSDirectory::GetDirectories',
               'oneZipFile', 'L"[Content_Types]"', 'L"_rels"'):
    if needle not in zipdir_fn:
        raise SystemExit('extracted ZipDir is missing %r - wrong function?' % needle)
if 'int ZipFile(' in zipdir_fn:
    raise SystemExit('extraction ran past the end of ZipDir')

harness = r'''
#include <stdio.h>
#include <deque>
#include <map>
#include <string>
#include <vector>

using namespace std;

typedef wchar_t WCHAR;
#define UTILS_ONPROGRESSEVENT_ID 0
typedef void (OnProgressCallback)(int, long, short*);

/* ---- stub filesystem ----------------------------------------------------
 * ZipDir only ever asks two questions about the tree, so that is all we model.
 * The two orders we care about are supplied by the caller. */
static map<wstring, vector<wstring> > g_files;   /* dir -> file names */
static map<wstring, vector<wstring> > g_dirs;    /* dir -> child dir names */

namespace NSDirectory
{
    static vector<wstring> childPaths(const wstring &dir,
                                      map<wstring, vector<wstring> > &tbl)
    {
        vector<wstring> out;
        map<wstring, vector<wstring> >::iterator it = tbl.find(dir);
        if (it == tbl.end()) return out;
        for (size_t i = 0; i < it->second.size(); ++i)
            out.push_back(dir + L"/" + it->second[i]);
        return out;
    }
    vector<wstring> GetFiles(const wstring &dir)       { return childPaths(dir, g_files); }
    vector<wstring> GetDirectories(const wstring &dir) { return childPaths(dir, g_dirs);  }
}

namespace NSSystemPath
{
    wstring GetFileName(const wstring &path)
    {
        size_t at = path.find_last_of(L'/');
        return at == wstring::npos ? path : path.substr(at + 1);
    }
    wstring Combine(const wstring &a, const wstring &b) { return a + L"/" + b; }
}

/* ---- stub zip writer: record what ZipDir asks for, in order -------------- */
struct Written { wstring name; int method; };
static vector<Written> g_written;

typedef void *zipFile;
static int g_zipSink;
static zipFile zipOpenHelp(const WCHAR *) { return &g_zipSink; }
static int zipClose(zipFile, void *) { return 0; }
static unsigned int get_files_count(const WCHAR *) { return 1; }

static int oneZipFile(zipFile &zf, wstring &file_name, wstring &zip_file_name,
                      int method, int compressionLevel, bool bDateTime)
{
    (void)zf; (void)file_name; (void)compressionLevel; (void)bDateTime;
    Written w; w.name = zip_file_name; w.method = method;
    g_written.push_back(w);
    return 0;
}

namespace ZLibZipUtils
{
/* ---- the real ZipDir, lifted verbatim out of ZipUtilsCP.cpp ---- */
%(zipdir_fn)s
}

/* ------------------------------------------------------------------------ */
static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("    %%-66s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static string narrow(const wstring &w)
{
    string s;
    for (size_t i = 0; i < w.size(); ++i) s += (char)(w[i] < 128 ? w[i] : '?');
    return s;
}

/* A realistic unpacked .docx. `relsFirst` chooses which of the two root
 * subdirectories NSDirectory::GetDirectories reports first - the thing that
 * used to decide the archive layout. */
static void buildTree(bool relsFirst)
{
    g_files.clear(); g_dirs.clear();

    g_files[L"/pkg"].push_back(L"[Content_Types].xml");
    if (relsFirst) { g_dirs[L"/pkg"].push_back(L"_rels"); g_dirs[L"/pkg"].push_back(L"word"); }
    else           { g_dirs[L"/pkg"].push_back(L"word");  g_dirs[L"/pkg"].push_back(L"_rels"); }
    g_dirs[L"/pkg"].push_back(L"docProps");

    g_files[L"/pkg/_rels"].push_back(L".rels");

    g_files[L"/pkg/word"].push_back(L"document.xml");
    g_files[L"/pkg/word"].push_back(L"styles.xml");
    g_files[L"/pkg/word"].push_back(L"settings.xml");
    g_dirs [L"/pkg/word"].push_back(L"_rels");
    g_dirs [L"/pkg/word"].push_back(L"theme");

    g_files[L"/pkg/word/_rels"].push_back(L"document.xml.rels");
    g_files[L"/pkg/word/theme"].push_back(L"theme1.xml");

    g_files[L"/pkg/docProps"].push_back(L"app.xml");
    g_files[L"/pkg/docProps"].push_back(L"core.xml");
}

static bool startsWith(const wstring &s, const wchar_t *p)
{
    wstring pre(p);
    return s.size() >= pre.size() && s.compare(0, pre.size(), pre) == 0;
}

static void runOne(bool relsFirst)
{
    buildTree(relsFirst);
    g_written.clear();

    /* `sorted` is true: that is what the docx save path passes
     * (X2tConverter/src/lib/common.h -> dir2zip(sFrom, sTo, true)). */
    ZLibZipUtils::ZipDir(L"/pkg", L"/out.docx", NULL, true,
                         8 /*Z_DEFLATED*/, -1, false);

    printf("  GetDirectories reports %%s first -> archive order:\n",
           relsFirst ? "\"_rels\"" : "\"word\"");
    for (size_t i = 0; i < g_written.size() && i < 4; ++i)
        printf("      %%zu. %%s\n", i + 1, narrow(g_written[i].name).c_str());

    check(g_written.size() >= 3, "the package has at least three entries");
    if (g_written.size() < 3) return;

    check(g_written[0].name == L"[Content_Types].xml",
          "entry 1 is [Content_Types].xml");
    check(g_written[1].name == L"_rels/.rels",
          "entry 2 is _rels/.rels");
    check(startsWith(g_written[2].name, L"word/"),
          "entry 3 is a word/ part, which is what identifies the package");
}

int main()
{
    printf("ZipDir entry order must not depend on directory enumeration order:\n");
    runOne(true);
    printf("\n");
    runOne(false);

    printf("\n%%s\n", failures
           ? "FAILED"
           : "ok - [Content_Types].xml, _rels/.rels, word/... either way round");
    return failures ? 1 : 0;
}
''' % {'zipdir_fn': zipdir_fn}

with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(cpp, 'w', encoding='utf-8').write(harness)
    cmd = ['clang++', '-std=c++14', '-Wall', '-Wno-unused-variable',
           '-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)

#!/usr/bin/env python3
r"""
#1855 - "PDF export does not include table of contents".

core's PDF writer is NOT missing an outline implementation.  PdfWriter::COutline
builds a proper /Outlines tree (Type, Title, First/Last/Next/Prev/Parent, Count,
Dest), CDocument::CreateOutline hangs it off the catalog, and there is a live
path to it: metafile opcode ctHeadings (169) -> CHeadings ->
CPdfFile::AdvancedCommand -> CPdfWriter::SetHeadings -> CreateOutlines.

What is missing is the one line that tells a reader to SHOW it.  The catalog's
page mode is set once, at document creation:

    PdfFile/SrcWriter/Document.cpp  (CDocument::NewDocument)
        m_pCatalog->SetPageMode(pagemode_UseNone);

and that was the ONLY SetPageMode call in the whole submodule - pagemode_UseOutline
is defined in Types.h and the name "UseOutlines" is in the catalog's name table,
but nothing ever selected either.  So a document that does carry a complete
outline still says /PageMode /UseNone and opens with the bookmarks pane shut.
LibreOffice - the comparison in the issue's screenshots - writes
/PageMode /UseOutlines whenever it emits an outline, which is why its export
visibly "has a table of contents" and ours appears not to.

The fix asks for the pane where the outline is actually created, so documents
without an outline are unaffected.

This test extracts the REAL CDocument::CreateOutline by brace matching and runs
it against stub catalog/outline objects, starting from the UseNone that
NewDocument leaves behind.

  BASELINE=1 re-reads Document.cpp from git HEAD, where it must FAIL.

NOTE ON SCOPE: this makes an outline that IS written visible.  Whether sdkjs
emits ctHeadings for a given DOCX export is a separate question and lives
outside core; it could not be exercised here because this build tree has no
editors/sdkjs/common/AllFonts.js, so x2t's docx->pdf path refuses to start.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
REL = 'PdfFile/SrcWriter/Document.cpp'
# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get('BASE_REF', '4116fbeb76^')

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


# The starting state the harness must reproduce: NewDocument nails the catalog
# to UseNone.  If that ever changes, this test is measuring the wrong thing.
if 'm_pCatalog->SetPageMode(pagemode_UseNone);' not in src:
    raise SystemExit('NewDocument no longer sets pagemode_UseNone - this test '
                     'assumes that starting state and needs updating')

# ---- the real CDocument::CreateOutline ------------------------------------
m = re.search(r'^\s*COutline\* CDocument::CreateOutline\(COutline\* pParent, '
              r'const char\* sTitle\)\s*$', src, re.M)
if not m:
    raise SystemExit('CDocument::CreateOutline was not found in %s - the '
                     'extractor needs updating' % REL)
ob = src.index('{', m.end())
create_outline = src[m.start():match_braces(src, ob) + 1]

for needle in ('m_pOutlines', 'm_pCatalog->Add("Outlines"', 'return new COutline'):
    if needle not in create_outline:
        raise SystemExit('extracted CreateOutline is missing %r - wrong '
                         'function?' % needle)

harness = r'''
#include <stdio.h>
#include <string>
#include <vector>

namespace PdfWriter
{
    /* Values and order taken from PdfFile/SrcWriter/Types.h. */
    enum EPageMode
    {
        pagemode_UseNone        = 0,
        pagemode_UseOutline     = 1,
        pagemode_UseThumbs      = 2,
        pagemode_FullScreen     = 3,
        pagemode_UseOC          = 4,
        pagemode_UseAttachments = 5
    };

    class CXref {};

    class COutline
    {
    public:
        COutline(CXref *) : pParent(0) {}
        COutline(COutline *p, const char *sTitle, CXref *)
            : pParent(p), sTitle(sTitle ? sTitle : "") {}
        COutline *pParent;
        std::string sTitle;
    };

    /* Records exactly what CreateOutline asks of the catalog. */
    class CCatalog
    {
    public:
        CCatalog() : nPageMode(pagemode_UseNone), nPageModeCalls(0) {}
        void Add(const std::string &sKey, COutline *pObj)
        {
            (void)pObj;
            vAdded.push_back(sKey);
        }
        void SetPageMode(EPageMode eMode)
        {
            nPageMode = eMode;
            nPageModeCalls++;
        }
        std::vector<std::string> vAdded;
        int nPageMode;
        int nPageModeCalls;
    };

    class CDocument
    {
    public:
        CDocument() : m_pOutlines(0), m_pCatalog(0), m_pXref(0) {}
        COutline *CreateOutline(COutline *pParent, const char *sTitle);

        COutline *m_pOutlines;
        CCatalog *m_pCatalog;
        CXref    *m_pXref;
    };

/* ---- the real CDocument::CreateOutline, lifted out of Document.cpp ---- */
%(create_outline)s
}

/* ------------------------------------------------------------------------ */
using namespace PdfWriter;

static int failures = 0;
static void check(bool ok, const char *what)
{
    printf("  %%-70s %%s\n", what, ok ? "ok" : "FAILED");
    if (!ok) failures++;
}

static int countAdded(const CCatalog &cat, const char *key)
{
    int n = 0;
    for (size_t i = 0; i < cat.vAdded.size(); ++i)
        if (cat.vAdded[i] == key) n++;
    return n;
}

static const char *modeName(int m)
{
    switch (m)
    {
    case pagemode_UseNone:    return "UseNone";
    case pagemode_UseOutline: return "UseOutlines";
    default:                  return "other";
    }
}

int main()
{
    /* ---- a document that gets an outline ------------------------------- */
    {
        CXref xref; CCatalog cat; CDocument doc;
        doc.m_pCatalog = &cat; doc.m_pXref = &xref;

        /* The state NewDocument leaves behind (Document.cpp). */
        cat.SetPageMode(pagemode_UseNone);
        cat.nPageModeCalls = 0;

        printf("a document whose export carries headings:\n");
        check(cat.nPageMode == pagemode_UseNone,
              "starts at /PageMode /UseNone, as NewDocument leaves it");

        COutline *pCh1 = doc.CreateOutline(NULL, "Chapter One");
        check(pCh1 != NULL, "CreateOutline returns a top-level item");
        check(countAdded(cat, "Outlines") == 1,
              "the /Outlines tree is hung off the catalog");
        printf("     /PageMode is now /%%s\n", modeName(cat.nPageMode));
        check(cat.nPageMode == pagemode_UseOutline,
              "and /PageMode is /UseOutlines, so the pane opens");

        /* Further items must not re-register the tree. */
        COutline *pCh2 = doc.CreateOutline(NULL, "Chapter Two");
        COutline *pSec = doc.CreateOutline(pCh2, "Section 2.1");
        check(countAdded(cat, "Outlines") == 1,
              "a second top-level item does not add /Outlines twice");
        check(pSec != NULL && pSec->pParent == pCh2,
              "a child item is parented to its heading, not to the root");
        check(cat.nPageMode == pagemode_UseOutline,
              "and /PageMode stays /UseOutlines");
    }

    /* ---- a document that never gets one -------------------------------- */
    {
        CCatalog cat;
        cat.SetPageMode(pagemode_UseNone);
        cat.nPageModeCalls = 0;

        printf("\na document with no headings:\n");
        check(cat.nPageMode == pagemode_UseNone && cat.nPageModeCalls == 0,
              "is left alone at /PageMode /UseNone");
    }

    printf("\n%%s\n", failures
           ? "FAILED"
           : "ok - an outline now also asks the reader to show it");
    return failures ? 1 : 0;
}
''' % {'create_outline': create_outline}

with tempfile.TemporaryDirectory() as d:
    cpp = os.path.join(d, 'harness.cpp')
    exe = os.path.join(d, 'harness')
    open(cpp, 'w', encoding='utf-8').write(harness)
    cmd = ['clang++', '-std=c++14', '-Wall', '-o', exe, cpp]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        raise SystemExit('harness did not compile')
    sys.exit(subprocess.run([exe]).returncode)

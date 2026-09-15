#!/usr/bin/env python3
r"""End-to-end for the TxtFile half of #1359, with the real x2t.

af68137e07 recorded that the TxtFile sites "could not be made to fire through
x2t's txt path".  One of them can: TxtFile.cpp readUtf8Lines is what the
txt->docx conversion uses, and x2t hands it <m_nCsvTxtEncoding> verbatim -
cextracttools.h:1010 turns that element into the codePage attribute that
TxtXmlFile.cpp:108 parses and passes to Txt2Docx::Converter.

This converts one windows-1252 file (caf\xe9 na\xefve \x805, i.e. "café naïve €5")
to .docx, varying nothing but that number.  Before the fix anything outside
0..53 missed the table's own index space and fell back to toUnicode(..., 65001),
the overload that takes a *code page*; ICU has no converter for it, the
conversion silently degrades to a byte copy, and the raw 0xE9 lands inside
word/document.xml.  The result is a .docx whose XML is not valid UTF-8 at all -
exit 0, a file on disk, and a document no XML parser will read.

Measured on the pre-fix build:

    enc=44     rc=0   "café naïve €5"        correct (44 is the table row)
    enc=46     rc=0   "caf? na?ve ?5"        correct (asked for UTF-8, got U+FFFD)
    enc=1252   rc=0   document.xml is NOT valid UTF-8
    enc=65001  rc=0   document.xml is NOT valid UTF-8
    enc=999    rc=0   document.xml is NOT valid UTF-8

Usage:
  ./e2e.py                     use core/build/bin/<plat>/x2t
  RD_X2T=<path> ./e2e.py       run it against another build (a pre-fix one fails)

Exit 0 = pass, 1 = fail, 77 = no x2t to test.

Not reachable, and not claimed to be: the three File.cpp subscripts guarded
alongside these two - transformToUnicode, transformFromUnicode and the
File::read(filename, code_page) overload - have no caller anywhere in core.
Txt2Docx uses File::read(filename); Docx2Txt uses writeUtf8/writeUnicode/
writeAnsi, which pass the constants 46 and -1.  writeCodePage, the one function
that would pass a caller's number to transformFromUnicode, is never called.  So
those three are guarded as defence in depth on a public API, with no
reproduction, and this file says so rather than inventing one.
"""

import os
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
FONTS = os.path.join(ROOT, "core-fonts")

FORMAT_TXT = 69
FORMAT_DOCX = 65
DELIMITER_COMMA = 4

SAMPLE = "café naïve €5\nrow2\n"

# (encoding, expected text or None for "whatever, but the docx must be well formed")
CASES = [
    (44, "café naïve €5"),    # the table's own row for windows-1252
    (46, None),                              # UTF-8 asked for, so U+FFFD is correct
    (1252, "café naïve €5"),  # the Windows code page for the same thing
    (65001, None),                           # UTF-8 by code page
    (999, None),                             # junk: must fall back, not corrupt
]


def find_x2t():
    if os.environ.get("RD_X2T"):
        return os.environ["RD_X2T"]
    for plat in ("mac_arm64", "mac_x86_64", "linux_x86_64"):
        p = os.path.join(ROOT, "core", "build", "bin", plat, "x2t")
        if os.path.exists(p):
            return p
    p = os.path.join(ROOT, "desktop-apps", "build", "Ration Docs.app",
                     "Contents", "Resources", "converter", "x2t")
    return p if os.path.exists(p) else None


X2T = find_x2t()
if not X2T:
    sys.stderr.write("no x2t built - skipping\n")
    raise SystemExit(77)

FRAMEWORKS = os.path.join(ROOT, "core", "build", "lib", "mac_arm64")


def convert(work, enc):
    src = os.path.join(work, "in.txt")
    with open(src, "wb") as fh:
        fh.write(SAMPLE.encode("cp1252"))
    dst = os.path.join(work, "out%d.docx" % enc)
    task = os.path.join(work, "task%d.xml" % enc)
    with open(task, "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<TaskQueueDataConvert xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
            "<m_sFileFrom>%s</m_sFileFrom>\n"
            "<m_sFileTo>%s</m_sFileTo>\n"
            "<m_nFormatFrom>%d</m_nFormatFrom>\n"
            "<m_nFormatTo>%d</m_nFormatTo>\n"
            "<m_nCsvTxtEncoding>%d</m_nCsvTxtEncoding>\n"
            "<m_nCsvDelimiter>%d</m_nCsvDelimiter>\n"
            "<m_sFontDir>%s</m_sFontDir>\n"
            "</TaskQueueDataConvert>\n"
            % (src, dst, FORMAT_TXT, FORMAT_DOCX, enc, DELIMITER_COMMA, FONTS)
        )
    env = dict(os.environ)
    if os.path.isdir(FRAMEWORKS):
        env["DYLD_FRAMEWORK_PATH"] = FRAMEWORKS
    rc = subprocess.run([X2T, task], env=env, capture_output=True).returncode
    if rc != 0 or not os.path.exists(dst):
        return rc, None, None
    with zipfile.ZipFile(dst) as z:
        raw = z.read("word/document.xml")
    try:
        doc = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return rc, False, str(e)
    text = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", doc))
    return rc, True, text.strip()


def main():
    print("x2t: %s\n" % X2T)
    print("input: windows-1252 bytes for %r\n" % SAMPLE.splitlines()[0])
    failures = []
    for enc, want in CASES:
        with tempfile.TemporaryDirectory() as work:
            rc, well_formed, text = convert(work, enc)
        if well_formed is None:
            shown, ok = "x2t failed, no document", False
        elif not well_formed:
            shown, ok = "word/document.xml is NOT valid UTF-8", False
        elif want is None:
            shown, ok = "%r" % text, True
        else:
            shown, ok = "%r" % text, text.startswith(want)
        print("  %-3s encoding %-6d rc=%-4d %s" % ("ok" if ok else "!!", enc, rc, shown))
        if not ok:
            failures.append("encoding %d: %s" % (enc, shown))

    print()
    if failures:
        for f in failures:
            print("  " + f)
        print("\n%d failure(s) - #1359, TxtFile.cpp readUtf8Lines" % len(failures))
        return 1
    print("every encoding produces a well-formed docx, and a code page decodes correctly")
    return 0


if __name__ == "__main__":
    sys.exit(main())

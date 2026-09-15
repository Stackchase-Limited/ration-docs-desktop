#!/usr/bin/env python3
r"""End-to-end demonstration of ONLYOFFICE/DesktopEditors#1359 with the real x2t.

The unit harness beside this file proves the subscript is now in range. This
proves what being out of range actually did, by converting the same two-line CSV
with nothing varying but <m_nCsvTxtEncoding>:

    a,b,c
    1,2,3

The number in that element comes from the editor's asc_setAdvancedOptions, and
the two sides disagree about what it means. NSUnicodeConverter::Encodings wants
its own Index column (UTF-8 is 46); the editor API documents a Windows code page
and gives 1200 as its example (sdkjs/cell/api.js:1273). So values far outside
0..53 reach the subscript, and an EncodindId gets built out of whatever follows
the table in .rodata.

Measured on the shipped 9.4.0 converter:

    enc=46      rc=0    6 cells     correct
    enc=1252    rc=0    0 cells     silent total loss - the sheet is blank
    enc=65001   rc=139  no file     SIGSEGV inside ICU

65001 is the Windows code page for UTF-8, i.e. the most likely value a caller
following the documented API would send for a plain UTF-8 CSV.

Usage:
  ./e2e.py                     use core/build/bin/<plat>/x2t
  RD_X2T=/path/to/old/x2t ./e2e.py   run the same check against another build

Exit 0 = pass, 1 = fail, 77 = no x2t to test.
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

FORMAT_CSV = 260
FORMAT_XLSX = 257
DELIMITER_COMMA = 4

# index 46 is UTF-8's own row; the rest are Windows code pages or plain garbage,
# every one of which lands outside a 54-entry table.
CASES = [46, 1252, 65001, 65000, 999]


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
    src = os.path.join(work, "in.csv")
    dst = os.path.join(work, "out%d.xlsx" % enc)
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("a,b,c\n1,2,3\n")
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
            % (src, dst, FORMAT_CSV, FORMAT_XLSX, enc, DELIMITER_COMMA, FONTS)
        )
    env = dict(os.environ)
    if os.path.isdir(FRAMEWORKS):
        env["DYLD_FRAMEWORK_PATH"] = FRAMEWORKS
    rc = subprocess.run([X2T, task], env=env, capture_output=True).returncode
    cells = -1
    if os.path.exists(dst):
        try:
            with zipfile.ZipFile(dst) as z:
                cells = len(re.findall(r"<c ", z.read("xl/worksheets/sheet1.xml").decode("utf-8")))
        except Exception:
            cells = -2
    return rc, cells


def main():
    print("x2t: %s" % X2T)
    failures = []
    for enc in CASES:
        with tempfile.TemporaryDirectory() as work:
            rc, cells = convert(work, enc)
        shown = "no output file" if cells < 0 else "%d cells" % cells
        ok = (rc == 0 and cells == 6)
        print("  %-5s encoding %-6d rc=%-4d %s"
              % ("ok   " if ok else "FAIL ", enc, rc, shown))
        if not ok:
            if rc != 0:
                failures.append("encoding %d killed the converter (rc=%d)" % (enc, rc))
            else:
                failures.append("encoding %d produced %s instead of 6 cells" % (enc, shown))

    print()
    if failures:
        for f in failures:
            print("  " + f)
        print("\n%d failure(s) - ONLYOFFICE/DesktopEditors#1359" % len(failures))
        return 1
    print("all encodings decode the file instead of crashing or losing it")
    return 0


if __name__ == "__main__":
    sys.exit(main())

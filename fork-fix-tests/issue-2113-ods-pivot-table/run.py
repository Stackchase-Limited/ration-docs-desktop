#!/usr/bin/env python3
"""
#2113 - a pivot table turns into plain cells when an ODS is closed and reopened.

The maintainer answered this one with "ODS has functional limitations". ODF does
specify pivot tables (table:data-pilot-table), and LibreOffice round-trips them,
so that answer does not explain the report. What actually happened is that our
xlsx->ods writer emitted the pivot's *container* and nothing inside it.

This drives the real x2t binary, both directions, and asserts on the bytes:

    xlsx (with a pivot)  ->  ods   ->  xlsx

Point X2T at a pre-fix binary and this must fail; that is the whole point.

    X2T=".../Ration Docs.app/Contents/Resources/converter/x2t" ./run.py

Exit 0 = pass. Any other exit = fail.
"""

import os
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

X2T = os.environ.get("X2T", os.path.join(ROOT, "core", "build", "bin", "mac_arm64", "x2t"))
FRAMEWORKS = os.environ.get("X2T_FRAMEWORKS", os.path.join(ROOT, "core", "build", "lib", "mac_arm64"))
FONTS = os.path.join(ROOT, "core-fonts")

FORMAT_XLSX = 257
FORMAT_ODS = 259

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ROWS = [("North", 10), ("South", 20), ("North", 30), ("South", 40)]


def build_pivot_xlsx(path, data_sheet, pivot_sheet):
    """A minimal but genuine xlsx: a data range, a cache over it, and a pivot
    with Region down the rows and Sum of Amount as the data field."""
    parts = {}
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/pivotCache/pivotCacheDefinition1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheDefinition+xml"/>'
        '<Override PartName="/xl/pivotCache/pivotCacheRecords1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.pivotCacheRecords+xml"/>'
        '<Override PartName="/xl/pivotTables/pivotTable1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.pivotTable+xml"/>'
        "</Types>"
    )
    parts["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{R}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{NS}" xmlns:r="{R}"><sheets>'
        f'<sheet name="{data_sheet}" sheetId="1" r:id="rId1"/>'
        f'<sheet name="{pivot_sheet}" sheetId="2" r:id="rId2"/>'
        '</sheets><pivotCaches><pivotCache cacheId="1" r:id="rId3"/></pivotCaches></workbook>'
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{R}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{R}/worksheet" Target="worksheets/sheet2.xml"/>'
        f'<Relationship Id="rId3" Type="{R}/pivotCacheDefinition" Target="pivotCache/pivotCacheDefinition1.xml"/>'
        "</Relationships>"
    )
    cells = '<row r="1"><c r="A1" t="str"><v>Region</v></c><c r="B1" t="str"><v>Amount</v></c></row>'
    for i, (region, amount) in enumerate(ROWS, start=2):
        cells += (
            f'<row r="{i}"><c r="A{i}" t="str"><v>{region}</v></c>'
            f'<c r="B{i}"><v>{amount}</v></c></row>'
        )
    parts["xl/worksheets/sheet1.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS}"><sheetData>{cells}</sheetData></worksheet>'
    )
    parts["xl/worksheets/sheet2.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{NS}"><sheetData/></worksheet>'
    )
    parts["xl/worksheets/_rels/sheet2.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{R}/pivotTable" Target="../pivotTables/pivotTable1.xml"/>'
        "</Relationships>"
    )
    parts["xl/pivotCache/pivotCacheDefinition1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<pivotCacheDefinition xmlns="{NS}" xmlns:r="{R}" r:id="rId1" recordCount="4" refreshOnLoad="0">'
        f'<cacheSource type="worksheet"><worksheetSource ref="A1:B5" sheet="{data_sheet}"/></cacheSource>'
        '<cacheFields count="2">'
        '<cacheField name="Region" numFmtId="0"><sharedItems count="2"><s v="North"/><s v="South"/></sharedItems></cacheField>'
        '<cacheField name="Amount" numFmtId="0"><sharedItems containsSemiMixedTypes="0" containsString="0" '
        'containsNumber="1" containsInteger="1" minValue="10" maxValue="40"/></cacheField>'
        "</cacheFields></pivotCacheDefinition>"
    )
    parts["xl/pivotCache/_rels/pivotCacheDefinition1.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{R}/pivotCacheRecords" Target="pivotCacheRecords1.xml"/>'
        "</Relationships>"
    )
    records = "".join(
        f'<r><x v="{0 if region == "North" else 1}"/><n v="{amount}"/></r>' for region, amount in ROWS
    )
    parts["xl/pivotCache/pivotCacheRecords1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<pivotCacheRecords xmlns="{NS}" xmlns:r="{R}" count="4">{records}</pivotCacheRecords>'
    )
    parts["xl/pivotTables/pivotTable1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<pivotTableDefinition xmlns="{NS}" name="PivotTable1" cacheId="1" dataCaption="Values" '
        'applyNumberFormats="0" applyBorderFormats="0" applyFontFormats="0" applyPatternFormats="0" '
        'applyAlignmentFormats="0" applyWidthHeightFormats="1">'
        '<location ref="A3:B6" firstHeaderRow="1" firstDataRow="1" firstDataCol="0"/>'
        '<pivotFields count="2">'
        '<pivotField axis="axisRow" showAll="0"><items count="3"><item x="0"/><item x="1"/><item t="default"/></items></pivotField>'
        '<pivotField dataField="1" showAll="0"/>'
        "</pivotFields>"
        '<rowFields count="1"><field x="0"/></rowFields>'
        '<rowItems count="3"><i><x/></i><i><x v="1"/></i><i t="grand"><x/></i></rowItems>'
        '<colItems count="1"><i/></colItems>'
        '<dataFields count="1"><dataField name="Sum of Amount" fld="1" baseField="0" baseItem="0"/></dataFields>'
        "</pivotTableDefinition>"
    )
    parts["xl/pivotTables/_rels/pivotTable1.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{R}/pivotCacheDefinition" Target="../pivotCache/pivotCacheDefinition1.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in parts.items():
            z.writestr(name, body)


def convert(work, src, dst, fmt):
    task = os.path.join(work, "task.xml")
    with open(task, "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<TaskQueueDataConvert xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
            f"<m_sFileFrom>{src}</m_sFileFrom>\n"
            f"<m_sFileTo>{dst}</m_sFileTo>\n"
            f"<m_nFormatTo>{fmt}</m_nFormatTo>\n"
            f"<m_sFontDir>{FONTS}</m_sFontDir>\n"
            "</TaskQueueDataConvert>\n"
        )
    env = dict(os.environ)
    if os.path.isdir(FRAMEWORKS):
        env["DYLD_FRAMEWORK_PATH"] = FRAMEWORKS
    proc = subprocess.run([X2T, task], env=env, capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"x2t exited {proc.returncode} converting to format {fmt}\n"
            f"{proc.stdout.decode('utf-8', 'replace')}\n{proc.stderr.decode('utf-8', 'replace')}"
        )


failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f"\n          {detail}" if detail else ""))
        failures.append(label)


def run_case(data_sheet, pivot_sheet, label):
    print(f"\n[{label}]  data sheet {data_sheet!r}, pivot sheet {pivot_sheet!r}")
    with tempfile.TemporaryDirectory() as work:
        src = os.path.join(work, "in.xlsx")
        ods = os.path.join(work, "out.ods")
        back = os.path.join(work, "back.xlsx")

        build_pivot_xlsx(src, data_sheet, pivot_sheet)
        convert(work, src, ods, FORMAT_ODS)

        with zipfile.ZipFile(ods) as z:
            content = z.read("content.xml").decode("utf-8")

        # Take the whole container. Matching the inner element non-greedily would
        # stop at the first "/>" it meets, which is the self-closing
        # source-cell-range child, and silently hide every field after it.
        match = re.search(r"<table:data-pilot-tables\b(?:\s*/>|.*?</table:data-pilot-tables>)", content, re.S)
        block = match.group(0) if match else ""
        check("the ods carries a data-pilot-table", "<table:data-pilot-table " in block)
        if "<table:data-pilot-table " not in block:
            return
        print(f"        {block}")

        # Pre-fix, every optional attribute was written unconditionally, so an
        # unset one streamed out as the literal "--" - not merely missing, but
        # invalid against the ODF schema for booleans and cell ranges.
        check('no attribute is the placeholder "--"', '="--"' not in block,
              "an unset optional was serialised instead of being omitted")

        # An address of "--" is not an address; spell that out so this check
        # cannot pass on the pre-fix output for the wrong reason.
        check("the pivot knows where it is drawn",
              re.search(r'table:target-range-address="(?!--")[^"]+"', block) is not None)
        check("the pivot knows what it is computed from",
              re.search(r'<table:source-cell-range\b[^>]*table:cell-range-address="(?!--")[^"]+"', block) is not None)

        # The sheet name has to survive into the ODF address, quoted or not.
        for sheet in {data_sheet, pivot_sheet}:
            check(f"the address names sheet {sheet!r}", sheet in block)

        check("Region is a row field",
              re.search(r'table:source-field-name="Region"[^/>]*table:orientation="row"', block) is not None)
        check("Amount is a data field summed",
              re.search(r'table:source-field-name="Amount"[^/>]*table:orientation="data"[^/>]*table:function="sum"',
                        block) is not None)
        check("the data field is not emitted twice",
              len(re.findall(r'table:source-field-name="Amount"', block)) == 1)

        # And the round trip: this is the reported scenario - save, close, reopen.
        convert(work, ods, back, FORMAT_XLSX)
        with zipfile.ZipFile(back) as z:
            names = z.namelist()
            check("the reopened workbook still has a pivot table part",
                  any("pivotTables/pivotTable" in n for n in names),
                  "the pivot came back as plain cells")
            if not any("pivotTables/pivotTable" in n for n in names):
                return
            table = z.read("xl/pivotTables/pivotTable1.xml").decode("utf-8")

        check("the reopened pivot still has a row field", "<rowFields" in table)
        check("the reopened pivot still sums", 'subtotal="sum"' in table)


def main():
    if not os.path.exists(X2T):
        print(f"x2t not found at {X2T}; set X2T=", file=sys.stderr)
        return 2
    print(f"x2t: {X2T}")

    run_case("Data", "Pivot", "plain sheet names")
    # A sheet name with a space has to be quoted on the way into the formula
    # converter, or the name is truncated at the space and the address is wrong.
    run_case("Q1 Sales", "Pivot Report", "sheet names with spaces")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

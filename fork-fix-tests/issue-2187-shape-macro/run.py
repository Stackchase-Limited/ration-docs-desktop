#!/usr/bin/env python3
"""
#2187 - "Impossible to execute macro assigned to a shape after reopening a
spreadsheet".

A macro assigned to a shape lives in the drawing part as xdr:sp/@macro, and for
an ONLYOFFICE (JSA) macro its value is "jsaProject_{guid}"; the macro body
itself lives in xl/jsaProject.bin. Losing either one produces the reported
symptom: no pointing-finger cursor, and a click selects the shape instead of
running anything, because sdkjs decides both from CGraphicObjectBase.hasJSAMacro()
which only looks at that string.

What this asserts, by driving the real x2t both ways and reading the bytes:

  1. xlsx -> bin -> xlsx  keeps every @macro, on sp / pic / cxnSp / a shape
     inside a grpSp, across twoCell / oneCell / absolute anchors, and keeps
     xl/jsaProject.bin.  This is the path the desktop editor uses to open and
     save an .xlsx, and it is NOT where #2187 comes from.

  2. xlsx -> ods -> xlsx  loses every @macro while still carrying jsaProject.bin
     into the .ods.  So after saving to ODS the macro is still listed in the
     Macros dialog but no shape is bound to it any more - the report, verbatim.

     That is recorded here as the *current* behaviour, not as desired
     behaviour.  The same check that passes on the xlsx route fails on this
     one, which is what gives check 1 its teeth.  When core/OdfFile learns to
     carry the binding (see the report), flip ODS_CARRIES_MACRO to True and
     this becomes the regression test for that fix.

Exit 0 = pass.  Any other exit = fail.

    ./run.py
    X2T=".../Ration Docs.app/Contents/Resources/converter/x2t" ./run.py   # baseline binary
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
FRAMEWORKS = os.environ.get(
    "X2T_FRAMEWORKS", os.path.join(ROOT, "core", "build", "lib", "mac_arm64")
)
FONTS = os.path.join(ROOT, "core-fonts")

FORMAT_XLSX = 257
FORMAT_ODS = 259
FORMAT_BIN = 8194

GUID = "{11111111-2222-3333-4444-555555555555}"
MACRO = "jsaProject_" + GUID

# Does the ODS route carry a shape's macro binding?  Today it does not: the
# xlsx->ods writer never looks at PPTX::Logic::Shape::macro, and the form-control
# equivalent, odf_controls_context::set_macro, is a stub with its one assignment
# commented out.  Flip this when that changes (ODS_CARRIES_MACRO=1 ./run.py
# demonstrates that the very same checks fail on the ods route today).
ODS_CARRIES_MACRO = os.environ.get("ODS_CARRIES_MACRO", "") not in ("", "0")

# One tiny opaque PNG, so the xdr:pic case is a real picture.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xda c\xfc\xcf\xc0P"
    b"\x0f\x00\x04\x85\x01\x80\x84\xa9\x8c!\x00\x00\x00\x00IEND\xaeB`\x82"
)


def sp(name, ident, macro):
    attr = ' macro="%s"' % macro if macro else ""
    return (
        '<xdr:sp%s textlink=""><xdr:nvSpPr><xdr:cNvPr id="%d" name="%s"/>'
        "<xdr:cNvSpPr/></xdr:nvSpPr>"
        '<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1905000" cy="952500"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        '<a:solidFill><a:srgbClr val="4472C4"/></a:solidFill></xdr:spPr>'
        '<xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/>'
        "<a:t>%s</a:t></a:r></a:p></xdr:txBody></xdr:sp>" % (attr, ident, name, name)
    )


def cxn(name, ident, macro):
    attr = ' macro="%s"' % macro if macro else ""
    return (
        '<xdr:cxnSp%s><xdr:nvCxnSpPr><xdr:cNvPr id="%d" name="%s"/>'
        "<xdr:cNvCxnSpPr/></xdr:nvCxnSpPr>"
        '<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="900000" cy="10000"/></a:xfrm>'
        '<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
        '<a:ln><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>'
        "</xdr:spPr></xdr:cxnSp>" % (attr, ident, name)
    )


def pic(name, ident, macro):
    attr = ' macro="%s"' % macro if macro else ""
    return (
        '<xdr:pic%s><xdr:nvPicPr><xdr:cNvPr id="%d" name="%s"/><xdr:cNvPicPr/></xdr:nvPicPr>'
        '<xdr:blipFill><a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' r:embed="rIdImg"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
        '<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1000000" cy="1000000"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic>'
        % (attr, ident, name)
    )


def grp(name, ident, inner):
    return (
        '<xdr:grpSp><xdr:nvGrpSpPr><xdr:cNvPr id="%d" name="%s"/>'
        "<xdr:cNvGrpSpPr/></xdr:nvGrpSpPr>"
        '<xdr:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="2000000" cy="1000000"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="2000000" cy="1000000"/></a:xfrm></xdr:grpSpPr>'
        "%s</xdr:grpSp>" % (ident, name, inner)
    )


def two_cell(inner, r0, r1):
    return (
        "<xdr:twoCellAnchor><xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff>"
        "<xdr:row>%d</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
        "<xdr:to><xdr:col>5</xdr:col><xdr:colOff>0</xdr:colOff>"
        "<xdr:row>%d</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>"
        "%s<xdr:clientData/></xdr:twoCellAnchor>" % (r0, r1, inner)
    )


def one_cell(inner, r0):
    return (
        "<xdr:oneCellAnchor><xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff>"
        "<xdr:row>%d</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
        '<xdr:ext cx="1905000" cy="952500"/>%s<xdr:clientData/></xdr:oneCellAnchor>'
        % (r0, inner)
    )


def absolute(inner):
    return (
        '<xdr:absoluteAnchor><xdr:pos x="100000" y="100000"/>'
        '<xdr:ext cx="1905000" cy="952500"/>%s<xdr:clientData/></xdr:absoluteAnchor>' % inner
    )


# name -> the element it should come back as
EXPECTED = [
    ("TwoCellShape", "sp"),
    ("OneCellShape", "sp"),
    ("AbsShape", "sp"),
    ("Connector", "cxnSp"),
    ("GroupedShape", "sp"),
    ("Picture1", "pic"),
]


def build_fixture(path, macro):
    """A workbook whose every drawing carries `macro` (or none, for the control),
    plus the jsaProject.bin that holds the macro body."""
    drawing = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        + two_cell(sp("TwoCellShape", 2, macro), 1, 6)
        + one_cell(sp("OneCellShape", 3, macro), 8)
        + absolute(sp("AbsShape", 4, macro))
        + two_cell(cxn("Connector", 5, macro), 16, 20)
        + two_cell(grp("Group1", 6, sp("GroupedShape", 7, macro)), 22, 28)
        + two_cell(pic("Picture1", 8, macro), 30, 34)
        + "</xdr:wsDr>"
    )
    jsa = (
        '{"macrosArray":[{"name":"Macro1","guid":"%s",'
        '"value":"Api.GetActiveSheet().GetRange(\'A1\').SetValue(\'ran\');",'
        '"autostart":false}],"current":0}' % GUID
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="bin" ContentType="application/octet-stream"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
            ' Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.onlyoffice.com/jsaProject" Target="jsaProject.bin"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<dimension ref="A1"/><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>hello</t></is></c></row></sheetData>'
            '<drawing r:id="rId1"/></worksheet>'
        ),
        "xl/worksheets/_rels/sheet1.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"'
            ' Target="../drawings/drawing1.xml"/></Relationships>'
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            "</styleSheet>"
        ),
        "xl/drawings/drawing1.xml": drawing,
        "xl/drawings/_rels/drawing1.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdImg" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
            ' Target="../media/image1.png"/></Relationships>'
        ),
        "xl/jsaProject.bin": jsa,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in parts.items():
            z.writestr(name, body)
        z.writestr("xl/media/image1.png", PNG)


def convert(src, dst, fmt, tmp):
    params = os.path.join(tmp, "params.xml")
    with open(params, "w") as fh:
        fh.write(
            '<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert>'
            "<m_sFileFrom>%s</m_sFileFrom><m_sFileTo>%s</m_sFileTo>"
            "<m_nFormatTo>%d</m_nFormatTo><m_sFontDir>%s</m_sFontDir>"
            "</TaskQueueDataConvert>" % (src, dst, fmt, FONTS)
        )
    env = dict(os.environ)
    env["DYLD_FRAMEWORK_PATH"] = FRAMEWORKS
    env["DYLD_LIBRARY_PATH"] = os.path.dirname(X2T)
    env["LD_LIBRARY_PATH"] = os.path.dirname(X2T)
    rc = subprocess.call([X2T, params], env=env, cwd=os.path.dirname(X2T))
    return rc


def read_drawing(xlsx):
    """(element, name, macro-or-None) for every drawing in the first drawing part."""
    with zipfile.ZipFile(xlsx) as z:
        names = [n for n in z.namelist() if re.match(r"xl/drawings/drawing\d+\.xml$", n)]
        if not names:
            return []
        body = z.read(sorted(names)[0]).decode("utf-8", "replace")
    out = []
    for m in re.finditer(r"<xdr:(sp|cxnSp|pic|grpSp)\b([^>]*)>", body):
        tag, attrs = m.group(1), m.group(2)
        macro = re.search(r'macro="([^"]*)"', attrs)
        nm = re.search(r'name="([^"]*)"', body[m.end() : m.end() + 400])
        out.append((tag, nm.group(1) if nm else "?", macro.group(1) if macro else None))
    return out


def has_jsa(path):
    with zipfile.ZipFile(path) as z:
        return any(n.endswith("jsaProject.bin") for n in z.namelist())


def bound(xlsx):
    """The set of drawing names that came back still carrying our macro."""
    return {name for _tag, name, macro in read_drawing(xlsx) if macro == MACRO}


failures = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        failures.append(what)


def main():
    if not os.path.exists(X2T):
        print("no x2t at %s - build it first" % X2T)
        return 2

    tmp = tempfile.mkdtemp(prefix="issue2187-")
    src = os.path.join(tmp, "in.xlsx")
    build_fixture(src, MACRO)

    print("1. xlsx -> bin -> xlsx  (how the desktop opens and saves an .xlsx)")
    mid = os.path.join(tmp, "mid.bin")
    back = os.path.join(tmp, "back.xlsx")
    rc = convert(src, mid, FORMAT_BIN, tmp)
    check(rc == 0, "xlsx -> bin converted (rc=%d)" % rc)
    if rc == 0:
        rc = convert(mid, back, FORMAT_XLSX, tmp)
        check(rc == 0, "bin -> xlsx converted (rc=%d)" % rc)
    if rc == 0:
        got = bound(back)
        for name, tag in EXPECTED:
            check(name in got, "%s (%s) kept macro=%s through bin" % (name, tag, MACRO))
        check(has_jsa(back), "xl/jsaProject.bin survived the bin round trip")

    print("2. the same check has teeth: a shape with no @macro must not gain one")
    ctl_src = os.path.join(tmp, "ctl.xlsx")
    ctl_mid = os.path.join(tmp, "ctl.bin")
    ctl_back = os.path.join(tmp, "ctl_back.xlsx")
    build_fixture(ctl_src, None)
    if convert(ctl_src, ctl_mid, FORMAT_BIN, tmp) == 0 and convert(
        ctl_mid, ctl_back, FORMAT_XLSX, tmp
    ) == 0:
        check(bound(ctl_back) == set(), "control workbook came back with no bindings")
    else:
        check(False, "control workbook converted")

    print("3. xlsx -> ods -> xlsx  (recorded current behaviour, see the header)")
    ods = os.path.join(tmp, "out.ods")
    ods_back = os.path.join(tmp, "ods_back.xlsx")
    rc = convert(src, ods, FORMAT_ODS, tmp)
    check(rc == 0, "xlsx -> ods converted (rc=%d)" % rc)
    if rc == 0:
        check(has_jsa(ods), "the .ods still carries jsaProject.bin - the macro body is kept")
        rc = convert(ods, ods_back, FORMAT_XLSX, tmp)
        check(rc == 0, "ods -> xlsx converted (rc=%d)" % rc)
    if rc == 0:
        got = bound(ods_back)
        drawings = read_drawing(ods_back)
        check(len(drawings) > 0, "the shapes themselves survived the ods round trip")
        if ODS_CARRIES_MACRO:
            for name, tag in EXPECTED:
                check(name in got, "%s (%s) kept macro=%s through ods" % (name, tag, MACRO))
        else:
            check(
                got == set(),
                "ODS drops every shape->macro binding (known gap; the macro body stays, "
                "so the Macros dialog still lists it and nothing is bound to it)",
            )

    print()
    if failures:
        print("FAILED %d check(s):" % len(failures))
        for f in failures:
            print("  - " + f)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

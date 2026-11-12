"""RD-0055 fixture: the #2187 drawing fixture plus a bar chart (xdr:graphicFrame)
carrying the same @macro. Imported by extract_and_run.py; not a test itself."""
import sys, os, re, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'issue-2187-shape-macro'))
import run as R
CHART = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
 '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
 '<c:chart><c:plotArea><c:layout/><c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
 '<c:ser><c:idx val="0"/><c:order val="0"/><c:val><c:numRef><c:f>Sheet1!$B$1:$B$3</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="3"/>'
 '<c:pt idx="0"><c:v>1</c:v></c:pt><c:pt idx="1"><c:v>2</c:v></c:pt><c:pt idx="2"><c:v>3</c:v></c:pt></c:numCache></c:numRef></c:val></c:ser>'
 '<c:axId val="1"/><c:axId val="2"/></c:barChart>'
 '<c:catAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="b"/><c:crossAx val="2"/></c:catAx>'
 '<c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="l"/><c:crossAx val="1"/></c:valAx>'
 '</c:plotArea><c:plotVisOnly val="1"/></c:chart></c:chartSpace>')
def gf(macro):
    attr = ' macro="%s"' % macro if macro else ''
    return ('<xdr:graphicFrame%s><xdr:nvGraphicFramePr><xdr:cNvPr id="9" name="Chart 1"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>'
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            '<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rIdChart"/>'
            '</a:graphicData></a:graphic></xdr:graphicFrame>' % attr)
def build(path, macro):
    tmp = path + '.base.xlsx'
    R.build_fixture(tmp, macro)
    zin = zipfile.ZipFile(tmp); zout = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
    for n in zin.namelist():
        b = zin.read(n)
        if n == 'xl/drawings/drawing1.xml':
            s = b.decode()
            s = s.replace('</xdr:wsDr>', R.two_cell(gf(macro), 36, 50) + '</xdr:wsDr>')
            b = s.encode()
        elif n == 'xl/drawings/_rels/drawing1.xml.rels':
            b = b.decode().replace('</Relationships>', '<Relationship Id="rIdChart" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/></Relationships>').encode()
        elif n == '[Content_Types].xml':
            b = b.decode().replace('</Types>', '<Override PartName="/xl/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>').encode()
        zout.writestr(n, b)
    zout.writestr('xl/charts/chart1.xml', CHART)
    zout.close(); os.remove(tmp)
def frames(xlsx):
    z = zipfile.ZipFile(xlsx)
    names = sorted(n for n in z.namelist() if re.match(r'xl/drawings/drawing\d+\.xml$', n))
    out = []
    for n in names:
        b = z.read(n).decode()
        for m in re.finditer(r'<xdr:graphicFrame\b([^>]*)>', b):
            mm = re.search(r'macro="([^"]*)"', m.group(1)); out.append(mm.group(1) if mm else None)
    return out, [n for n in z.namelist() if 'charts/chart' in n]

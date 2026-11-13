# a two-sheet book: "Dest" (B3:B6 Arial 9 italic, number format 0.00) and "Src" (rich text, styled cells)
import sys, zipfile
dst = sys.argv[1]
NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet %s>
<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0.00"/></numFmts>
<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font><font><i/><sz val="9"/><name val="Arial"/></font><font><b/><sz val="18"/><name val="Times New Roman"/></font><font><sz val="16"/><name val="Courier New"/></font></fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="2" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>''' % NS
dest = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet %s><sheetData>' % NS
for r in range(3, 7):
    dest += '<row r="%d"><c r="B%d" s="1"/></row>' % (r, r)
dest += '</sheetData></worksheet>'
rich = ('<is><r><rPr><b/><sz val="20"/><color rgb="FFFF0000"/><rFont val="Courier New"/></rPr><t>Big</t></r>'
        '<r><rPr><sz val="14"/><rFont val="Times New Roman"/></rPr><t xml:space="preserve"> red</t></r></is>')
src = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet %s><sheetData>'
       '<row r="3"><c r="B3" t="inlineStr">%s</c></row>'
       '<row r="4"><c r="B4" s="2" t="inlineStr"><is><t>plain styled</t></is></c></row>'
       '<row r="5"><c r="B5" s="3"><v>125.5</v></c></row>'
       '<row r="6"><c r="B6" t="inlineStr"><is><r><rPr><sz val="22"/><rFont val="Courier New"/></rPr><t xml:space="preserve">line1&#10;line2</t></r></is></c></row>'
       '</sheetData></worksheet>') % (NS, rich)
z = zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED)
z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook %s xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Dest" sheetId="1" r:id="rId1"/><sheet name="Src" sheetId="2" r:id="rId2"/></sheets></workbook>' % NS)
z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
z.writestr('xl/styles.xml', styles)
z.writestr('xl/worksheets/sheet1.xml', dest)
z.writestr('xl/worksheets/sheet2.xml', src)
z.close()

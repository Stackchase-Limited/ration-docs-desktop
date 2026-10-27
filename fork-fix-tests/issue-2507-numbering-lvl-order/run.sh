#!/bin/bash
# #2507 - "DOCX save writes w:lvl child elements in alphabetical order, so bullets
# and numbering are lost in Microsoft 365".
#
# Saving rebuilds word/numbering.xml from OOX::Numbering objects, whose toXML wrote
# the children of w:lvl and w:abstractNum alphabetically, w:startOverride after
# w:lvl in w:lvlOverride, and w:numPicBullet after w:num. All four are xsd
# sequences; Word for the web drops every bullet and number of a level written
# out of order.
#
# Builds a small .docx whose numbering is in schema order (a two-level bullet
# list and a "1)" list with a lvlOverride/startOverride), does what open+save
# does - docx -> editor bin -> docx - with the in-tree x2t, and checks every
# numbering element's children against ECMA-376 order.
#
# Shipped 9.4 x2t: FAIL (5 of 9 elements out of order). Fixed: PASS.
# RD_X2T=<path> runs it against another converter.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
X2T="$HERE/../../harness/bin/x2t.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

python3 - "$T/in.docx" <<'PY'
import sys, zipfile
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
def lvl(i, fmt, text, start=1):
    return (f'<w:lvl w:ilvl="{i}"><w:start w:val="{start}"/><w:numFmt w:val="{fmt}"/><w:isLgl/><w:suff w:val="tab"/>'
            f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{720*(i+1)}" w:hanging="360"/></w:pPr>'
            f'<w:rPr><w:rFonts w:ascii="Symbol"/></w:rPr></w:lvl>')
numbering = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering {W}>'
    '<w:abstractNum w:abstractNumId="0"><w:nsid w:val="1A2B3C4D"/><w:multiLevelType w:val="hybridMultilevel"/><w:tmpl w:val="0409000F"/>'
    + lvl(0, 'bullet', '') + lvl(1, 'bullet', 'o') + '</w:abstractNum>'
    '<w:abstractNum w:abstractNumId="1"><w:nsid w:val="5E6F7A8B"/><w:multiLevelType w:val="singleLevel"/>'
    + lvl(0, 'decimal', '%1)') + '</w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    '<w:num w:numId="2"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="3"/></w:lvlOverride></w:num>'
    '</w:numbering>')
def p(text, num=None):
    ppr = f'<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num}"/></w:numPr></w:pPr>' if num else ''
    return f'<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>'
document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>'
    + p('Intro') + p('First bullet', 1) + p('Second bullet', 1) + p('Third item', 2) + p('Fourth item', 2)
    + '<w:sectPr/></w:body></w:document>')
files = {
 '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>',
 '_rels/.rels': '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
 'word/_rels/document.xml.rels': '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>',
 'word/document.xml': document, 'word/numbering.xml': numbering}
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for name, data in files.items(): z.writestr(name, data)
PY

echo "fixture: $(python3 "$HERE/check_order.py" "$T/in.docx")"
"$X2T" "$T/in.docx" "$T/Editor.bin" 8193 >/dev/null
"$X2T" "$T/Editor.bin" "$T/out.docx" 65 >/dev/null
result="$(python3 "$HERE/check_order.py" "$T/out.docx")"
echo "saved:   $result"
case "$result" in
	*"out-of-order 0") echo PASS ;;
	*) echo FAIL; exit 1 ;;
esac

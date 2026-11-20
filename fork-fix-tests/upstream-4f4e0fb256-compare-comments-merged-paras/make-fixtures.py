#!/usr/bin/env python3
"""Writes the docx fixtures of upstream-4f4e0fb256-* and upstream-279413255a-*:
merged-paras.docx (tracked-deleted paragraph marks on P1 and P2, comments in
P1, P2, P3 and one across P2-P3) and duplicate-marks.docx (comment 0 with two
commentRangeStart and two commentRangeEnd marks).
  make-fixtures.py <out dir>"""
import sys, zipfile
def make(out, body, comments):
    W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    files = {
'[Content_Types].xml': '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>''',
'_rels/.rels': '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>''',
'word/_rels/document.xml.rels': '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>''',
'word/document.xml': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>',
'word/comments.xml': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:comments xmlns:w="{W}">' + ''.join(
    f'<w:comment w:id="{i}" w:author="A" w:date="2026-01-01T00:00:00Z" w:initials="A"><w:p><w:r><w:t>{t}</w:t></w:r></w:p></w:comment>' for i, t in comments) + '</w:comments>',
    }
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items(): z.writestr(n, d)

def r(t): return f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>'
def cs(i): return f'<w:commentRangeStart w:id="{i}"/>'
def ce(i): return f'<w:commentRangeEnd w:id="{i}"/><w:r><w:commentReference w:id="{i}"/></w:r>'
DEL = '<w:pPr><w:rPr><w:del w:id="90" w:author="A" w:date="2026-01-01T00:00:00Z"/></w:rPr></w:pPr>'
# tracked-deleted paragraph mark on P1 and P2; comments inside P2, P3 and across
make(sys.argv[1] + '/merged-paras.docx',
     f'<w:p>{DEL}{r("Alpha ")}{cs(0)}{r("one")}{ce(0)}</w:p>'
     f'<w:p>{DEL}{r("Beta ")}{cs(1)}{r("two")}{ce(1)}{r(" x")}{cs(2)}{r("y")}</w:p>'
     f'<w:p>{r("Gamma ")}{cs(3)}{r("three")}{ce(3)}{r(" z")}{ce(2)}</w:p>'
     f'<w:p>{r("Delta")}</w:p>',
     [(0, 'c-one'), (1, 'c-two'), (2, 'c-across'), (3, 'c-three')])
# duplicate start / end marks for comment 0
make(sys.argv[1] + '/duplicate-marks.docx',
     f'<w:p>{r("Alpha ")}{cs(0)}{r("Beta ")}{cs(0)}{r("Gamma")}{ce(0)}{r(" Delta")}{ce(0)}{r(" Epsilon")}</w:p>',
     [(0, 'c-dup')])
print('ok')

#!/bin/bash
# #2482 - "Re-saving a DOCX with comments writes the same paraId for every comment
# in commentsExtended.xml".
#
# commentsExtended.xml and commentsIds.xml identify a comment by the w14:paraId of
# its last paragraph. On save, x2t took that from a counter which only advances
# for paragraphs that get a generated id. A file that has been saved once has a
# w14:paraId on every comment paragraph, so the counter never moved: every
# commentEx became paraId 00000001 and every reply's paraIdParent 00000001.
# Next open, threads were flat and resolved state unmatched; a further save
# dropped the resolved comment.
#
# The fixture is what a first save writes: comment 0 with a reply (comment 1),
# and a resolved comment 2, each paragraph carrying its own paraId. Doing what
# reopen+save does (docx -> editor bin -> docx) must keep three distinct paraIds
# that match comments.xml, the reply's parent, and done="1" on comment 2.
#
# Shipped 9.4 x2t: FAIL (all 00000001). Fixed: PASS. RD_X2T=<path> to compare.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
X2T="$HERE/../../harness/bin/x2t.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

python3 - "$T/in.docx" <<'PY'
import sys, zipfile
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
      'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
H = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
def comment(i, pid, text):
    return (f'<w:comment w:id="{i}" w:author="A" w:date="2026-10-01T10:00:00Z" w:initials="A">'
            f'<w:p w14:paraId="{pid}" w14:textId="77777777"><w:r><w:t>{text}</w:t></w:r></w:p></w:comment>')
comments = (f'{H}<w:comments {NS}>' + comment(0, '1A2B3C01', 'First') + comment(1, '1A2B3C02', 'Reply to first')
            + comment(2, '1A2B3C03', 'Resolved one') + '</w:comments>')
ext = (f'{H}<w15:commentsEx {NS}>'
       '<w15:commentEx w15:paraId="1A2B3C01" w15:done="0"/>'
       '<w15:commentEx w15:paraId="1A2B3C02" w15:paraIdParent="1A2B3C01" w15:done="0"/>'
       '<w15:commentEx w15:paraId="1A2B3C03" w15:done="1"/></w15:commentsEx>')
def ranged(i, text):
    return (f'<w:commentRangeStart w:id="{i}"/><w:r><w:t>{text}</w:t></w:r><w:commentRangeEnd w:id="{i}"/>'
            f'<w:r><w:commentReference w:id="{i}"/></w:r>')
doc = (f'{H}<w:document {NS}><w:body><w:p>' + ranged(0, 'Alpha ') + ranged(1, '') + ranged(2, 'Beta')
       + '</w:p><w:sectPr/></w:body></w:document>')
CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.'
files = {
 '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
   f'<Override PartName="/word/document.xml" ContentType="{CT}document.main+xml"/><Override PartName="/word/comments.xml" ContentType="{CT}comments+xml"/><Override PartName="/word/commentsExtended.xml" ContentType="{CT}commentsExtended+xml"/></Types>',
 '_rels/.rels': '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
 'word/_rels/document.xml.rels': '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
   '<Relationship Id="rId2" Type="http://schemas.microsoft.com/office/2011/relationships/commentsExtended" Target="commentsExtended.xml"/></Relationships>',
 'word/document.xml': doc, 'word/comments.xml': comments, 'word/commentsExtended.xml': ext}
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for n, d in files.items(): z.writestr(n, d)
PY

"$X2T" "$T/in.docx" "$T/Editor.bin" 8193 >/dev/null
"$X2T" "$T/Editor.bin" "$T/out.docx" 65 >/dev/null

python3 - "$T/out.docx" <<'PY'
import sys, zipfile, re
z = zipfile.ZipFile(sys.argv[1])
com = z.read('word/comments.xml').decode()
ext = z.read('word/commentsExtended.xml').decode()
# comment text -> paraId of its last paragraph (x2t may reorder the comments)
pid = {}
for c in re.findall(r'<w:comment\b.*?</w:comment>', com, re.S):
    ids = re.findall(r'w14:paraId="([0-9A-F]+)"', c)
    pid[''.join(re.findall(r'<w:t[^>]*>([^<]*)', c))] = ids[-1] if ids else None
ex = {a['paraId']: a for a in (dict(re.findall(r'w15:(\w+)="([^"]*)"', e))
                               for e in re.findall(r'<w15:commentEx ([^>]*)/>', ext))}
print('comments.xml:', pid)
print('commentsExtended:', list(ex.values()))
first, reply, resolved = pid.get('First'), pid.get('Reply to first'), pid.get('Resolved one')
ok = (len(set(pid.values())) == 3 and set(ex) == set(pid.values())
      and ex[reply].get('paraIdParent') == first and 'paraIdParent' not in ex[first]
      and ex[resolved].get('done') == '1' and ex[first].get('done') == '0')
print('PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
PY

# check.py file.docx - report numbering.xml elements whose children break the ECMA-376 sequence order
import sys,zipfile,re
from xml.etree import ElementTree as ET
W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
ORDER={'lvl':'start numFmt lvlRestart pStyle isLgl suff lvlText lvlPicBulletId legacy lvlJc pPr rPr',
 'abstractNum':'nsid multiLevelType tmpl name styleLink numStyleLink lvl',
 'lvlOverride':'startOverride lvl','numbering':'numPicBullet abstractNum num numIdMacAtCleanup','num':'abstractNumId lvlOverride'}
z=zipfile.ZipFile(sys.argv[1])
if 'word/numbering.xml' not in z.namelist(): print('no-numbering'); sys.exit()
root=ET.fromstring(z.read('word/numbering.xml')); bad=0; n=0
for el in root.iter():
    tag=el.tag.replace(W,'')
    if tag not in ORDER: continue
    seq=ORDER[tag].split(); idx=[seq.index(c.tag.replace(W,'')) for c in el if c.tag.startswith(W) and c.tag.replace(W,'') in seq]
    n+=1
    if idx!=sorted(idx): bad+=1
print('elements',n,'out-of-order',bad)

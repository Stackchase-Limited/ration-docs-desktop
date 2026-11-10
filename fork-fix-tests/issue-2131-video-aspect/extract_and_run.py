#!/usr/bin/env python3
"""
#2131 - a video inserted in a presentation showed padded with black (and was
saved in a frame of the wrong shape) instead of keeping its own aspect ratio.

Insert > Video on the desktop goes AscDesktopEditor.AddVideo -> desktop-sdk
_AddVideo (client_renderer_wrapper.cpp), which copies the media into the
document folder and hands the editor a poster image, then
on_add_multimedia_local -> asc_AddVideoCallback -> addMediaCallback (sdkjs
slide/api.js), which sizes the new picture from the poster. The poster is the
stock sdkjs/common/Images/local/video/image.png - a 300x300 opaque black
square - so every video, whatever its shape, got the same 79.375mm square
frame. The players (AppKit AVPlayerLayer, Qt/VLC) keep the video's aspect and
letterbox it inside the frame with black; the saved pptx carries the square
a:ext, which PowerPoint stretches the video to fill.

Fix: _AddVideo reads the display size of the first visual track from the ISO
base media header (moov/trak/tkhd; 90/270 degree matrix swaps it) and passes
it to on_add_multimedia_local; sdkjs forwards it and addMediaCallback uses it
in place of the poster's size. The frame is then sized like a picture: native
size, scaled to fit the slide.

What this runs (real code, extracted by brace matching, against small stubs):
  1. C++: namespace NSMediaSize from client_renderer_wrapper.cpp compiled with
     the host compiler against a minimal FILE*-based NSFile::CFileBinary, run on
     ISO BMFF files built here: moov after mdat, audio track before video,
     64-bit mdat size, version 1 tkhd, 90 degree display matrix, non-mp4 and
     truncated input. Plus a structural check that the _AddVideo branch passes
     the size it reads into on_add_multimedia_local.
  2. JS (node): the REAL slide/Local/api.js asc_AddVideo, slide/api.js
     asc_AddVideoCallback + addMediaCallback and the REAL
     DrawingObjectsController.prototype.addImage, with a stubbed host that
     answers like _AddVideo (300x300 poster, plus the size when the fixed host
     sends one). Checked: a 1280x720 clip gets a 16:9 frame, 720x1280 a 9:16
     frame; with no size from the host the old poster-based size is kept.

Also verified by hand (not by this test): the real slide sdk in headless
Chromium inserting real ffmpeg-made mp4/mov files through asc_AddVideo, and
the x2t-saved pptx (a:ext 12191999x6858000 for 16:9, 3857625x6858000 for 9:16;
2857500 square before).

NOT claimed: the CEF renderer hop itself (the sCode string is checked only
structurally); the in-app players were not run (they size their view to the
frame they are given, so a frame of the right aspect leaves no bars - needs a
GUI check). webm/mkv/avi/wmv get no size and keep the square frame. The
"pixelated" playback and the black poster before play in the same report are
not addressed here.

Env:
  RD_REPO           desktop-sdk checkout (default ../../desktop-sdk)
  RD_SDKJS          sdkjs checkout (default ../../sdkjs)
  BASELINE=1        read sources from BASE_REF (desktop-sdk) / SDKJS_BASE_REF
                    (sdkjs), the parents of the fix commits: must FAIL.
  CXX               C++ compiler (default c++)
"""
import json
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
SDKJS = os.environ.get('RD_SDKJS') or os.path.normpath(os.path.join(HERE, '..', '..', 'sdkjs'))
BASE_REF = os.environ.get('BASE_REF', '6e140c36^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '3c780add0b^')
BASELINE = bool(os.environ.get('BASELINE'))
CXX = os.environ.get('CXX', 'c++')

WRAPPER = 'ChromiumBasedEditors/lib/src/cefwrapper/client_renderer_wrapper.cpp'


def read(repo, rel, ref):
    if BASELINE:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


def brace_match(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces from offset %d' % start)


def extract(text, anchor, needles=(), optional=False):
    at = text.find(anchor)
    if at == -1:
        if optional:
            return None
        raise SystemExit('%r not found - the extractor needs updating' % anchor)
    body = brace_match(text, at)
    for n in needles:
        if n not in body:
            raise SystemExit('extracted %r is missing %r - wrong block?' % (anchor, n))
    return body


failures = []


def check(ok, what):
    print('%s %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok:
        failures.append(what)


# ---------------------------------------------------------------- ISO BMFF fixtures
def box(kind, payload):
    return struct.pack('>I', 8 + len(payload)) + kind + payload


def box64(kind, payload):
    return struct.pack('>I', 1) + kind + struct.pack('>Q', 16 + len(payload)) + payload


IDENTITY = [0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000]
ROT90 = [0, 0x10000, 0, -0x10000 & 0xFFFFFFFF, 0, 0, 0, 0, 0x40000000]


def tkhd(w, h, version=0, matrix=IDENTITY):
    times = struct.pack('>QQIIQ', 0, 0, 1, 0, 0) if version else struct.pack('>IIIII', 0, 0, 1, 0, 0)
    body = (bytes([version, 0, 0, 3]) + times + b'\0' * 8 + struct.pack('>hhhh', 0, 0, 0, 0)
            + struct.pack('>9I', *matrix) + struct.pack('>II', int(w * 65536), int(h * 65536)))
    return box(b'tkhd', body)


def trak(w, h, **kw):
    return box(b'trak', tkhd(w, h, **kw) + box(b'mdia', b'\0' * 16))


def mp4(*traks, moov_first=False, mdat64=False):
    ftyp = box(b'ftyp', b'isom\0\0\x02\0isomiso2mp41')
    mdat = (box64 if mdat64 else box)(b'mdat', b'\0' * 4096)
    moov = box(b'moov', box(b'mvhd', b'\0' * 100) + b''.join(traks))
    return ftyp + (moov + mdat if moov_first else mdat + moov)


tmp = tempfile.mkdtemp(prefix='rd2131-')
CASES = [
    ('16:9, moov after mdat', mp4(trak(1280, 720)), (1280, 720)),
    ('9:16, moov first (faststart)', mp4(trak(720, 1280), moov_first=True), (720, 1280)),
    ('audio track before the video track', mp4(trak(0, 0), trak(640, 480)), (640, 480)),
    ('64-bit mdat size', mp4(trak(1920, 1080), mdat64=True), (1920, 1080)),
    ('version 1 tkhd', mp4(trak(1024, 768, version=1)), (1024, 768)),
    ('90 degree display matrix (phone video)', mp4(trak(1920, 1080, matrix=ROT90)), (1080, 1920)),
    ('anamorphic: tkhd already holds the display width', mp4(trak(1047.27, 576)), (1047, 576)),
    ('not ISO BMFF (webm header)', b'\x1a\x45\xdf\xa3' + b'\0' * 200, None),
    ('truncated moov', mp4(trak(1280, 720))[:-40], None),
    ('empty file', b'', None),
]
for i, (_, data, _) in enumerate(CASES):
    with open(os.path.join(tmp, 'v%d.mp4' % i), 'wb') as f:
        f.write(data)

# ---------------------------------------------------------------- C++ part
wrapper = read(REPO, WRAPPER, BASE_REF)
print('-- desktop-sdk: reading the video size (%s)' % WRAPPER)
reader = extract(wrapper, 'namespace NSMediaSize', ('GetVideoSize',), optional=True)
add_video = extract(wrapper, 'else if (name == "_AddVideo")', ('on_add_multimedia_local', 'Images/local/video/image'))
check(reader is not None, 'client_renderer_wrapper.cpp has a video size reader (NSMediaSize::GetVideoSize)')
check('GetVideoSize(' in add_video and 'sVideoSize' in add_video.split('on_add_multimedia_local')[1].split(';')[0],
      '_AddVideo passes the size it reads into on_add_multimedia_local')

got = {}
if reader is not None:
    STUB = r'''
#include <cstdio>
#include <string>
#include <algorithm>
typedef unsigned char BYTE; typedef unsigned int DWORD;
namespace NSFile { class CFileBinary { FILE* m_f = nullptr; long m_size = 0; public:
  ~CFileBinary() { if (m_f) fclose(m_f); }
  bool OpenFile(const std::wstring& s) { std::string u(s.begin(), s.end()); m_f = fopen(u.c_str(), "rb"); if (!m_f) return false;
    fseek(m_f, 0, SEEK_END); m_size = ftell(m_f); fseek(m_f, 0, SEEK_SET); return true; }
  long GetFileSize() { return m_size; }
  bool SeekFile(int p, int m = 0) { fseek(m_f, p, m); return true; }
  bool ReadFile(BYTE* d, DWORD n) { return fread(d, 1, n, m_f) == n; }
}; }
'''
    MAIN = r'''
int main(int argc, char** argv) {
  for (int i = 1; i < argc; ++i) { std::string a(argv[i]); int w = 0, h = 0;
    bool ok = NSMediaSize::GetVideoSize(std::wstring(a.begin(), a.end()), w, h);
    printf("%d %d %d\n", ok ? 1 : 0, w, h); }
  return 0; }
'''
    cpp = os.path.join(tmp, 'reader.cpp')
    with open(cpp, 'w') as f:
        f.write(STUB + reader + MAIN)
    exe = os.path.join(tmp, 'reader')
    subprocess.run([CXX, '-std=c++11', '-Wall', '-Werror', '-o', exe, cpp], check=True)
    files = [os.path.join(tmp, 'v%d.mp4' % i) for i in range(len(CASES))]
    lines = subprocess.run([exe] + files, capture_output=True, text=True, check=True).stdout.split('\n')
    for (name, _, _), line in zip(CASES, lines):
        ok, w, h = map(int, line.split())
        got[name] = (w, h) if ok else None
for name, _, want in CASES:
    check(got.get(name, 'n/a') == want, '%-48s -> %s (got %s)' % (name, want, got.get(name, 'n/a')))

# ---------------------------------------------------------------- JS part
print('-- sdkjs: the size reaches the new picture')
local_api = read(SDKJS, 'slide/Local/api.js', SDKJS_BASE_REF)
api = read(SDKJS, 'slide/api.js', SDKJS_BASE_REF)
ctrl = open(os.path.join(SDKJS, 'slide/Editor/DrawingObjectsController.js'), encoding='utf-8').read()
add_video_js = extract(local_api, 'Asc[\'asc_docs_api\'].prototype["pluginMethod_AddVideo"] = Asc[\'asc_docs_api\'].prototype["asc_AddVideo"] = function(obj)', ('AddVideo',))
cb = extract(api, 'asc_docs_api.prototype.asc_AddVideoCallback = function(', ('addMediaCallback',))
media_cb = extract(api, 'asc_docs_api.prototype.addMediaCallback = function(', ('addImages',))
add_image = extract(ctrl, 'DrawingObjectsController.prototype.addImage = function(', ('createImage',))

JS = r'''
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {};
for (const host of input.hosts) {
  const Asc = { 'asc_docs_api': function () {}, c_oAscAsyncActionType: {}, c_oAscAsyncAction: {} };
  const asc_docs_api = Asc['asc_docs_api'];
  function DrawingObjectsController() {}
  const created = [];
  const AscCommon = {
    g_dKoef_pix_to_mm: 25.4 / 96,
    g_oDocumentUrls: { getImageUrl: s => 'file:///doc/media/' + s },
  };
  const window = {};
  window["AscDesktopEditor"] = {
    OpenFilenameDialog(filter, multi, cb) { cb('/home/u/clip.mp4'); },
    // answers like desktop-sdk _AddVideo: stock poster, copied media, then the size if the host sends one
    AddVideo(file, callback) { callback.apply(null, ['display8image1.png', 'display8image1.mp4'].concat(host)); },
  };
  const setTimeout = f => f();
  @ADDVIDEO@;
  @CB@;
  @MEDIACB@;
  @ADDIMAGE@;
  const ctrl = new DrawingObjectsController();
  ctrl.getPresentation = () => ({ GetWidthMM: () => 338.6666666666667, GetHeightMM: () => 190.5 });
  ctrl.createImage = (src, x, y, w, h, videoUrl) => { const s = { src, x, y, w, h, videoUrl, setParent() {}, addToDrawingObjects() {} }; created.push(s); return s; };
  ctrl.selectObject = () => {};
  const api = new asc_docs_api();
  window.editor = api;
  api.sync_StartAction = api.sync_EndAction = () => {};
  api.ImageLoader = {
    LoadImagesWithCallback(urls, f) { f(); },
    LoadImage: () => ({ Image: { width: 300, height: 300 } }), // the stock poster
  };
  api.WordControl = { m_oLogicDocument: { addImages(images) { for (const im of images) ctrl.addImage(im.src, im.Image.width, im.Image.height, im.videoUrl, im.audioUrl); } } };
  api.asc_AddVideo();
  out[JSON.stringify(host)] = created.map(s => ({ w: +s.w.toFixed(3), h: +s.h.toFixed(3), video: s.videoUrl }));
}
process.stdout.write(JSON.stringify(out));
'''
JS = (JS.replace('@ADDVIDEO@', add_video_js).replace('@CB@', cb)
        .replace('@MEDIACB@', media_cb).replace('@ADDIMAGE@', add_image))
hosts = [[1280, 720], [720, 1280], []]
node = subprocess.run(['node', '-e', JS], input=json.dumps({'hosts': hosts}), capture_output=True, text=True)
if node.returncode:
    raise SystemExit('node failed:\n' + node.stderr[-2000:])
res = json.loads(node.stdout)


def aspect(r):
    return round(r[0]['w'] / r[0]['h'], 4) if r else None


r = res['[1280,720]']
check(len(r) == 1 and r[0]['video'] == 'display8image1.mp4', 'one video picture is created with the media attached (got %s)' % r)
check(aspect(r) == round(16 / 9, 4), '1280x720 clip -> 16:9 frame (got %s, %s)' % (aspect(r), r))
check(r and r[0]['w'] == 338.667 and r[0]['h'] == 190.5, '1280x720 clip fits the 16:9 slide exactly (got %s)' % r)
r = res['[720,1280]']
check(aspect(r) == round(9 / 16, 4), '720x1280 clip -> 9:16 frame (got %s, %s)' % (aspect(r), r))
r = res['[]']
check(r == [{'w': 79.375, 'h': 79.375, 'video': 'display8image1.mp4'}],
      'no size from the host -> the poster size as before (got %s)' % r)

print('BASELINE run (sources from %s / %s)' % (BASE_REF, SDKJS_BASE_REF) if BASELINE else 'fixed sources')
if failures:
    print('FAILED: %d check(s)' % len(failures))
    sys.exit(1)
print('ALL PASS')

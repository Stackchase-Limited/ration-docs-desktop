#!/usr/bin/env python3
"""
#1922 - Presentation: a video would not stay muted, and the volume set for it
was not respected.

Two causes, both on the way from the document / the user to the player:

1. sdkjs. A video's own playback settings sit in the slide timing, as
   PowerPoint writes them: <p:video><p:cMediaNode vol="80000" mute="1">
   (vol in thousandths of a percent). Only CCmd.getMediaData - a play/pause
   command fired by an animation - looked them up. Selecting the video in the
   editor, or hovering it in a slide show, opens the player through
   CImageShape.getMediaData (common/Drawings/Format/Image.js), which never
   did: the player got Mute=false, Volume=null and a muted video played with
   sound. When the volume was sent, it went out raw (80000) to players that
   take 0..100.
   Fix: Timing.js getMediaAdditionalData(root, id) (shared with CCmd) and
   CTiming.getMediaAdditionalData; CImageShape.getMediaData attaches it;
   CMediaData.getVol scales vol to 0..100.

2. desktop-sdk. Turning a video down or muting it in the player was lost as
   soon as it was deselected: every showMediaControl builds a new player,
   which started at its default volume again (AppKit 1.0, Qt 50). The AppKit
   glue also passed the 0..100 Volume straight to AVPlayer (0..1).
   Fix: CCefViewMedia (macOS) and QCefView_Media (Qt) remember the volume
   (Qt: and mute state) per media file when the player closes and apply it
   when it opens again, before the media's own setting; the presenter's
   window stays muted and remembers nothing.

What this runs (real code, against small stubs):
  1. JS (node): the REAL CImageShape.prototype.getMediaData, the CMediaData
     block (incl. getPlayerData) from Image.js and CCmd.getMediaData,
     getMediaAdditionalData, CTiming.getMediaAdditionalData and
     CAdditionalMediaData from Timing.js, over a stub slide whose timing
     holds PowerPoint's media nodes. Checked: the player data of a muted
     video says Mute=true/Volume=80, a quiet one Volume=20, both when
     selected and from an animation command; a video without a media node
     and one not on a slide are unchanged.
  2. macOS only: the REAL CCefViewMedia (mac_cefviewmedia.mm) and the REAL
     AppKit player (src/mac_videoplayer, AVPlayer) compiled with clang++
     against a stub mac_cefview.h, driven like the editor drives it. The
     user's volume change goes through the player's own volume slider
     action; the volume is read back from the AVPlayer under the video view.
  3. Optional (Qt 5 qmake + the core kernel library): the REAL
     QCefView_Media (qcefview_media.cpp) and the REAL videoplayerlib
     (QAscVideoView, QMediaPlayer backend), built against a stub qcefview.h
     and run offscreen. Skipped, and said so, when Qt or kernel is missing.

Also verified by hand (not by this test): a pptx with those two media nodes,
converted by x2t to Editor.bin and opened in the real slide sdk in headless
Chromium: selecting / hovering the videos sent Mute=false, Volume=null
before and Mute=true/Volume=80, Volume=20 after; x2t pptx -> pptx keeps
vol/mute.

NOT claimed: the in-app players with real audio output (needs a GUI check);
VLC builds (USE_VLC_LIBRARY) share QAscVideoView but were not built; the
volume a user sets is remembered for the session per editor view and media
file, it is not written into the document (PowerPoint's Playback > Volume
is), and the presenter and audience windows are still not synced (#1943).

Env:
  RD_REPO           desktop-sdk checkout (default ../../desktop-sdk)
  RD_SDKJS          sdkjs checkout (default ../../sdkjs)
  RD_CORE           core checkout, for NSString+StringUtils and kernel headers
                    (default ../../core)
  BASELINE=1        read sources from BASE_REF (desktop-sdk) / SDKJS_BASE_REF
                    (sdkjs), the parents of the fix commits: must FAIL.
  RD_QMAKE          Qt 5 qmake (default /opt/homebrew/opt/qt@5/bin/qmake, then
                    qmake on PATH)
  RD_KERNEL_DIR     dir holding the built core kernel (kernel.framework +
                    UnicodeConverter.framework on macOS, libkernel.so on Linux)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
SDKJS = os.environ.get('RD_SDKJS') or os.path.normpath(os.path.join(HERE, '..', '..', 'sdkjs'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', '83724834^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '39b0fd827b^')
BASELINE = bool(os.environ.get('BASELINE'))
KERNEL_DIR = os.environ.get('RD_KERNEL_DIR') or os.path.normpath(
    os.path.join(HERE, '..', '..', '..', '.rd-work', 'payload', 'converter'))

CBE = 'ChromiumBasedEditors'


def read(repo, rel, ref):
    if BASELINE:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


def materialize(rels, dest):
    """desktop-sdk paths (dirs or files) into dest, from the tree or BASE_REF."""
    if BASELINE:
        arc = subprocess.run(['git', '-C', REPO, 'archive', BASE_REF] + rels, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', dest], input=arc, check=True)
        return
    for rel in rels:
        src, dst = os.path.join(REPO, rel), os.path.join(dest, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)


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


def between(text, start, end):
    i = text.find(start)
    j = text.find(end, i)
    if i == -1 or j == -1:
        raise SystemExit('block %r..%r not found - the extractor needs updating' % (start, end))
    return text[i:j]


failures = []


def check(ok, what):
    print('%s %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok:
        failures.append(what)


# ---------------------------------------------------------------------------------------------
print('-- sdkjs: the media node\'s mute/vol in the player data')
image = read(SDKJS, 'common/Drawings/Format/Image.js', SDKJS_BASE_REF)
timing = read(SDKJS, 'slide/Editor/Format/Timing.js', SDKJS_BASE_REF)
get_media_data = extract(image, 'CImageShape.prototype.getMediaData = function', ('new CMediaData(this)',))
media_block = between(image, 'function CMediaData(drawing)', '//--------------------------------------------------------export')
for n in ('CMediaData.prototype.getPlayerData', 'function CreateMediaData'):
    if n not in media_block:
        raise SystemExit('CMediaData block is missing %r' % n)
cmd_get = extract(timing, 'CCmd.prototype.getMediaData = function', ('setAdditionalData',))
lookup = extract(timing, 'function getMediaAdditionalData(', optional=True) or ''
timing_get = extract(timing, 'CTiming.prototype.getMediaAdditionalData = function', optional=True) or ''
add_data = between(timing, 'function CAdditionalMediaData()', 'changesFactory[AscDFH.historyitem_TimeNodeContainerCTn]')

JS = r'''
const AscFormat = { isRealNumber: v => typeof v === 'number' && isFinite(v) };
const AscCommon = { GlobalSkin: { Type: 'light' } };
const Asc = { editor: { isSlideShow: () => false } };
function CImageShape() {}
function CCmd() {}
function CTiming(nodes) { this.nodes = nodes; }
CTiming.prototype.getTimingRootNode = function () {
    const nodes = this.nodes;   // the tmRoot: traverseTimeNodes visits itself, then its children
    return { traverseTimeNodes(cb) { if (cb({ isVideo: () => false, isAudio: () => false })) return true;
        for (const n of nodes) if (cb(n)) return true; return false; } };
};
CImageShape.prototype.getMediaData = @GETMEDIADATA@;
@MEDIABLOCK@
CCmd.prototype.getMediaData = @CMDGET@;
@LOOKUP@
@TIMINGGET@
@ADDDATA@
// a PowerPoint media node: <p:video|p:audio><p:cMediaNode vol=.. mute=..><p:tgtEl><p:spTgt spid=../>
function mediaNode(spId, attrs, video = true) {
    return { isVideo: () => video, isAudio: () => !video,
             cMediaNode: Object.assign({ mute: null, vol: null, fullScrn: null, getTargetObjectId: () => spId }, attrs) };
}
const timing = new CTiming([mediaNode('sp-muted', { mute: true, vol: 80000 }), mediaNode('sp-quiet', { vol: 20000 })]);
const slide = { timing };
function picture(id, onSlide = true) {
    const sp = new CImageShape();
    Object.assign(sp, { Id: id, selected: true, GetId: () => id, getMediaFileName: () => id + '.mp4', IsUseInDocument: () => true,
        isVideo: () => true, getTransformMatrix: () => null, getMediaStartTime: () => null, getMediaEndTime: () => null,
        getFullRotate: () => 0, getFullFlipH: () => false, getFullFlipV: () => false,
        getParentObjects: () => ({ slide: onSlide ? slide : null }) });
    return sp;
}
const rect = { toObject: () => ({ X: 0, Y: 0, W: 10, H: 10 }) };
const pick = d => d && ({ Mute: d['Mute'], Volume: d['Volume'], MediaFile: d['MediaFile'] });
const out = {};
for (const id of ['sp-muted', 'sp-quiet', 'sp-plain'])
    out['select ' + id] = pick(picture(id).getMediaData().getPlayerData(rect, rect));
out['select off-slide'] = pick(picture('sp-muted', false).getMediaData().getPlayerData(rect, rect));
// the timeline path: a play command on the muted video (CCmd target + its tmRoot)
const cmd = new CCmd();
const shape = picture('sp-muted');
cmd.getTargetObject = () => shape;
cmd.getRoot = () => timing.getTimingRootNode();
out['animation play sp-muted'] = pick(cmd.getMediaData().getPlayerData(rect, rect));
process.stdout.write(JSON.stringify(out));
'''
JS = (JS.replace('@GETMEDIADATA@', get_media_data[get_media_data.index('function'):])
        .replace('@MEDIABLOCK@', media_block).replace('@CMDGET@', cmd_get[cmd_get.index('function'):])
        .replace('@LOOKUP@', lookup).replace('@TIMINGGET@', timing_get + (';' if timing_get else ''))
        .replace('@ADDDATA@', add_data))
node = subprocess.run(['node', '-e', JS], capture_output=True, text=True)
if node.returncode:
    raise SystemExit('node failed:\n' + node.stderr[-2000:])
res = json.loads(node.stdout)
r = res['select sp-muted']
check(r == {'Mute': True, 'Volume': 80, 'MediaFile': 'sp-muted.mp4'},
      'selecting a video with mute="1" vol="80000" -> Mute true, Volume 80 (got %s)' % r)
r = res['select sp-quiet']
check(r == {'Mute': False, 'Volume': 20, 'MediaFile': 'sp-quiet.mp4'},
      'selecting a video with vol="20000" -> Volume 20 (got %s)' % r)
r = res['select sp-plain']
check(r == {'Mute': False, 'Volume': None, 'MediaFile': 'sp-plain.mp4'},
      'a video without a media node -> Mute false, Volume null as before (got %s)' % r)
r = res['select off-slide']
check(r == {'Mute': False, 'Volume': None, 'MediaFile': 'sp-muted.mp4'},
      'a picture not on a slide (no timing) -> no media settings, no error (got %s)' % r)
r = res['animation play sp-muted']
check(r == {'Mute': True, 'Volume': 80, 'MediaFile': 'sp-muted.mp4'},
      'an animation play command on the muted video -> Mute true, Volume 80 (got %s)' % r)


# ---------------------------------------------------------------------------------------------
# what each printed volume is (same order in both drivers; Qt adds the last two)
LABELS = ['file mute="1" vol="80000"', 'file vol="20000"', 'no media setting (player default)',
          'user moves the slider to 30%', 'video deselected and selected again',
          'user turns the file-muted video up to 50%', 'that video selected again',
          'presenter window (always muted)', 'back in the editor, presenter changes not kept',
          'muted with M, selected again', 'M again (unmute)']

MAC_STUB = r'''// stand-in for lib/include/mac_cefview.h: only what CCefViewMedia uses
#ifndef MAC_CEF_VIEW_H
#define MAC_CEF_VIEW_H
#import <Cocoa/Cocoa.h>
#include <string>
#define DESKTOP_DECL
namespace NSEditorApi {
class CAscExternalMediaPlayerCommand {
public:
	std::string Cmd = "showMediaControl", Theme = "light";
	std::wstring Url;
	bool IsSelected = true, Mute = false;
	int Volume = -1;
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_Mute() { return Mute; }
	int get_Volume() { return Volume; }
	int get_From() { return 0; } int get_StartTime() { return -1; } int get_EndTime() { return -1; } bool get_IsSlideShow() { return false; }
	int get_FrameBoundsX() { return 10; } int get_FrameBoundsY() { return 10; }
	int get_FrameBoundsW() { return 320; } int get_FrameBoundsH() { return 180; }
	int get_ControlRectX() { return 10; } int get_ControlRectY() { return 200; }
	int get_ControlRectW() { return 320; } int get_ControlRectH() { return 40; }
};
}
class CCefView { public: bool reporter = false; bool IsPresentationReporter() { return reporter; } void ExecuteInAllFrames(const std::string&, const bool& = true) {} };
class CCefViewWrapper {
public:
	CCefView* m_pCefView = nullptr;
	NSView* m_pParent = nil;
	unsigned int cef_height = 600;
	CCefViewWrapper(NSView* view) : m_pParent(view) {}
	virtual ~CCefViewWrapper() {}
	virtual void OnMediaPlayerCommand(NSEditorApi::CAscExternalMediaPlayerCommand* data) {}
};
#endif
'''

MAC_MAIN = r'''// drives the real CCefViewMedia + mac_videoplayer (AVPlayer) the way the editor does
#include "include/mac_cefviewmedia.h"
#include <cstdio>
static NSView* g_parent;
static float Vol() {   // the AVPlayer behind the open player's video view
	for (NSView* v in g_parent.subviews)
		if ([v.layer isKindOfClass:[AVPlayerLayer class]]) return ((AVPlayerLayer*)v.layer).player.volume;
	return -1;
}
// the volume slider of the open player (a closed player's volume panel leaves the parent only
// when it is deallocated, so take the most recently added one)
static NSSlider* VolumeSlider(NSView* root) {
	NSSlider* found = nil;
	for (NSView* v in root.subviews) {
		if ([v isKindOfClass:[NSSlider class]] && ((NSSlider*)v).isVertical) found = (NSSlider*)v;
		NSSlider* s = VolumeSlider(v); if (s) found = s;
	}
	return found;
}
static void Drag(double part) {   // the user moves the player's volume slider
	NSSlider* s = VolumeSlider(g_parent);
	[s setDoubleValue:s.maxValue * part]; [NSApp sendAction:s.action to:s.target from:s];
}
static void Show(CCefViewMedia& view, const wchar_t* url, bool mute, int volume) {
	NSEditorApi::CAscExternalMediaPlayerCommand cmd; cmd.Url = url; cmd.Mute = mute; cmd.Volume = volume;
	view.OnMediaPlayerCommand(&cmd);
}
static void Hide(CCefViewMedia& view) {
	NSEditorApi::CAscExternalMediaPlayerCommand cmd; cmd.Cmd = "hideMediaControl";
	view.OnMediaPlayerCommand(&cmd);
}
int main() {
	@autoreleasepool {
		[NSApplication sharedApplication];
		g_parent = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 800, 600)];
		CCefView cef; CCefViewMedia view(g_parent); view.m_pCefView = &cef;
		Show(view, L"/nonexistent/a.mp4", true, 80);  printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/b.mp4", false, 20); printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/c.mp4", false, -1); printf("%.2f\n", Vol());
		Drag(0.3); printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/c.mp4", false, -1); printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/a.mp4", true, 80); Drag(0.5); printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/a.mp4", true, 80); printf("%.2f\n", Vol()); Hide(view);
		cef.reporter = true;
		Show(view, L"/nonexistent/c.mp4", false, -1); printf("%.2f\n", Vol()); Drag(0.9); Hide(view);
		cef.reporter = false;
		Show(view, L"/nonexistent/c.mp4", false, -1); printf("%.2f\n", Vol()); Hide(view);
	}
	return 0;
}
'''

QT_STUB = r'''// stand-in for lib/qt_wrapper/include/qcefview.h: only what QCefView_Media uses
#ifndef QCEFWEBVIEW_H
#define QCEFWEBVIEW_H
#include <QWidget>
#include <string>
#define DESKTOP_DECL
namespace NSEditorApi {
class CAscExternalMedia { public: std::wstring get_Url() { return L""; } int get_BoundsX() { return 0; } int get_BoundsY() { return 0; } int get_BoundsW() { return 0; } int get_BoundsH() { return 0; } };
class CAscExternalMediaPlayerCommand {
public:
	std::string Cmd = "showMediaControl", Theme = "light";
	std::wstring Url;
	bool IsSelected = true, Mute = false, IsSlideShow = false;
	int Volume = -1;
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_IsSlideShow() { return IsSlideShow; }
	bool get_Mute() { return Mute; }
	bool get_Fullscreen() { return false; } bool get_IsVideo() { return true; } bool get_FlipH() { return false; } bool get_FlipV() { return false; }
	double get_Rotation() { return 0; }
	int get_Volume() { return Volume; }
	int get_StartTime() { return -1; } int get_EndTime() { return -1; } int get_From() { return 0; }
	int get_FrameRectX() { return 10; } int get_FrameRectY() { return 10; } int get_FrameRectW() { return 320; } int get_FrameRectH() { return 180; }
	int get_FrameBoundsX() { return 10; } int get_FrameBoundsY() { return 10; } int get_FrameBoundsW() { return 320; } int get_FrameBoundsH() { return 180; }
	int get_ControlRectX() { return 10; } int get_ControlRectY() { return 200; } int get_ControlRectW() { return 320; } int get_ControlRectH() { return 40; }
};
}
class CCefView { public: bool reporter = false; bool IsPresentationReporter() { return reporter; } double GetDeviceScale() { return 1; } void ExecuteInAllFrames(const std::string&) {} };
class QCefView : public QWidget
{
	Q_OBJECT
public:
	QCefView(QWidget* parent, const QSize& size = QSize()) : QWidget(parent) {}
	virtual ~QCefView() {}
	CCefView* m_pCefView = nullptr;
};
#endif
'''

QT_MAIN = r'''// drives the real QCefView_Media + videoplayerlib QAscVideoView the way the editor does
#include "x/include/qcefview_media.h"
#include "videoplayerlib/src/qascvideowidget.h"
#include <QApplication>
#include <cstdio>
static QWidget* g_parent;
static QAscVideoView* View() { auto l = g_parent->findChildren<QAscVideoView*>(); return l.isEmpty() ? nullptr : l.last(); }
// what the player plays at: QAscVideoWidget::m_nVolume, set from the footer's volume slider
static int Vol() { QAscVideoView* p = View(); return p ? p->m_pInternal->m_pPlayer->m_nVolume : -1; }
static void Show(QCefView_Media& v, const wchar_t* url, bool mute, int volume) {
	NSEditorApi::CAscExternalMediaPlayerCommand c; c.Url = url; c.Mute = mute; c.Volume = volume; v.OnMediaPlayerCommand(&c);
}
static void Hide(QCefView_Media& v) { NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = "hideMediaControl"; v.OnMediaPlayerCommand(&c); QCoreApplication::processEvents(); }
int main(int argc, char** argv) {
	qputenv("QT_QPA_PLATFORM", "offscreen");
	QApplication app(argc, argv);
	QWidget parent; g_parent = &parent; parent.resize(800, 600);
	CCefView cef; QCefView_Media view(&parent); view.m_pCefView = &cef;
	// ChangeVolume moves the footer's volume slider, the same path as the user dragging it
	Show(view, L"/nonexistent/a.mp4", true, 80);  printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/b.mp4", false, 20); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol());
	View()->ChangeVolume(30); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/a.mp4", true, 80); View()->ChangeVolume(50); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/a.mp4", true, 80); printf("%d\n", Vol()); Hide(view);
	cef.reporter = true;
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol()); View()->ChangeVolume(90); Hide(view);
	cef.reporter = false;
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol());
	// M (ToggleMute) twice: muted, then back to where it was
	View()->ToggleMute(); Hide(view);
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol());
	View()->ToggleMute(); printf("%d\n", Vol()); Hide(view);
	return 0;
}
'''


def player_checks(name, got, expected):
    if len(got) < len(expected):
        check(False, '%s: the driver printed %d of %d values: %s' % (name, len(got), len(expected), got))
        return
    for label, g, e in zip(LABELS, got, expected):
        check(g == e, '%s: %s -> volume %s (got %s)' % (name, label, e, g))


tmp = tempfile.mkdtemp(prefix='rd1922-')
try:
    print('-- desktop-sdk macOS: CCefViewMedia + AppKit player (AVPlayer)')
    if sys.platform != 'darwin':
        print('skip (not macOS)')
    else:
        m = os.path.join(tmp, 'mac')
        os.makedirs(m)
        materialize([CBE + '/lib/include/mac_cefviewmedia.h', CBE + '/lib/src/mac_cefviewmedia.mm',
                     CBE + '/lib/src/mac_videoplayer'], m)
        lib = os.path.join(m, CBE, 'lib')
        open(os.path.join(lib, 'include', 'mac_cefview.h'), 'w').write(MAC_STUB)
        open(os.path.join(lib, 'main.mm'), 'w').write(MAC_MAIN)
        for f in ('NSString+StringUtils.h', 'NSString+StringUtils.mm'):
            shutil.copy(os.path.join(CORE, 'DesktopEditor', 'common', 'Mac', f), os.path.join(lib, 'src', 'mac_videoplayer'))
        vp = os.path.join('src', 'mac_videoplayer')
        srcs = ['main.mm', 'src/mac_cefviewmedia.mm'] + [os.path.join(vp, f) for f in sorted(os.listdir(os.path.join(lib, vp))) if f.endswith('.mm')]
        subprocess.run(['clang++', '-std=c++17', '-w', '-I.', '-I' + vp] + srcs +
                       ['-framework', 'Cocoa', '-framework', 'AVFoundation', '-framework', 'CoreMedia',
                        '-framework', 'QuartzCore', '-o', 'probe'], cwd=lib, check=True)
        out = subprocess.run(['./probe'], cwd=lib, capture_output=True, text=True, check=True).stdout.split()
        player_checks('AppKit', [float(v) for v in out],
                      [0.0, 0.2, 1.0, 0.3, 0.3, 0.5, 0.5, 0.0, 0.3])

    print('-- desktop-sdk Qt: QCefView_Media + videoplayerlib (QMediaPlayer)')
    qmake = os.environ.get('RD_QMAKE') or ('/opt/homebrew/opt/qt@5/bin/qmake' if os.path.exists('/opt/homebrew/opt/qt@5/bin/qmake') else shutil.which('qmake'))
    qver = subprocess.run([qmake, '-query', 'QT_VERSION'], capture_output=True, text=True).stdout.strip() if qmake else ''
    if sys.platform == 'darwin':
        have_kernel = os.path.isdir(os.path.join(KERNEL_DIR, 'kernel.framework'))
        kernel_libs = '-F%s -framework kernel -Wl,-rpath,%s' % (KERNEL_DIR, KERNEL_DIR)
    else:
        have_kernel = os.path.exists(os.path.join(KERNEL_DIR, 'libkernel.so'))
        kernel_libs = '-L%s -lkernel -Wl,-rpath,%s' % (KERNEL_DIR, KERNEL_DIR)
    if not qver.startswith('5.') or not have_kernel:
        print('skip (needs Qt 5 qmake [%s] and the core kernel library in %s)' % (qver or 'none', KERNEL_DIR))
    else:
        q = os.path.join(tmp, 'qt')
        os.makedirs(q)
        materialize([CBE + '/videoplayerlib', CBE + '/lib/qt_wrapper/include/qcefview_media.h',
                     CBE + '/lib/qt_wrapper/src/qcefview_media.cpp'], q)
        # lay the sources out so their relative includes resolve: x/y/videoplayerlib/src/../../../../core = core
        b = os.path.join(q, 'b')
        os.makedirs(os.path.join(b, 'x', 'y'))
        shutil.move(os.path.join(q, CBE, 'videoplayerlib'), os.path.join(b, 'x', 'y', 'videoplayerlib'))
        os.symlink('x/y/videoplayerlib', os.path.join(b, 'videoplayerlib'))
        shutil.move(os.path.join(q, CBE, 'lib', 'qt_wrapper', 'include'), os.path.join(b, 'x', 'include'))
        shutil.move(os.path.join(q, CBE, 'lib', 'qt_wrapper', 'src'), os.path.join(b, 'x', 'src'))
        os.symlink(CORE, os.path.join(b, 'core'))
        open(os.path.join(b, 'x', 'include', 'qcefview.h'), 'w').write(QT_STUB)
        open(os.path.join(b, 'main.cpp'), 'w').write(QT_MAIN)
        V = 'videoplayerlib/src/'
        open(os.path.join(b, 'probe.pro'), 'w').write('\n'.join([
            'QT += core gui printsupport widgets multimedia multimediawidgets',
            'CONFIG += c++17 console', 'CONFIG -= app_bundle', 'TARGET = probe',
            'DEFINES += BUILD_VIDEO_LIBRARY', 'INCLUDEPATH += $$PWD', 'QMAKE_CXXFLAGS += -w',
            'HEADERS += x/include/qcefview.h x/include/qcefview_media.h videoplayerlib/qascvideoview.h videoplayerlib/qfooterpanel.h '
            + ' '.join(V + h for h in ('qiconpushbutton.h', 'qtimelabel.h', 'qfooterpanel_private.h', 'qvideoslider.h',
                                       'qvideoplaylist.h', 'qascvideowidget.h', 'qmultimedia.h', 'lib_base.h')),
            'SOURCES += main.cpp x/src/qcefview_media.cpp '
            + ' '.join(V + s for s in ('lib_base.cpp', 'qiconpushbutton.cpp', 'qtimelabel.cpp', 'qfooterpanel.cpp',
                                       'qascvideoview.cpp', 'qvideoslider.cpp', 'qvideoplaylist.cpp', 'qascvideowidget.cpp',
                                       'qwidgetutils.cpp', 'style/skins_footer.cpp')),
            'RESOURCES += videoplayerlib/IconsVideoPlayerLib.qrc',
            'LIBS += ' + kernel_libs, '']))
        subprocess.run([qmake, 'probe.pro'], cwd=b, check=True, capture_output=True)
        mk = subprocess.run(['make', '-j8'], cwd=b, capture_output=True, text=True)
        if mk.returncode:
            raise SystemExit('Qt probe build failed:\n' + '\n'.join(l for l in mk.stdout.splitlines() + mk.stderr.splitlines() if 'error' in l)[-3000:])
        out = subprocess.run(['./probe'], cwd=b, capture_output=True, text=True, check=True).stdout.split()
        player_checks('Qt', [int(v) for v in out],
                      [0, 20, 50, 30, 30, 50, 50, 0, 30, 0, 30])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('BASELINE run (sources from %s / %s)' % (BASE_REF, SDKJS_BASE_REF) if BASELINE else 'fixed sources')
if failures:
    print('FAILED: %d check(s)' % len(failures))
    sys.exit(1)
print('ALL PASS')

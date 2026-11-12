#!/usr/bin/env python3
"""
#1943 - Presentation: with the presenter's view, playing a video in the
presenter's window did not play it on the slides the audience sees (and the
volume set there did not carry over).

With the presenter's view on, the presenter's window (the "reporter", its own
editor page) and the slide show are two editors, and each opens its own desktop
player for a video: a click on the video in the presenter's window is mirrored
to the slide show (on_mouse_down), which selects it there as well, so both
windows show a player (the presenter's always muted, #1922). They were never
connected:

1. desktop-sdk. The players (AppKit mac_videoplayer, Qt QAscVideoView) handled
   their footer's play/pause, rewind and time slider themselves and told nobody;
   they also had no command to put the media at a position (CCefViewMedia /
   QCefView_Media handled play/pause/stop/togglePause only; the From field of
   the command was never used).
   Fix: a user action in the footer (play/pause button, rewind buttons, time
   slider) is reported to the editor page of the player's view:
   window.editor.asc_onMediaPlayerEvent("play"|"pause"|"seek", <ms>), through
   CCefView::ExecuteInAllFrames (as #1491's key hand-off does). Commands sent to
   the player are not reported (no echo). A new "seek" command moves the media
   to From (ms).
2. sdkjs. asc_onMediaPlayerEvent was an empty stub, and the reporter bridge
   (sendFromReporter -> DemonstrationReporterMessages, sendToReporter ->
   DemonstrationToReporterMessages) had no media message.
   Fix (slide/api.js): asc_onMediaPlayerEvent, in a slide show with the
   presenter's view, sends {media, pos, slide, file} to the other window;
   applyMediaPlayerEvent there opens its player of the same video if needed
   (selects it, as the mirrored click does), then sends "seek" (From = pos) and
   play/pause/stop to its own player. callMediaPlayerCommand takes the From.

So the presenter's play/pause/seek drive the audience's player at the same
position; the audience's sound comes from the slide show, the presenter's player
stays muted. Actions in the slide show's player go to the presenter's player too.

What this runs (real code, against small stubs):
  1. macOS: the REAL CCefViewMedia (mac_cefviewmedia.mm) and the REAL AppKit
     player (src/mac_videoplayer, AVPlayer) compiled with clang++ against a stub
     mac_cefview.h whose CCefView::ExecuteInAllFrames records the JS. A 10 s
     video is made with ffmpeg (if missing, the position checks are skipped).
     The footer's buttons are pressed through their own actions. Checked: play,
     rewind-forward, pause each report the matching asc_onMediaPlayerEvent call
     with the position; a "seek" command puts the AVPlayer at From; commands
     sent to the player report nothing.
  2. Qt (when Qt 5 qmake and the core kernel library exist): the REAL
     QCefView_Media + videoplayerlib against a stub qcefview.h, offscreen: the
     footer's play/pause and rewind slots (what the buttons' clicked signals run) report the
     same calls; commands report nothing.
  3. sdkjs (node, two vm contexts = two windows): the REAL
     asc_onMediaPlayerEvent, applyMediaPlayerEvent, DemonstrationReporterMessages,
     DemonstrationToReporterMessages, sendToReporter, sendFromReporter
     (slide/api.js), callMediaPlayerCommand, getPlayerData, getMediaData,
     hideMediaControl (apiBase.js), the controller's selectObject and
     checkShowMediaControlOnSelect (CommonController.js) and CImageShape.getMediaData
     + CMediaData (Image.js). Only the transport between the windows is stubbed,
     as the desktop delivers it (a string handed to the other page's handler).
     The JS the native player produced in 1./2. is run in the presenter's
     window. Checked: presenter play/seek/pause/stop reach the audience's player
     with the position; the audience's player reaches the presenter's; a closed
     audience player is opened for the video first; nothing is sent outside a
     slide show, without the presenter's view, or to a window on another slide.

Also verified by hand (not by this test): two real slide editors (sdk-all built
from the fork) in headless Chromium on a deck with two videos, wired the same
way: a click on the video in the presenter's window opens a player in both;
before the fix the presenter's play/seek/pause reached nothing, after it the
audience's player got seek+play at the position.

NOT claimed: the players running side by side in the app with sound (needs a
GUI check with the presenter's view); the volume / mute set in one window is not
mirrored (the presenter's player stays muted on purpose); a drag on the time
slider is mirrored on release (AppKit) or on every move (Qt); VLC builds
(USE_VLC_LIBRARY) were not built; videos inside groups are found only when the
receiving window already has their player open.

Env:
  RD_REPO           desktop-sdk checkout (default ../../desktop-sdk)
  RD_SDKJS          sdkjs checkout (default ../../sdkjs)
  RD_CORE           core checkout (NSString+StringUtils, kernel headers; default ../../core)
  BASELINE=1        read sources from BASE_REF (desktop-sdk) / SDKJS_BASE_REF
                    (sdkjs), the parents of the fix commits: must FAIL.
  RD_QMAKE          Qt 5 qmake (default /opt/homebrew/opt/qt@5/bin/qmake, then PATH)
  RD_KERNEL_DIR     dir with the built core kernel (kernel.framework on macOS,
                    libkernel.so on Linux)
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
BASE_REF = os.environ.get('BASE_REF', '3f9d60fc^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', 'b12cc75a46^')
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


def func(text, anchor, needles=(), optional=False):
    """the function expression of `X.prototype.y = function (...) {...}` / `y: function (...) {...}`"""
    body = extract(text, anchor, needles, optional)
    return body[body.index('function'):] if body else None


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


def event_call(code):
    """("play", 1234) from the JS a player ran, by running it against a recording window.editor"""
    js = ('const calls = []; const window = { editor: { asc_onMediaPlayerEvent: (e, p) => calls.push([e, p]) } };'
          + code + '\nprocess.stdout.write(JSON.stringify(calls));')
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True)
    if r.returncode:
        return 'JS error: ' + r.stderr.strip().splitlines()[-1]
    calls = json.loads(r.stdout)
    return tuple(calls[0]) if len(calls) == 1 else calls


MAC_STUB = r'''// stand-in for lib/include/mac_cefview.h: only what CCefViewMedia uses
#ifndef MAC_CEF_VIEW_H
#define MAC_CEF_VIEW_H
#import <Cocoa/Cocoa.h>
#include <string>
#include <vector>
#define DESKTOP_DECL
namespace NSEditorApi {
class CAscExternalMediaPlayerCommand {
public:
	std::string Cmd = "showMediaControl", Theme = "light";
	std::wstring Url;
	bool IsSelected = true, Mute = false, IsSlideShow = false;
	int Volume = -1, From = 0;
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_IsSlideShow() { return IsSlideShow; }
	bool get_Mute() { return Mute; }
	int get_Volume() { return Volume; }
	int get_From() { return From; } int get_StartTime() { return -1; } int get_EndTime() { return -1; }
	int get_FrameBoundsX() { return 10; } int get_FrameBoundsY() { return 10; }
	int get_FrameBoundsW() { return 320; } int get_FrameBoundsH() { return 180; }
	int get_ControlRectX() { return 10; } int get_ControlRectY() { return 200; }
	int get_ControlRectW() { return 320; } int get_ControlRectH() { return 40; }
};
}
class CCefView {
public:
	bool reporter = false;
	std::vector<std::string> code;   // what the view ran in its editor page
	bool IsPresentationReporter() { return reporter; }
	void ExecuteInAllFrames(const std::string& sCode, const bool& isMain = true) { code.push_back(sCode); }
};
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

MAC_MAIN = r'''// drives the real CCefViewMedia + mac_videoplayer (AVPlayer) in the presenter's window
#include "include/mac_cefviewmedia.h"
#import "footerpanel.h"
#include <cstdio>
static NSView* g_parent;
static AVPlayer* Player() {
	for (NSView* v in g_parent.subviews)
		if ([v.layer isKindOfClass:[AVPlayerLayer class]]) return ((AVPlayerLayer*)v.layer).player;
	return nil;
}
static NSFooterPanel* Footer() {
	NSFooterPanel* found = nil;
	for (NSView* v in g_parent.subviews) if ([v isKindOfClass:[NSFooterPanel class]]) found = (NSFooterPanel*)v;
	return found;
}
static void Wait(double sec) { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:sec]]; }
static void Press(NSButton* b) { [NSApp sendAction:b.action to:b.target from:b]; Wait(0.3); }   // the user clicks it
static void Cmd(CCefViewMedia& view, const char* cmd, int from) {   // a command from the editor
	NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = cmd; c.From = from; view.OnMediaPlayerCommand(&c); Wait(0.3);
}
static void Dump(CCefView& cef, size_t from) {
	for (size_t i = from; i < cef.code.size(); ++i) printf("CODE %s\n", cef.code[i].c_str());
	printf("END\n");
}
int main(int argc, char** argv) {
	@autoreleasepool {
		[NSApplication sharedApplication];
		g_parent = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 800, 600)];
		CCefView cef; cef.reporter = true;
		CCefViewMedia view(g_parent); view.m_pCefView = &cef;
		NSEditorApi::CAscExternalMediaPlayerCommand show;
		show.Url = std::wstring(argv[1], argv[1] + strlen(argv[1]));
		view.OnMediaPlayerCommand(&show);
		for (int i = 0; i < 100 && Player().currentItem.status != AVPlayerItemStatusReadyToPlay; ++i) Wait(0.05);
		printf("READY %d\n", Player().currentItem.status == AVPlayerItemStatusReadyToPlay ? 1 : 0);
		// the user: play, 5 s forward, pause
		Press(Footer()->m_btn_play); Dump(cef, 0);
		size_t n = cef.code.size();
		Press(Footer()->m_btn_rewind_forward); Dump(cef, n);
		n = cef.code.size();
		Press(Footer()->m_btn_play); Dump(cef, n);
		// the other window: seek to 2.5 s, play, pause, stop - nothing goes back
		n = cef.code.size();
		Cmd(view, "seek", 2500);
		printf("POS %.2f\n", CMTimeGetSeconds(Player().currentTime));
		Cmd(view, "play", 2500); Cmd(view, "pause", 2500); Cmd(view, "stop", 0);
		Dump(cef, n);
	}
	return 0;
}
'''

QT_STUB = r'''// stand-in for lib/qt_wrapper/include/qcefview.h: only what QCefView_Media uses
#ifndef QCEFWEBVIEW_H
#define QCEFWEBVIEW_H
#include <QWidget>
#include <string>
#include <vector>
#define DESKTOP_DECL
namespace NSEditorApi {
class CAscExternalMedia { public: std::wstring get_Url() { return L""; } int get_BoundsX() { return 0; } int get_BoundsY() { return 0; } int get_BoundsW() { return 0; } int get_BoundsH() { return 0; } };
class CAscExternalMediaPlayerCommand {
public:
	std::string Cmd = "showMediaControl", Theme = "light";
	std::wstring Url;
	bool IsSelected = true, Mute = false, IsSlideShow = false;
	int Volume = -1, From = 0;
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_IsSlideShow() { return IsSlideShow; }
	bool get_Mute() { return Mute; }
	bool get_Fullscreen() { return false; } bool get_IsVideo() { return true; } bool get_FlipH() { return false; } bool get_FlipV() { return false; }
	double get_Rotation() { return 0; }
	int get_Volume() { return Volume; }
	int get_StartTime() { return -1; } int get_EndTime() { return -1; } int get_From() { return From; }
	int get_FrameRectX() { return 10; } int get_FrameRectY() { return 10; } int get_FrameRectW() { return 320; } int get_FrameRectH() { return 180; }
	int get_FrameBoundsX() { return 10; } int get_FrameBoundsY() { return 10; } int get_FrameBoundsW() { return 320; } int get_FrameBoundsH() { return 180; }
	int get_ControlRectX() { return 10; } int get_ControlRectY() { return 200; } int get_ControlRectW() { return 320; } int get_ControlRectH() { return 40; }
};
}
class CCefView {
public:
	bool reporter = false;
	std::vector<std::string> code;   // what the view ran in its editor page
	bool IsPresentationReporter() { return reporter; }
	double GetDeviceScale() { return 1; }
	void ExecuteInAllFrames(const std::string& sCode, const bool& isMain = true) { code.push_back(sCode); }
};
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

QT_MAIN = r'''// drives the real QCefView_Media + videoplayerlib QAscVideoView in the presenter's window
#include "x/include/qcefview_media.h"
#include "videoplayerlib/src/qascvideowidget.h"
#include <QApplication>
#include <cstdio>
static QWidget* g_parent;
static QAscVideoView* View() { auto l = g_parent->findChildren<QAscVideoView*>(); return l.isEmpty() ? nullptr : l.last(); }
static void Dump(CCefView& cef, size_t from) {
	for (size_t i = from; i < cef.code.size(); ++i) printf("CODE %s\n", cef.code[i].c_str());
	printf("END\n");
}
static void Cmd(QCefView_Media& v, const char* cmd, int from) {
	NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = cmd; c.From = from; v.OnMediaPlayerCommand(&c); QCoreApplication::processEvents();
}
int main(int argc, char** argv) {
	qputenv("QT_QPA_PLATFORM", "offscreen");
	QApplication app(argc, argv);
	QWidget parent; g_parent = &parent; parent.resize(800, 600);
	CCefView cef; cef.reporter = true;
	QCefView_Media view(&parent); view.m_pCefView = &cef;
	NSEditorApi::CAscExternalMediaPlayerCommand show; show.Url = L"/nonexistent/a.mp4"; view.OnMediaPlayerCommand(&show);
	// the user: play, 5 s back, pause (the footer slots its buttons' clicked signals are connected to)
	QFooterPanel* f = View()->Footer();
	QMetaObject::invokeMethod(f, "onPlayPauseBtnClicked"); QCoreApplication::processEvents(); Dump(cef, 0);
	size_t n = cef.code.size();
	QMetaObject::invokeMethod(f, "onRewindBackBtnClicked"); QCoreApplication::processEvents(); Dump(cef, n);
	n = cef.code.size();
	View()->m_pInternal->m_bIsPlay = false;   // the player reports Playing (a missing file never plays)
	QMetaObject::invokeMethod(f, "onPlayPauseBtnClicked"); QCoreApplication::processEvents(); Dump(cef, n);
	// the other window: nothing goes back
	n = cef.code.size();
	Cmd(view, "seek", 2500); Cmd(view, "play", 2500); Cmd(view, "pause", 2500); Cmd(view, "togglePause", 0);
	Dump(cef, n);
	return 0;
}
'''


def parse_dumps(out):
    """the CODE lines of each Dump, in order"""
    groups, cur = [], []
    for line in out.splitlines():
        if line.startswith('CODE '):
            cur.append(line[5:])
        elif line == 'END':
            groups.append(cur)
            cur = []
    return groups


native_play_code = None   # the JS a real player ran for the user's play: fed to the sdkjs part
tmp = tempfile.mkdtemp(prefix='rd1943-')
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
        video = os.path.join(tmp, 'ten.mp4')
        if shutil.which('ffmpeg'):
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=duration=10:size=160x120:rate=10',
                            '-pix_fmt', 'yuv420p', video], check=True)
        else:
            video = '/nonexistent/ten.mp4'
        out = subprocess.run(['./probe', video], cwd=lib, capture_output=True, text=True, check=True).stdout
        ready = 'READY 1' in out
        dumps = parse_dumps(out)
        if len(dumps) != 4:
            check(False, 'AppKit: the driver printed %d of 4 groups:\n%s' % (len(dumps), out))
        else:
            calls = [[event_call(c) for c in g] for g in dumps]
            c = calls[0]
            check(len(c) == 1 and c[0][0] == 'play' and c[0][1] == 0,
                  'AppKit: the user presses play -> asc_onMediaPlayerEvent("play", 0) in the editor (got %s)' % c)
            if c and c[0][0] == 'play':
                native_play_code = dumps[0][0].replace('"play", 0', '"play", 1500')
            c = calls[1]
            want = 5000 if ready else 0
            check(len(c) == 1 and c[0][0] == 'seek' and abs(c[0][1] - want) <= 400,
                  'AppKit: the user presses 5 s forward -> ("seek", ~%d) (got %s)' % (want, c))
            c = calls[2]
            check(len(c) == 1 and c[0][0] == 'pause',
                  'AppKit: the user presses pause -> ("pause", <position>) (got %s)' % c)
            check(calls[3] == [], 'AppKit: seek/play/pause/stop commands sent to the player report nothing back (got %s)' % calls[3])
            pos = [l for l in out.splitlines() if l.startswith('POS ')]
            if not ready:
                print('skip AppKit seek position (no playable video: ffmpeg missing?)')
            else:
                p = float(pos[0][4:]) if pos else -1
                check(abs(p - 2.5) < 0.15, 'AppKit: a "seek" command with From=2500 puts the AVPlayer at 2.5 s (got %.2f)' % p)

    print('-- desktop-sdk Qt: QCefView_Media + videoplayerlib')
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
        out = subprocess.run(['./probe'], cwd=b, capture_output=True, text=True, check=True).stdout
        dumps = parse_dumps(out)
        if len(dumps) != 4:
            check(False, 'Qt: the driver printed %d of 4 groups:\n%s' % (len(dumps), out))
        else:
            calls = [[event_call(c) for c in g] for g in dumps]
            check(calls[0] == [('play', 0)], 'Qt: the user presses play -> asc_onMediaPlayerEvent("play", 0) (got %s)' % calls[0])
            if native_play_code is None and calls[0] == [('play', 0)]:
                native_play_code = dumps[0][0].replace('"play", 0', '"play", 1500')
            check(calls[1] == [('seek', 0)], 'Qt: the user presses 5 s back at 0 -> ("seek", 0) (got %s)' % calls[1])
            check(calls[2] == [('pause', 0)], 'Qt: the user presses pause -> ("pause", 0) (got %s)' % calls[2])
            check(calls[3] == [], 'Qt: commands sent to the player report nothing back (got %s)' % calls[3])
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------
print('-- sdkjs: presenter window <-> slide show over the reporter bridge (two vm contexts)')
api = read(SDKJS, 'slide/api.js', SDKJS_BASE_REF)
base = read(SDKJS, 'common/apiBase.js', SDKJS_BASE_REF)
ctl = read(SDKJS, 'common/Drawings/CommonController.js', SDKJS_BASE_REF)
image = read(SDKJS, 'common/Drawings/Format/Image.js', SDKJS_BASE_REF)

parts = {
    'reporterMessages': func(api, 'asc_docs_api.prototype.DemonstrationReporterMessages = function', ('reporter_command',)),
    'toReporterMessages': func(api, 'asc_docs_api.prototype.DemonstrationToReporterMessages = function', ('main_command',)),
    'sendToReporter': func(api, 'asc_docs_api.prototype.sendToReporter = function', ('sendToReporter',)),
    'sendFromReporter': func(api, 'asc_docs_api.prototype.sendFromReporter = function', ('sendFromReporter',)),
    'onMediaPlayerEvent': func(api, 'asc_docs_api.prototype.asc_onMediaPlayerEvent = function', optional=True)
                          or func(base, 'baseEditorsApi.prototype.asc_onMediaPlayerEvent = function'),
    'applyMediaPlayerEvent': func(api, 'asc_docs_api.prototype.applyMediaPlayerEvent = function', optional=True) or 'undefined',
    'callMediaPlayerCommand': func(base, 'baseEditorsApi.prototype.callMediaPlayerCommand = function', ('CallMediaPlayerCommand',)),
    'getPlayerData': func(base, 'baseEditorsApi.prototype.getPlayerData = function', ('GetMediaPlayerData',)),
    'getMediaData': func(base, 'baseEditorsApi.prototype.getMediaData = function'),
    'hideMediaControl': func(base, 'baseEditorsApi.prototype.hideMediaControl = function', ('hideMediaControl',)),
    'selectObject': func(ctl, 'selectObject: function (object, pageIndex)', ('checkShowMediaControlOnSelect',)),
    'checkOnSelect': func(ctl, 'checkShowMediaControlOnSelect: function', ('showMediaControl',)),
    'imageGetMediaData': func(image, 'CImageShape.prototype.getMediaData = function', ('new CMediaData(this)',)),
    'mediaBlock': between(image, 'function CMediaData(drawing)', '//--------------------------------------------------------export'),
}
if '"main_command"' not in api or "'asc_onMediaPlayerEvent'" not in base:
    raise SystemExit('reporter bridge / media event stub not where expected - the extractor needs updating')

JS = r'''
const vm = require('vm');
const P = @PARTS@;
// one editor window: the real functions on a stub api/slide; only AscDesktopEditor is the desktop
function makeWindow(name, isReporter) {
    const ctx = { name, sent: [], media: [], JSON, console };
    ctx.window = ctx;
    vm.createContext(ctx);
    vm.runInContext(`
        var AscFormat = { isRealNumber: v => typeof v === 'number' && isFinite(v),
                          IsEqualObjects: (a, b) => JSON.stringify(a) === JSON.stringify(b) };
        var AscCommon = { GlobalSkin: { Type: 'light' } };
        var Asc = {};
        function CImageShape() {}
        CImageShape.prototype.getMediaData = ${P.imageGetMediaData};
        ${P.mediaBlock}
        CImageShape.prototype.select = function (ctl) { this.selected = true; ctl.selectedObjects.push(this); };
        function video(id, file) {
            const sp = new CImageShape();
            Object.assign(sp, { Id: id, selected: false, getMediaFileName: () => file, IsUseInDocument: () => true,
                isVideo: () => true, getMediaStartTime: () => null, getMediaEndTime: () => null,
                getFullRotate: () => 0, getFullFlipH: () => false, getFullFlipV: () => false,
                getParentObjects: () => ({ slide: null }) });
            return sp;
        }
        // the slides: slide 0 has two videos, slide 1 none
        var ctl = { selectedObjects: [], getSelectedArray() { return this.selectedObjects; },
                    resetSelection() { this.selectedObjects.forEach(o => o.selected = false); this.selectedObjects = []; } };
        ctl.selectObject = ${P.selectObject};
        ctl.checkShowMediaControlOnSelect = ${P.checkOnSelect};
        var slides = [{ graphicObjects: ctl, drawings: [video('${name}-1', 'video1.mp4'), video('${name}-2', 'video2.mp4')] }, { graphicObjects: ctl, drawings: [] }];
        slides.forEach(s => s.getDrawingObjects = () => s.drawings);
        var rect = { toObject: () => ({ X: 0, Y: 0, W: 10, H: 10 }) };
        function Api() {
            this.isReporterMode = ${isReporter};
            this.reporterWindow = null;
            this.disableReporterEvents = false;
            this.mediaData = null;
            this.WordControl = {
                DemonstrationManager: { Mode: true, SlideNum: 0 },
                m_oLogicDocument: { GetSlide: n => slides[n] },
                GetMediaPlayerData: md => (md && md.isValid()) ? md.getPlayerData(rect, rect) : null,
            };
        }
        Api.prototype.isSlideShow = function () { return !!this.WordControl.DemonstrationManager.Mode; };
        Api.prototype.addMacroStepData = function () {};
        Api.prototype.getAnnotations = function () { return null; };
        Api.prototype.sendEvent = function () {};
        Api.prototype.DemonstrationReporterMessages = ${P.reporterMessages};
        Api.prototype.DemonstrationToReporterMessages = ${P.toReporterMessages};
        Api.prototype.sendToReporter = ${P.sendToReporter};
        Api.prototype.sendFromReporter = ${P.sendFromReporter};
        Api.prototype.asc_onMediaPlayerEvent = ${P.onMediaPlayerEvent};
        Api.prototype.applyMediaPlayerEvent = ${P.applyMediaPlayerEvent};
        Api.prototype.callMediaPlayerCommand = ${P.callMediaPlayerCommand};
        Api.prototype.getPlayerData = ${P.getPlayerData};
        Api.prototype.getMediaData = ${P.getMediaData};
        Api.prototype.hideMediaControl = ${P.hideMediaControl};
        Api.prototype.editorId = 1;
        var c_oEditorId = { Word: 0, Presentation: 1, Spreadsheet: 2 };
        var editor = new Api();
        window.editor = editor; Asc.editor = editor;
        window.AscDesktopEditor = {
            sendToReporter: v => sent.push(v), sendFromReporter: v => sent.push(v),
            CallMediaPlayerCommand: d => media.push(d['Cmd'] + ' ' + d['MediaFile'] + (d['Cmd'] === 'hideMediaControl' ? '' : ' sel=' + d['IsSelected']) + (d['From'] ? ' From=' + d['From'] : '')),
        };
    `, ctx);
    return ctx;
}
const main = makeWindow('main', false), rep = makeWindow('rep', true);
main.editor.reporterWindow = {};   // DemonstrationReporterStart on the desktop
// the desktop: what one window sends, the other's renderer hands to its handler as { data: string }
function pump() {
    for (let k = 0; k < 5; k++) {
        const a = main.sent.splice(0), b = rep.sent.splice(0);
        if (!a.length && !b.length) return;
        a.forEach(v => vm.runInContext('editor.DemonstrationToReporterMessages({ data: ' + JSON.stringify(v) + ' })', rep));
        b.forEach(v => vm.runInContext('editor.DemonstrationReporterMessages({ data: ' + JSON.stringify(v) + ' })', main));
    }
}
const take = w => w.media.splice(0);
// a click on video 1 in the presenter's window, mirrored to the slide show (on_mouse_down): both select it
const click = (w, i) => vm.runInContext(`ctl.resetSelection(); ctl.selectObject(slides[0].drawings[${i}], 0);`, w);
const player = (w, code) => { vm.runInContext(code, w); pump(); };
const ev = (e, p) => `window.editor && window.editor.asc_onMediaPlayerEvent && window.editor.asc_onMediaPlayerEvent("${e}", ${p});`;
const out = {};
click(rep, 0); click(main, 0); take(rep); take(main);
player(rep, @NATIVE@);
out.native = { rep: take(rep), main: take(main) };
for (const [e, p] of [['seek', 4200], ['pause', 5100], ['play', 5100], ['stop', 0]]) {
    player(rep, ev(e, p));
    out['rep ' + e] = { rep: take(rep), main: take(main) };
}
player(main, ev('pause', 7300));
out['main pause'] = { rep: take(rep), main: take(main) };
// the slide show's player of video 1 closed (deselected); presenter plays video 2
vm.runInContext('ctl.resetSelection(); editor.hideMediaControl(); editor.mediaData = null;', main); take(main);
click(rep, 1); take(rep);
player(rep, ev('play', 800));
out['closed'] = { rep: take(rep), main: take(main) };
// the slide show on another slide: ignored
main.editor.WordControl.DemonstrationManager.SlideNum = 1;
player(rep, ev('play', 900));
out['other slide'] = { rep: take(rep), main: take(main) };
main.editor.WordControl.DemonstrationManager.SlideNum = 0;
// no presenter's view: the slide show's player keeps it to itself
main.editor.reporterWindow = null;
player(main, ev('play', 1000));
out['no reporter'] = { sent: main.sent.length, rep: take(rep), main: take(main) };
main.editor.reporterWindow = {};
// the editor, not a slide show
rep.editor.WordControl.DemonstrationManager.Mode = false;
player(rep, ev('play', 1100));
out['editor'] = { rep: take(rep), main: take(main) };
process.stdout.write(JSON.stringify(out));
'''
native = native_play_code
if native is None:
    print('note: no native player probe ran; the presenter\'s player call is written by hand')
    native = 'window.editor && window.editor.asc_onMediaPlayerEvent && window.editor.asc_onMediaPlayerEvent("play", 1500);'
JS = JS.replace('@PARTS@', json.dumps(parts)).replace('@NATIVE@', json.dumps(native))
node = subprocess.run(['node', '-e', JS], capture_output=True, text=True)
if node.returncode:
    raise SystemExit('node failed:\n' + node.stderr[-3000:])
res = json.loads(node.stdout)
V1, V2 = 'video1.mp4', 'video2.mp4'


def expect(key, want, what):
    got = res[key]
    check(got == want, '%s (got %s)' % (what, json.dumps(got)))


expect('native', {'rep': [], 'main': ['seek %s sel=true From=1500' % V1, 'play %s sel=true From=1500' % V1]},
       'the presenter presses play in its player (the JS the native player ran) -> the slide show\'s player seeks to 1.5 s and plays')
expect('rep seek', {'rep': [], 'main': ['seek %s sel=true From=4200' % V1]},
       'presenter seeks to 4.2 s -> slide show\'s player seeks there')
expect('rep pause', {'rep': [], 'main': ['seek %s sel=true From=5100' % V1, 'pause %s sel=true From=5100' % V1]},
       'presenter pauses at 5.1 s -> slide show\'s player pauses at 5.1 s')
expect('rep play', {'rep': [], 'main': ['seek %s sel=true From=5100' % V1, 'play %s sel=true From=5100' % V1]},
       'presenter plays again -> slide show\'s player plays from 5.1 s')
expect('rep stop', {'rep': [], 'main': ['stop %s sel=true' % V1]},
       'presenter stops -> slide show\'s player stops')
expect('main pause', {'rep': ['seek %s sel=true From=7300' % V1, 'pause %s sel=true From=7300' % V1], 'main': []},
       'pause in the slide show\'s player -> the presenter\'s player pauses at the same position')
expect('closed', {'rep': [], 'main': ['showMediaControl %s sel=true' % V2, 'setMediaFlags %s sel=true' % V2, 'seek %s sel=true From=800' % V2, 'play %s sel=true From=800' % V2]},
       'slide show without an open player -> it opens one for the same video (with its playback flags, #2005), seeks, plays')
expect('other slide', {'rep': [], 'main': []}, 'slide show on another slide -> nothing')
expect('no reporter', {'sent': 0, 'rep': [], 'main': []}, 'slide show without the presenter\'s view -> nothing sent')
expect('editor', {'rep': [], 'main': []}, 'player in the editor (no slide show) -> nothing sent')

print('BASELINE run (sources from %s / %s)' % (BASE_REF, SDKJS_BASE_REF) if BASELINE else 'fixed sources')
if failures:
    print('FAILED: %d check(s)' % len(failures))
    sys.exit(1)
print('ALL PASS')

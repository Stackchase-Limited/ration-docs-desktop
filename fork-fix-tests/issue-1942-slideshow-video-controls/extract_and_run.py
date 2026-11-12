#!/usr/bin/env python3
"""
#1942 - Presentation: the video controls stayed over the video during a slide show.

In a slide show the desktop player's footer (play/pause, time slider, volume) is laid over the
bottom of the video (sdkjs GetMediaControlRect, DemonstrationManager branch) and, once the player
was open, it stayed there the whole time: over a playing video, with the mouse resting or
elsewhere on the slide. PowerPoint shows the controls only while the mouse is over the video and
hides them while it plays and the mouse rests.

Cause (desktop-sdk): neither player had a slide-show state for the footer. macOS
(lib/src/mac_videoplayer, CPlayerView/NSFooterPanel) creates the footer visible and never hides it;
Qt (videoplayerlib QAscVideoView) shows it with the player (qcefview_media.cpp showMediaControl,
QAscVideoView::slotVideoAvailableChanged) and only hides it in its own fullscreen mode. The
player already receives IsSlideShow with every command (#1491).

Fix: with IsSlideShow the footer is shown only while the mouse is on the footer (or its open
volume panel), or over the video unless the video is playing and the mouse has not moved for
2 s; it hides when the mouse leaves. Outside a slide show it is always shown, as before.
macOS: NSPlayerControllerBridge setSlideShowMode / updateFooterVisibility, set from
CCefViewMedia::OnMediaPlayerCommand. Qt: QAscVideoView::setSlideShowMode (already set by
QCefView_Media) + UpdateSlideShowFooter. Both poll the mouse position every 100 ms.

What this runs (real code, against small stubs):
  1. macOS: the REAL CCefViewMedia (mac_cefviewmedia.mm) and the REAL AppKit player
     (src/mac_videoplayer, AVPlayer) compiled with clang++ against a stub mac_cefview.h, in an
     (unshown) NSWindow; +[NSEvent mouseLocation] is replaced so the test moves "the mouse".
     The player plays a 10 s test video made with ffmpeg. Read back: NSFooterPanel.hidden.
  2. Qt 5 (Homebrew qt@5 + the core kernel library): the REAL QCefView_Media and the REAL
     videoplayerlib (QAscVideoView, QMediaPlayer) against a stub qcefview.h, offscreen platform,
     the mouse moved with QCursor::setPos. Read back: QFooterPanel::isHidden(). Skipped, and said
     so, when Qt or kernel is missing. The "playing" steps need QMediaPlayer to actually play the
     file; if it does not reach PlayingState they are skipped and said so.

NOT claimed: how it looks and feels in the real app (needs a GUI check: hover, 2 s fade-out,
clicking the footer buttons in a running show); that the editor's web view still gets the mouse
while it is over the player's views (polling makes the footer independent of that); the VLC
build of videoplayerlib; Windows/Linux window managers.

Env:
  RD_REPO       desktop-sdk checkout (default ../../desktop-sdk)
  RD_CORE       core checkout, for NSString+StringUtils and kernel headers (default ../../core)
  BASELINE=1    read sources from BASE_REF (default: parent of the fix commit): must FAIL.
  RD_QMAKE      Qt 5 qmake (default /opt/homebrew/opt/qt@5/bin/qmake, then qmake on PATH)
  RD_KERNEL_DIR dir with the built core kernel (kernel.framework on macOS, libkernel.so on Linux)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'f5635e16^')
BASELINE = bool(os.environ.get('BASELINE'))
KERNEL_DIR = os.environ.get('RD_KERNEL_DIR') or os.path.normpath(
    os.path.join(HERE, '..', '..', '..', '.rd-work', 'payload', 'converter'))

CBE = 'ChromiumBasedEditors'


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


failures = []


def check(ok, what):
    print('%s %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok:
        failures.append(what)


# each step: (label, expected footer hidden) - the drivers print "<label>|<hidden 0/1>" per step
STEPS = [
    ('slide show, player opens, mouse elsewhere on the slide', 1),
    ('slide show, mouse moves over the video (not playing)', 0),
    ('slide show, mouse leaves the video', 1),
    ('slide show, mouse back over the video, video starts playing', 0),
    ('slide show, playing, mouse rests over the video 2.5 s', 1),
    ('slide show, playing, mouse moves over the video', 0),
    ('slide show, playing, mouse rests on the footer 2.5 s', 0),
    ('slide show, playing, mouse leaves', 1),
    ('slide show ends under the player (update command)', 0),
    ('editor, new player, mouse elsewhere', 0),
    ('editor, playing, mouse rests over the video 2.5 s', 0),
]
PLAYING_STEPS = {3, 4, 5, 6, 7, 10}


def results(name, out, have_playing=True):
    got = {}
    for line in out.splitlines():
        if '|' in line:
            label, hidden = line.rsplit('|', 1)
            got[label] = int(hidden)
    for i, (label, hidden) in enumerate(STEPS):
        if i in PLAYING_STEPS and not have_playing:
            print('skip %s: %s (the media did not play here)' % (name, label))
            continue
        g = got.get(label)
        check(g == hidden, '%s: %s -> footer %s (got %s)' % (
            name, label, 'hidden' if hidden else 'shown', {None: 'nothing', 0: 'shown', 1: 'hidden'}[g]))


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
	bool IsSelected = true, Mute = true, IsSlideShow = false;
	int Volume = -1;
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_IsSlideShow() { return IsSlideShow; }
	bool get_Mute() { return Mute; }
	int get_Volume() { return Volume; }
	int get_From() { return 0; } int get_StartTime() { return -1; } int get_EndTime() { return -1; }
	// video 10,10 320x180; in a slide show sdkjs lays the footer over the video's bottom
	int get_FrameBoundsX() { return 10; } int get_FrameBoundsY() { return 10; }
	int get_FrameBoundsW() { return 320; } int get_FrameBoundsH() { return 180; }
	int get_ControlRectX() { return 30; } int get_ControlRectY() { return 140; }
	int get_ControlRectW() { return 280; } int get_ControlRectH() { return 40; }
};
}
class CCefView { public: bool IsPresentationReporter() { return false; } void ExecuteInAllFrames(const std::string&, const bool& = true) {} };
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

# parent is the window's content view at the screen origin, so screen = view coordinates (y up):
# video x 10..330, y 410..590; footer x 30..310, y 420..460
MAC_MAIN = r'''// drives the real CCefViewMedia + mac_videoplayer the way the editor does, moving a fake mouse
#include "include/mac_cefviewmedia.h"
#include <objc/runtime.h>
#include <cstdio>
#include <string>
static NSPoint g_mouse = NSMakePoint(700, 100);
static NSView* g_parent;
static std::wstring g_url;
static const NSPoint kAway = NSMakePoint(700, 100), kVideo = NSMakePoint(170, 550), kFooter = NSMakePoint(170, 440);
static void Spin(double sec) { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:sec]]; }
static NSFooterPanel* Footer() {   // the open player's footer: the last one added to the parent
	NSFooterPanel* found = nil;
	for (NSView* v in g_parent.subviews) if ([v isKindOfClass:[NSFooterPanel class]]) found = (NSFooterPanel*)v;
	return found;
}
static AVPlayer* Player() {
	for (NSView* v in g_parent.subviews)
		if ([v.layer isKindOfClass:[AVPlayerLayer class]]) return ((AVPlayerLayer*)v.layer).player;
	return nil;
}
static void Report(const char* label) { NSFooterPanel* f = Footer(); printf("%s|%d\n", label, f ? (int)f.hidden : -1); fflush(stdout); }
static void Move(NSPoint p, double wait = 0.3) { g_mouse = p; Spin(wait); }
static void Cmd(CCefViewMedia& view, const char* name, bool slide_show) {
	NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = name; c.Url = g_url; c.IsSlideShow = slide_show;
	view.OnMediaPlayerCommand(&c);
}
static void Play(CCefViewMedia& view, bool slide_show) {
	Cmd(view, "play", slide_show);
	for (int i = 0; i < 50 && Player().rate <= 0; ++i) Spin(0.1);
	Spin(0.2);
}
int main(int argc, char** argv) {
	@autoreleasepool {
		[NSApplication sharedApplication];
		Method m = class_getClassMethod([NSEvent class], @selector(mouseLocation));
		method_setImplementation(m, imp_implementationWithBlock(^NSPoint(id) { return g_mouse; }));
		NSString* path = [NSString stringWithUTF8String:argv[1]];
		g_url = std::wstring((const wchar_t*)[path cStringUsingEncoding:NSUTF32LittleEndianStringEncoding], path.length);
		NSWindow* window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 800, 600) styleMask:NSWindowStyleMaskBorderless
														  backing:NSBackingStoreBuffered defer:YES];
		[window setFrameOrigin:NSMakePoint(0, 0)];
		g_parent = window.contentView;
		CCefView cef; CCefViewMedia view(g_parent); view.m_pCefView = &cef;

		Move(kAway, 0);
		Cmd(view, "showMediaControl", true); Spin(0.3);
		Report("slide show, player opens, mouse elsewhere on the slide");
		Move(kVideo); Report("slide show, mouse moves over the video (not playing)");
		Move(kAway); Report("slide show, mouse leaves the video");
		Move(kVideo); Play(view, true); Report("slide show, mouse back over the video, video starts playing");
		Spin(2.5); Report("slide show, playing, mouse rests over the video 2.5 s");
		Move(NSMakePoint(180, 560)); Report("slide show, playing, mouse moves over the video");
		Move(kFooter, 2.5); Report("slide show, playing, mouse rests on the footer 2.5 s");
		Move(kAway); Report("slide show, playing, mouse leaves");
		Cmd(view, "update", false); Spin(0.3); Report("slide show ends under the player (update command)");
		Cmd(view, "hideMediaControl", false); Spin(0.1);

		Cmd(view, "showMediaControl", false); Spin(0.3); Report("editor, new player, mouse elsewhere");
		Move(kVideo); Play(view, false); Spin(2.5); Report("editor, playing, mouse rests over the video 2.5 s");
		Cmd(view, "hideMediaControl", false);
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
	bool IsSelected = true, Mute = true, IsSlideShow = false;
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
	int get_ControlRectX() { return 30; } int get_ControlRectY() { return 140; } int get_ControlRectW() { return 280; } int get_ControlRectH() { return 40; }
};
}
class CCefView { public: bool IsPresentationReporter() { return false; } double GetDeviceScale() { return 1; } void ExecuteInAllFrames(const std::string&) {} };
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

# Qt coordinates (y down) in the media view: video x 10..330, y 10..190; footer x 30..310, y 140..
QT_MAIN = r'''// drives the real QCefView_Media + videoplayerlib QAscVideoView, moving the (offscreen) cursor
#include "x/include/qcefview_media.h"
#include "videoplayerlib/src/qascvideowidget.h"
#include <QApplication>
#include <QCursor>
#include <QElapsedTimer>
#include <cstdio>
static QWidget* g_view;
static std::wstring g_url;
static const QPoint kAway(700, 500), kVideo(170, 50), kFooter(170, 160);
static void Spin(int ms) { QElapsedTimer t; t.start(); while (t.elapsed() < ms) QCoreApplication::processEvents(QEventLoop::AllEvents, 20); }
static QAscVideoView* View() { auto l = g_view->findChildren<QAscVideoView*>(); return l.isEmpty() ? nullptr : l.last(); }
static void Report(const char* label) { QAscVideoView* v = View(); printf("%s|%d\n", label, v ? (int)v->Footer()->isHidden() : -1); fflush(stdout); }
static void Move(QPoint p, int wait = 300) { QCursor::setPos(g_view->mapToGlobal(p)); Spin(wait); }
static void Cmd(QCefView_Media& v, const char* name, bool slideShow) {
	NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = name; c.Url = g_url; c.IsSlideShow = slideShow; v.OnMediaPlayerCommand(&c);
}
static bool g_played = true;
static void Play(QCefView_Media& v, bool slideShow) {
	Cmd(v, "play", slideShow);
	for (int i = 0; i < 50 && View()->m_pInternal->m_bIsPlay; ++i) Spin(100);   // m_bIsPlay: "show the play icon"
	if (View()->m_pInternal->m_bIsPlay) g_played = false;
	Spin(200);
}
int main(int argc, char** argv) {
	qputenv("QT_QPA_PLATFORM", "offscreen");
	QApplication app(argc, argv);
	g_url = QString::fromLocal8Bit(argv[1]).toStdWString();
	QWidget top; top.resize(800, 600); top.move(0, 0);
	CCefView cef; QCefView_Media view(&top); view.m_pCefView = &cef; view.resize(800, 600); g_view = &view;
	top.show(); Spin(100);

	Move(kAway, 0);
	Cmd(view, "showMediaControl", true); Spin(300);
	Report("slide show, player opens, mouse elsewhere on the slide");
	Move(kVideo); Report("slide show, mouse moves over the video (not playing)");
	Move(kAway); Report("slide show, mouse leaves the video");
	Move(kVideo); Play(view, true); Report("slide show, mouse back over the video, video starts playing");
	Spin(2500); Report("slide show, playing, mouse rests over the video 2.5 s");
	Move(QPoint(180, 40)); Report("slide show, playing, mouse moves over the video");
	Move(kFooter, 2500); Report("slide show, playing, mouse rests on the footer 2.5 s");
	Move(kAway); Report("slide show, playing, mouse leaves");
	Cmd(view, "update", false); Spin(300); Report("slide show ends under the player (update command)");
	Cmd(view, "hideMediaControl", false); Spin(100);

	Cmd(view, "showMediaControl", false); Spin(300); Report("editor, new player, mouse elsewhere");
	Move(kVideo); Play(view, false); Spin(2500); Report("editor, playing, mouse rests over the video 2.5 s");
	Cmd(view, "hideMediaControl", false); Spin(100);
	printf("played|%d\n", g_played ? 1 : 0);
	return 0;
}
'''

tmp = tempfile.mkdtemp(prefix='rd1942-')
try:
    if not shutil.which('ffmpeg'):
        raise SystemExit('ffmpeg is needed to make the test video')
    video = os.path.join(tmp, 'clip.mp4')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=duration=10:size=320x180:rate=25',
                    '-pix_fmt', 'yuv420p', '-c:v', 'libx264', video], check=True)

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
        run = subprocess.run(['./probe', video], cwd=lib, capture_output=True, text=True, timeout=120)
        if run.returncode:
            raise SystemExit('macOS probe failed:\n' + run.stdout + run.stderr[-2000:])
        results('AppKit', run.stdout)

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
        run = subprocess.run(['./probe', video], cwd=b, capture_output=True, text=True, timeout=120)
        if run.returncode:
            raise SystemExit('Qt probe failed:\n' + run.stdout + run.stderr[-2000:])
        results('Qt', run.stdout, 'played|1' in run.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('BASELINE run (sources from %s)' % BASE_REF if BASELINE else 'fixed sources')
if failures:
    print('FAILED: %d check(s)' % len(failures))
    sys.exit(1)
print('ALL PASS')

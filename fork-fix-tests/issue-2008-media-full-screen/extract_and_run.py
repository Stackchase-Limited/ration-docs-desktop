#!/usr/bin/env python3
"""
#2008 - Presentation: play a video full screen ("Play Full Screen").

PowerPoint stores it as <p:video fullScrn="1"> (an attribute of the media's time node,
not of its <p:cMediaNode>). It survived open/save, but nothing used it:
  - sdkjs Timing.js getMediaAdditionalData read oPr.fullScrn from the cMediaNode, where it
    never is, so CMediaData.isFullScreen() was always false;
  - desktop-sdk client_renderer_wrapper.cpp CallMediaPlayerCommand read "Fullscreen" while
    sdkjs sends "FullScreen" (no player consumed it either);
  - neither player could fill the screen and come back.

Fix (honours the file's own setting, as #2007 does; no editor option), on #2005's
setMediaFlags command and end-of-media hooks:
  sdkjs  fullScrn read from the CVideo; setMediaFlags flag 4.
  desktop-sdk  macOS (NSPlayerControllerBridge) and Qt (QAscVideoView): with flag 4, in a
         slide show, a video that starts playing fills the slide show view (black around it,
         footer centred at the bottom) and goes back to its slide frame when it ends (a looping
         one stays), is stopped or the slide show ends. Geometry updates while it is full screen
         are kept for the way back. Not in the presenter's window. Renderer key fixed too.

What this runs (REAL code; shared harness ../issue-2002-media-trim/media_c1.py):
  1. the real slide editor (headless Chromium): a PowerPoint deck whose video has
     fullScrn="1" opens with setMediaFlags From 4; the same deck without it, From 0.
  2. macOS: the REAL CCefViewMedia + AppKit player playing a generated 1 s movie in an
     800x600 parent: the video view's frame while playing and after the end, for flag 4 in a
     slide show, flag 4 outside one, no flag, flag 4|1 (loop), a geometry update while full
     screen, and the presenter's window.
  3. Qt 5 (when available): the REAL QCefView_Media + QAscVideoView take the flag (no
     playback offscreen here, so the Qt layout itself is NOT exercised).
NOT claimed: a GUI check in the app (real full-screen slide show window, Retina scaling),
Qt/Linux/Windows playback at runtime, the renderer key fix (not compiled here).

Env: RD_SDKJS, RD_DESKTOP_SDK, RD_CORE, RD_X2T, RD_FONTS, RD_QMAKE, RD_KERNEL_DIR (see
media_c1.py). BASELINE=1 uses SDKJS_BASE_REF / BASE_REF (desktop-sdk), the parents of the
fixes, and MUST FAIL.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'issue-2002-media-trim'))
import media_c1 as h  # noqa: E402

BASELINE = bool(os.environ.get('BASELINE'))
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', 'd1ba4197ba^')
BASE_REF = os.environ.get('BASE_REF', 'f3d90689^')
CBE = h.CBE

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
	bool IsSelected = true, Mute = false, IsSlideShow = false;
	int Volume = -1, From = 0, StartTime = -1, EndTime = -1;
	int X = 10, Y = 10, W = 320, H = 180;
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_Mute() { return Mute; }
	int get_Volume() { return Volume; }
	int get_From() { return From; } bool get_IsSlideShow() { return IsSlideShow; }
	int get_StartTime() { return StartTime; } int get_EndTime() { return EndTime; }
	bool get_Fullscreen() { return false; }
	int get_FrameBoundsX() { return X; } int get_FrameBoundsY() { return Y; }
	int get_FrameBoundsW() { return W; } int get_FrameBoundsH() { return H; }
	int get_ControlRectX() { return X; } int get_ControlRectY() { return Y + H + 10; }
	int get_ControlRectW() { return W; } int get_ControlRectH() { return 40; }
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

MAC_MAIN = r'''// drives the real CCefViewMedia + mac_videoplayer as the editor does in a slide show:
// argv: movie flags slideshow(0/1) reporter(0/1) update(0/1)
// showMediaControl, setMediaFlags (From = flags), play; [at 300 ms an "update" moving the video to 40,40 400x225];
// prints "<label> x,y,w,h footer x,y,w,h" at 500 ms (playing) and 1800 ms (after the 1 s movie ended)
#include "include/mac_cefviewmedia.h"
#include <cstdio>
#include <cstdlib>
#include <string>
static NSView* g_parent;
static NSView* VideoView() {
	for (NSView* v in g_parent.subviews)
		if ([v.layer isKindOfClass:[AVPlayerLayer class]]) return v;
	return nil;
}
static NSView* Footer() { for (NSView* v in g_parent.subviews) if ([v isKindOfClass:NSClassFromString(@"NSFooterPanel")]) return v; return nil; }
static void Spin(double sec) { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:sec]]; }
static void Print(const char* label) {
	NSRect r = VideoView().frame, f = Footer().frame;
	printf("%s %.0f,%.0f,%.0f,%.0f footer %.0f,%.0f,%.0f,%.0f\n", label, r.origin.x, r.origin.y, r.size.width, r.size.height,
		   f.origin.x, f.origin.y, f.size.width, f.size.height);
}
int main(int argc, char** argv) {
	@autoreleasepool {
		[NSApplication sharedApplication];
		std::string path = argv[1];
		std::wstring url(path.begin(), path.end());
		int flags = atoi(argv[2]); bool show = atoi(argv[3]), reporter = atoi(argv[4]), update = atoi(argv[5]);
		g_parent = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 800, 600)];
		CCefView cef; cef.reporter = reporter; CCefViewMedia view(g_parent); view.m_pCefView = &cef;
		auto cmd = [&](const char* name, int from) {
			NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = name; c.Url = url; c.From = from; c.IsSlideShow = show;
			view.OnMediaPlayerCommand(&c);
		};
		cmd("showMediaControl", 0);
		cmd("setMediaFlags", flags);
		Spin(0.5);
		cmd("play", 0);
		Spin(0.3);
		if (update) {
			NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = "update"; c.Url = url; c.IsSlideShow = show;
			c.X = 40; c.Y = 40; c.W = 400; c.H = 225; view.OnMediaPlayerCommand(&c);
		}
		Spin(0.2);
		Print("playing");
		Spin(1.3);
		Print("ended");
		cmd("hideMediaControl", 0);
	}
	return 0;
}
'''


def mac_probe(tmp, ref):
    m = os.path.join(tmp, 'mac')
    h.materialize(h.DESKTOP_SDK, ref, [CBE + '/lib/include/mac_cefviewmedia.h', CBE + '/lib/src/mac_cefviewmedia.mm',
                                       CBE + '/lib/src/mac_videoplayer'], m)
    lib = os.path.join(m, CBE, 'lib')
    open(os.path.join(lib, 'include', 'mac_cefview.h'), 'w').write(MAC_STUB)
    open(os.path.join(lib, 'main.mm'), 'w').write(MAC_MAIN)
    for f in ('NSString+StringUtils.h', 'NSString+StringUtils.mm'):
        shutil.copy(os.path.join(h.CORE, 'DesktopEditor', 'common', 'Mac', f), os.path.join(lib, 'src', 'mac_videoplayer'))
    vp = os.path.join('src', 'mac_videoplayer')
    srcs = ['main.mm', 'src/mac_cefviewmedia.mm'] + [os.path.join(vp, f) for f in sorted(os.listdir(os.path.join(lib, vp))) if f.endswith('.mm')]
    subprocess.run(['clang++', '-std=c++17', '-w', '-I.', '-I' + vp] + srcs +
                   ['-framework', 'Cocoa', '-framework', 'AVFoundation', '-framework', 'CoreMedia',
                    '-framework', 'QuartzCore', '-o', 'probe'], cwd=lib, check=True)
    open(os.path.join(m, 'mkmov.mm'), 'w').write(h.MKMOV)
    subprocess.run(['clang++', '-fobjc-arc', '-w', 'mkmov.mm', '-framework', 'AVFoundation', '-framework', 'CoreMedia',
                    '-framework', 'CoreVideo', '-framework', 'Foundation', '-o', 'mkmov'], cwd=m, check=True)
    movie = os.path.join(m, 'clip1s.mov')
    subprocess.run([os.path.join(m, 'mkmov'), movie], check=True)

    def run(flags, show=1, reporter=0, update=0):
        out = subprocess.run([os.path.join(lib, 'probe'), movie, str(flags), str(show), str(reporter), str(update)],
                             capture_output=True, text=True, check=True).stdout
        res = {}
        for line in out.splitlines():
            label, video, _, footer = line.split()
            res[label] = (video, footer)
        return res
    return run


def full_deck(dst, full):
    """make_deck with a media node, and <p:video fullScrn="1"> when full."""
    tmp = dst + '.base.pptx'
    h.make_deck(tmp, media_node_attrs='fill="hold"')
    zin = zipfile.ZipFile(tmp)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == 'ppt/slides/slide1.xml' and full:
                assert b'<p:video>' in d
                d = d.replace(b'<p:video>', b'<p:video fullScrn="1">', 1)
            zo.writestr(it, d)
    os.remove(tmp)


def main():
    x2t = h.find_x2t(False)
    for p, what in ((x2t, 'x2t'), (h.TEMPLATE, 'pptx template'), (os.path.join(h.FONTS, 'AllFonts.js'), 'fonts cache')):
        if not os.path.exists(p):
            sys.stderr.write('missing %s (%s) - skipping\n' % (what, p))
            sys.exit(77)
    print('BASELINE (%s, %s)' % (SDKJS_BASE_REF, BASE_REF) if BASELINE else 'trees under test')
    tmp = tempfile.mkdtemp(prefix='issue2008-', dir=os.environ.get('RD_TMP'))
    try:
        print('-- sdkjs: the editor')
        tree = h.build_sdkjs(tmp, SDKJS_BASE_REF if BASELINE else None)
        conv = h.setup_x2t(tmp, x2t, tree)
        for full, want in ((True, 4), (False, 0)):
            deck = os.path.join(tmp, 'full%d.pptx' % full)
            full_deck(deck, full)
            b = h.deck_to_bin(conv, tmp, deck, 'b%d' % full)
            res, _ = h.editor(tree, b, tmp, [], 'e%d' % full)
            sent = [p['From'] for p in res['steps'][0]['player'] if p['Cmd'] == 'setMediaFlags']
            print('deck %s fullScrn: setMediaFlags From %s' % ('with' if full else 'without', sent))
            h.check(sent == [want], 'a video %s fullScrn="1": setMediaFlags From %d' % ('with' if full else 'without', want))

        print('-- desktop-sdk macOS: CCefViewMedia + AppKit player (AVPlayer), parent 800x600')
        if sys.platform != 'darwin':
            print('skip (not macOS)')
        else:
            try:
                run = mac_probe(tmp, BASE_REF if BASELINE else None)
            except subprocess.CalledProcessError as e:
                run = None
                print('macOS probe does not build/run: %s' % e)
            h.check(run is not None, 'the macOS player builds with the change')
            if run:
                FULL, SLIDE, MOVED = '0,0,800,600', '10,410,320,180', '40,335,400,225'
                r = run(4)
                print('flag 4, slide show: %s' % r)
                h.check(r['playing'][0] == FULL and r['playing'][1].endswith(',12,320,40') and r['playing'][1].startswith('240,'),
                        'flag 4 in a slide show: the playing video fills the view, footer centred at the bottom')
                h.check(r['ended'] == (SLIDE, '10,360,320,40'), 'and goes back to its slide frame (and footer) when it ends')
                r = run(5)
                print('flags 5 (loop): %s' % r)
                h.check(r['ended'][0] == FULL, 'a looping full screen video stays full screen past its end')
                r = run(4, update=1)
                print('flag 4 + update while full screen: %s' % r)
                h.check(r['playing'][0] == FULL and r['ended'][0] == MOVED, 'a geometry update while full screen applies on the way back')
                for label, kw in (('no flag', dict(flags=0)), ('flag 4 outside a slide show', dict(flags=4, show=0)),
                                  ('flag 4 in the presenter\'s window', dict(flags=4, reporter=1))):
                    r = run(**kw)
                    print('%s: %s' % (label, r))
                    h.check(r['playing'][0] == SLIDE and r['ended'][0] == SLIDE, '%s: the video stays in its frame' % label)

        print('-- desktop-sdk Qt: QCefView_Media + QAscVideoView')
        qt = h.qt_player(tmp, BASE_REF if BASELINE else None, r'"full=%d\n", (int)p->m_bIsPlayFullScreen')
        if qt is not None:
            built, qrun = qt
            h.check(built, 'the Qt player builds with the change')
            if built:
                h.check(qrun(4) == 'full=1' and qrun(3) == 'full=0', 'setMediaFlags sets the view\'s full screen (%s / %s)' % (qrun(4), qrun(3)))
    finally:
        if not os.environ.get('RD_KEEP'):
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print('kept %s' % tmp)
    h.finish('#2008 a fullScrn video fills the slide show while it plays and comes back at its end')


if __name__ == '__main__':
    main()

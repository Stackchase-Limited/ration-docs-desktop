"""
Shared harness for the slide media playback fixes (#2002 trim, #2005 loop, #2006 rewind).
Every piece runs REAL code from the trees under test (or from a BASELINE git ref):

  build_sdkjs()    sdkjs copied (or `git archive`d) and built with its own build/build.py
  setup_x2t()      a clone of x2t next to a DoctRenderer.config that points at that sdkjs
  convert()        x2t (pptx <-> Editor.bin, Editor.bin + changes -> pptx = the desktop's save)
  make_deck()      a one-slide pptx with a video (optional p14:trim, optional media node attributes)
  editor()         editor_rt.js: the real slide editor in headless Chromium (stubbed desktop host)
  mac_player()     the real CCefViewMedia + AppKit player (AVPlayer) driven like the editor drives it,
                   playing a generated 1 s silent H.264 movie; samples (ms, position ms, playing)
  qt_player()      the real QCefView_Media + videoplayerlib built with Qt 5; reports the state the
                   commands leave in QAscVideoView (no playback: QMediaPlayer does not play offscreen here)
  webapps_panel()  the real ImageSettings view code (Playback section) against a stub api
Paths: RD_SDKJS, RD_DESKTOP_SDK, RD_WEBAPPS, RD_CORE, RD_X2T, RD_X2T_FRAMEWORKS, RD_FONTS, RD_QMAKE,
RD_PLAYWRIGHT, RD_CHROME (see each test's docstring).
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
SDKJS = os.environ.get('RD_SDKJS') or os.path.join(ROOT, 'sdkjs')
DESKTOP_SDK = os.environ.get('RD_DESKTOP_SDK') or os.path.join(ROOT, 'desktop-sdk')
WEBAPPS = os.environ.get('RD_WEBAPPS') or os.path.join(ROOT, 'web-apps')
CORE = os.environ.get('RD_CORE') or os.path.join(ROOT, 'core')
PAYLOAD = os.path.normpath(os.path.join(ROOT, '..', '.rd-work', 'payload', 'converter'))
FONTS = os.environ.get('RD_FONTS') or '/Users/osindero/dev/active/rationdocs/.rd-work/fonts-cache'
TEMPLATE = os.path.join(PAYLOAD, 'empty', 'en-US', 'new.pptx')
FMT_PPTX, FMT_BIN = 129, 8195
CBE = 'ChromiumBasedEditors'

failures = []


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        failures.append(what)


def finish(name):
    if failures:
        print('FAIL: %d check(s) failed' % len(failures))
        sys.exit(1)
    print('PASS: ' + name)


def materialize(repo, ref, rels, dest):
    """paths of a repo into dest: from the working tree, or `git archive <ref>`."""
    os.makedirs(dest, exist_ok=True)
    if ref:
        arc = subprocess.run(['git', '-C', repo, 'archive', ref] + rels, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', dest], input=arc, check=True)
        return
    for rel in rels:
        src, dst = os.path.join(repo, rel), os.path.join(dest, rel)
        if os.path.isdir(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if subprocess.run(['cp', '-cR', src, os.path.dirname(dst)], capture_output=True).returncode != 0:
                shutil.copytree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)


def read(repo, rel, ref):
    if ref:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)], capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


# ------------------------------------------------------------------------------------------- sdkjs + x2t
def build_sdkjs(tmp, ref=None):
    tree = os.path.join(tmp, 'sdkjs')
    if ref:
        materialize(SDKJS, ref, [], tree)
    else:
        os.makedirs(tree)
        for name in os.listdir(SDKJS):
            if name in ('.git', 'deploy', 'develop'):
                continue
            src = os.path.join(SDKJS, name)
            if name == 'build':
                os.makedirs(os.path.join(tree, 'build'))
                for f in os.listdir(src):
                    if f != 'node_modules' and os.path.isfile(os.path.join(src, f)):
                        shutil.copy(os.path.join(src, f), os.path.join(tree, 'build', f))
                continue
            if subprocess.run(['cp', '-cR', src, tree], capture_output=True).returncode != 0:
                (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(tree, name))
    r = subprocess.run([sys.executable, 'build.py', '--beta=false', '--minimize', '--desktop', '--product', 'slide'],
                       cwd=os.path.join(tree, 'build'), capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(os.path.join(tree, 'deploy', 'sdkjs', 'slide', 'sdk-all.js')):
        raise SystemExit('sdkjs build failed:\n' + r.stdout[-2000:] + r.stderr[-2000:])
    return tree


def find_x2t(baseline):
    if baseline:
        return os.environ.get('RD_X2T_BASE') or os.path.join(PAYLOAD, 'x2t')
    return os.environ.get('RD_X2T') or os.path.join(ROOT, 'core', 'build', 'bin', 'mac_arm64', 'x2t')


def x2t_frameworks(x2t):
    if os.environ.get('RD_X2T_FRAMEWORKS'):
        return os.environ['RD_X2T_FRAMEWORKS']
    if os.path.isdir(os.path.join(os.path.dirname(x2t), 'kernel.framework')):
        return os.path.dirname(x2t)
    return os.path.join(ROOT, 'core', 'build', 'lib', 'mac_arm64')


def setup_x2t(tmp, x2t_src, sdkjs_tree):
    """x2t reads DoctRenderer.config from its own directory: a clone of it next to a config for the sdkjs under test."""
    d = os.path.join(tmp, 'conv')
    os.makedirs(d)
    x = os.path.join(d, 'x2t')
    if subprocess.run(['cp', '-c', x2t_src, x], capture_output=True).returncode != 0:
        shutil.copy(x2t_src, x)
    dep = os.path.join(sdkjs_tree, 'deploy', 'sdkjs')
    with open(os.path.join(d, 'DoctRenderer.config'), 'w') as fh:
        fh.write('<Settings><file>%s/common/Native/native.js</file><file>%s/common/Native/jquery_native.js</file>'
                 '<allfonts>%s/AllFonts.js</allfonts><file>%s/vendor/xregexp/xregexp-all-min.js</file>'
                 '<sdkjs>%s</sdkjs></Settings>' % (dep, dep, FONTS, WEBAPPS, dep))
    return {'x2t': x, 'fw': x2t_frameworks(x2t_src), 'tmp': tmp}


def convert(conv, src, dst, fmt, extra=''):
    params = os.path.join(conv['tmp'], 'params.xml')
    with open(params, 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert><m_sFileFrom>%s</m_sFileFrom>'
                 '<m_sFileTo>%s</m_sFileTo><m_nFormatTo>%d</m_nFormatTo><m_sFontDir>%s</m_sFontDir>'
                 '<m_sAllFontsPath>%s/AllFonts.js</m_sAllFontsPath><m_sTempDir>%s</m_sTempDir>%s'
                 '</TaskQueueDataConvert>' % (src, dst, fmt, FONTS, FONTS, conv['tmp'], extra))
    fw = conv['fw']
    env = dict(os.environ, DYLD_FRAMEWORK_PATH=fw, DYLD_LIBRARY_PATH=fw, LD_LIBRARY_PATH=fw)
    r = subprocess.run([conv['x2t'], params], capture_output=True, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(dst):
        raise SystemExit('x2t failed (%d) -> %s\n%s%s' % (r.returncode, dst, r.stdout[-1500:], r.stderr[-1500:]))


def save_with_changes(conv, work, bin_dir, changes_file, name):
    """the desktop's save: Editor.bin + media/ + changes/changes0.json -> pptx (sdkjs in x2t's doctrenderer)."""
    d = os.path.join(work, name)
    os.makedirs(os.path.join(d, 'changes'))
    shutil.copy(os.path.join(bin_dir, 'Editor.bin'), d)
    shutil.copytree(os.path.join(bin_dir, 'media'), os.path.join(d, 'media'))
    shutil.copy(changes_file, os.path.join(d, 'changes', 'changes0.json'))
    out = os.path.join(d, 'out.pptx')
    convert(conv, os.path.join(d, 'Editor.bin'), out, FMT_PPTX, '<m_bFromChanges>true</m_bFromChanges>')
    return out


def make_deck(dst, trim=None, media_node_attrs=None):
    """one slide (the app's own empty template) + a video pic (cNvPr id 4); trim=(st, end) strings adds
    <p14:trim>; media_node_attrs adds PowerPoint's <p:video><p:cMediaNode><p:cTn ...attrs> for it."""
    trim_xml = ''
    if trim:
        trim_xml = '<p14:trim%s%s/>' % ((' st="%s"' % trim[0]) if trim[0] else '', (' end="%s"' % trim[1]) if trim[1] else '')
    pic = ('<p:pic><p:nvPicPr><p:cNvPr id="4" name="clip"><a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr>'
           '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr><a:videoFile r:link="rId13"/><p:extLst>'
           '<p:ext uri="{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}"><p14:media xmlns:p14="http://schemas.microsoft.com/'
           'office/powerpoint/2010/main" r:embed="rId14">' + trim_xml + '</p14:media></p:ext></p:extLst>'
           '</p:nvPr></p:nvPicPr><p:blipFill><a:blip r:embed="rId15"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
           '<p:spPr><a:xfrm><a:off x="1000000" y="1000000"/><a:ext cx="4000000" cy="2250000"/></a:xfrm>'
           '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
    timing = ''
    if media_node_attrs is not None:
        timing = ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
                  '<p:video><p:cMediaNode vol="80000"><p:cTn id="2" %s display="0"><p:stCondLst><p:cond delay="indefinite"/>'
                  '</p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="4"/></p:tgtEl></p:cMediaNode></p:video>'
                  '</p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>') % media_node_attrs
    rels = ('<Relationship Id="rId13" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/video" Target="../media/media1.mp4"/>'
            '<Relationship Id="rId14" Type="http://schemas.microsoft.com/office/2007/relationships/media" Target="../media/media1.mp4"/>'
            '<Relationship Id="rId15" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>')

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00')) + chunk(b'IEND', b''))
    zin = zipfile.ZipFile(TEMPLATE)
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            d = zin.read(it.filename)
            if it.filename == 'ppt/slides/slide1.xml':
                d = d.replace(b'</p:spTree>', pic.encode() + b'</p:spTree>', 1)
                if timing:
                    d = d.replace(b'</p:sld>', timing.encode() + b'</p:sld>', 1)
            elif it.filename == 'ppt/slides/_rels/slide1.xml.rels':
                d = d.replace(b'</Relationships>', rels.encode() + b'</Relationships>', 1)
            elif it.filename == '[Content_Types].xml':
                d = d.replace(b'</Types>', b'<Default Extension="mp4" ContentType="video/mp4"/>'
                              b'<Default Extension="png" ContentType="image/png"/></Types>', 1)
            zo.writestr(it, d)
        zo.writestr('ppt/media/media1.mp4', b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 64)
        zo.writestr('ppt/media/image1.png', png)


def deck_to_bin(conv, work, deck, name):
    d = os.path.join(work, name)
    os.makedirs(d)
    convert(conv, deck, os.path.join(d, 'Editor.bin'), FMT_BIN)
    return d


def slide_xml(pptx, n=1):
    return zipfile.ZipFile(pptx).read('ppt/slides/slide%d.xml' % n).decode('utf-8')


def media_cTn(xml):
    """attributes of the <p:cTn> of the slide's <p:video> media node, or None."""
    m = re.search(r'<p:video>\s*<p:cMediaNode[^>]*>\s*<p:cTn\b([^>]*)>', xml)
    return dict(re.findall(r'(\w+)="([^"]*)"', m.group(1))) if m else None


def editor(sdkjs_tree, bin_dir, work, settings=None, name='editor'):
    out = os.path.join(work, name + '-changes0.json')
    args = ['node', os.path.join(HERE, 'editor_rt.js'), sdkjs_tree, os.path.join(bin_dir, 'Editor.bin'),
            os.path.join(FONTS, 'AllFonts.js'), out]
    if settings is not None:
        args.append(json.dumps(settings))
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit('editor harness failed:\n' + r.stdout[-2000:] + r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1]), out


# ------------------------------------------------------------------------------------------- players
MKMOV = r'''// a 1 s, 10 fps, 64x64 H.264 .mov without audio (AVAssetWriter)
#import <AVFoundation/AVFoundation.h>
int main(int argc, char** argv) {
	@autoreleasepool {
		NSURL* url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[1]]];
		[[NSFileManager defaultManager] removeItemAtURL:url error:nil];
		AVAssetWriter* w = [AVAssetWriter assetWriterWithURL:url fileType:AVFileTypeQuickTimeMovie error:nil];
		AVAssetWriterInput* in = [AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeVideo
			outputSettings:@{AVVideoCodecKey: AVVideoCodecTypeH264, AVVideoWidthKey: @64, AVVideoHeightKey: @64}];
		AVAssetWriterInputPixelBufferAdaptor* ad = [AVAssetWriterInputPixelBufferAdaptor assetWriterInputPixelBufferAdaptorWithAssetWriterInput:in
			sourcePixelBufferAttributes:@{(id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA), (id)kCVPixelBufferWidthKey: @64, (id)kCVPixelBufferHeightKey: @64}];
		[w addInput:in]; [w startWriting]; [w startSessionAtSourceTime:kCMTimeZero];
		for (int i = 0; i < 10; ++i) {
			while (!in.readyForMoreMediaData) [NSThread sleepForTimeInterval:0.01];
			CVPixelBufferRef pb = NULL;
			CVPixelBufferPoolCreatePixelBuffer(NULL, ad.pixelBufferPool, &pb);
			CVPixelBufferLockBaseAddress(pb, 0);
			memset(CVPixelBufferGetBaseAddress(pb), (i * 25) & 0xff, CVPixelBufferGetDataSize(pb));
			CVPixelBufferUnlockBaseAddress(pb, 0);
			[ad appendPixelBuffer:pb withPresentationTime:CMTimeMake(i, 10)];
			CVPixelBufferRelease(pb);
		}
		[in markAsFinished];
		[w endSessionAtSourceTime:CMTimeMake(10, 10)];
		__block bool done = false;
		[w finishWritingWithCompletionHandler:^{ done = true; }];
		while (!done) [NSThread sleepForTimeInterval:0.01];
		return w.status == AVAssetWriterStatusCompleted ? 0 : 1;
	}
}
'''

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
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_Mute() { return Mute; }
	int get_Volume() { return Volume; }
	int get_From() { return From; } bool get_IsSlideShow() { return IsSlideShow; }
	int get_StartTime() { return StartTime; } int get_EndTime() { return EndTime; }
	bool get_Fullscreen() { return false; }
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

MAC_MAIN = r'''// drives the real CCefViewMedia + mac_videoplayer (AVPlayer) as the editor does: showMediaControl,
// setMediaFlags (flags argv[2] in From, trim argv[3]/argv[4] ms in StartTime/EndTime), play; then prints
// "<ms since play>:<position ms>:<playing>" every 100 ms for 2.6 s
#include "include/mac_cefviewmedia.h"
#include <cstdio>
#include <cstdlib>
#include <string>
static NSView* g_parent;
static AVPlayer* Player() {
	for (NSView* v in g_parent.subviews)
		if ([v.layer isKindOfClass:[AVPlayerLayer class]]) return ((AVPlayerLayer*)v.layer).player;
	return nil;
}
static void Spin(double sec) { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:sec]]; }
int main(int argc, char** argv) {
	@autoreleasepool {
		[NSApplication sharedApplication];
		std::string path = argv[1];
		std::wstring url(path.begin(), path.end());
		int flags = atoi(argv[2]), st = atoi(argv[3]), end = atoi(argv[4]);
		g_parent = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 800, 600)];
		CCefView cef; CCefViewMedia view(g_parent); view.m_pCefView = &cef;
		const char* cmds[] = { "showMediaControl", "setMediaFlags" };
		for (const char* name : cmds) {
			NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = name; c.Url = url; c.StartTime = st; c.EndTime = end;
			c.From = (std::string(name) == "setMediaFlags") ? flags : 0;
			view.OnMediaPlayerCommand(&c);
		}
		Spin(0.5);
		{ NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = "play"; c.Url = url; view.OnMediaPlayerCommand(&c); }
		for (int i = 0; i < 26; ++i) {
			Spin(0.1);
			AVPlayer* p = Player();
			printf("%d:%.0f:%d\n", (i + 1) * 100, CMTimeGetSeconds(p.currentTime) * 1000, p.rate > 0 ? 1 : 0);
		}
		NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = "hideMediaControl"; view.OnMediaPlayerCommand(&c);
	}
	return 0;
}
'''


class MacPlayer:
    """build once (tree or ref), run scenarios."""

    def __init__(self, tmp, ref=None):
        self.ok = sys.platform == 'darwin'
        if not self.ok:
            return
        m = os.path.join(tmp, 'mac')
        materialize(DESKTOP_SDK, ref, [CBE + '/lib/include/mac_cefviewmedia.h', CBE + '/lib/src/mac_cefviewmedia.mm',
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
        open(os.path.join(m, 'mkmov.mm'), 'w').write(MKMOV)
        subprocess.run(['clang++', '-fobjc-arc', '-w', 'mkmov.mm', '-framework', 'AVFoundation', '-framework', 'CoreMedia',
                        '-framework', 'CoreVideo', '-framework', 'Foundation', '-o', 'mkmov'], cwd=m, check=True)
        self.movie = os.path.join(m, 'clip1s.mov')
        subprocess.run([os.path.join(m, 'mkmov'), self.movie], check=True)
        self.probe = os.path.join(lib, 'probe')

    def run(self, flags, st=-1, end=-1):
        out = subprocess.run([self.probe, self.movie, str(flags), str(st), str(end)], capture_output=True, text=True, check=True).stdout
        return [tuple(int(v) for v in line.split(':')) for line in out.split()]


def at(samples, t):
    """(position ms, playing) at t ms after play."""
    for s in samples:
        if s[0] == t:
            return s[1], s[2]
    return None


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
	int Volume = -1, From = 0, StartTime = -1, EndTime = -1;
	std::string get_Cmd() { return Cmd; }
	std::string get_Theme() { return Theme; }
	std::wstring get_Url() { return Url; }
	bool get_IsSelected() { return IsSelected; }
	bool get_IsSlideShow() { return IsSlideShow; }
	bool get_Mute() { return Mute; }
	bool get_Fullscreen() { return false; } bool get_IsVideo() { return true; } bool get_FlipH() { return false; } bool get_FlipV() { return false; }
	double get_Rotation() { return 0; }
	int get_Volume() { return Volume; }
	int get_StartTime() { return StartTime; } int get_EndTime() { return EndTime; } int get_From() { return From; }
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

QT_MAIN = r'''// drives the real QCefView_Media + QAscVideoView: showMediaControl + setMediaFlags (flags argv[1],
// trim argv[2]/argv[3]) and prints what the view keeps: STATE
#include "x/include/qcefview_media.h"
#include "videoplayerlib/src/qascvideowidget.h"
#include <QApplication>
#include <cstdio>
#include <cstdlib>
int main(int argc, char** argv) {
	qputenv("QT_QPA_PLATFORM", "offscreen");
	QApplication app(argc, argv);
	int flags = atoi(argv[1]), st = atoi(argv[2]), end = atoi(argv[3]);
	QWidget parent; parent.resize(800, 600);
	CCefView cef; QCefView_Media view(&parent); view.m_pCefView = &cef;
	const char* cmds[] = { "showMediaControl", "setMediaFlags" };
	for (const char* name : cmds) {
		NSEditorApi::CAscExternalMediaPlayerCommand c; c.Cmd = name; c.Url = L"/nonexistent/a.mp4"; c.StartTime = st; c.EndTime = end;
		c.From = (std::string(name) == "setMediaFlags") ? flags : 0;
		view.OnMediaPlayerCommand(&c);
	}
	QAscVideoView* v = parent.findChildren<QAscVideoView*>().last();
	QAscVideoView_Private* p = v->m_pInternal;
	printf(STATE);
	return 0;
}
'''


def qt_player(tmp, ref, state_fmt):
    """None when Qt 5 / kernel are missing; else (built, stdout). state_fmt: printf args using p (Private)."""
    qmake = os.environ.get('RD_QMAKE') or ('/opt/homebrew/opt/qt@5/bin/qmake' if os.path.exists('/opt/homebrew/opt/qt@5/bin/qmake') else shutil.which('qmake'))
    qver = subprocess.run([qmake, '-query', 'QT_VERSION'], capture_output=True, text=True).stdout.strip() if qmake else ''
    kdir = os.environ.get('RD_KERNEL_DIR') or PAYLOAD
    if sys.platform == 'darwin':
        have_kernel = os.path.isdir(os.path.join(kdir, 'kernel.framework'))
        kernel_libs = '-F%s -framework kernel -Wl,-rpath,%s' % (kdir, kdir)
    else:
        have_kernel = os.path.exists(os.path.join(kdir, 'libkernel.so'))
        kernel_libs = '-L%s -lkernel -Wl,-rpath,%s' % (kdir, kdir)
    if not qver.startswith('5.') or not have_kernel:
        print('skip Qt (needs Qt 5 qmake [%s] and the core kernel library in %s)' % (qver or 'none', kdir))
        return None
    q = os.path.join(tmp, 'qt')
    materialize(DESKTOP_SDK, ref, [CBE + '/videoplayerlib', CBE + '/lib/qt_wrapper/include/qcefview_media.h',
                                   CBE + '/lib/qt_wrapper/src/qcefview_media.cpp'], q)
    b = os.path.join(q, 'b')
    os.makedirs(os.path.join(b, 'x', 'y'))
    shutil.move(os.path.join(q, CBE, 'videoplayerlib'), os.path.join(b, 'x', 'y', 'videoplayerlib'))
    os.symlink('x/y/videoplayerlib', os.path.join(b, 'videoplayerlib'))
    shutil.move(os.path.join(q, CBE, 'lib', 'qt_wrapper', 'include'), os.path.join(b, 'x', 'include'))
    shutil.move(os.path.join(q, CBE, 'lib', 'qt_wrapper', 'src'), os.path.join(b, 'x', 'src'))
    os.symlink(CORE, os.path.join(b, 'core'))
    open(os.path.join(b, 'x', 'include', 'qcefview.h'), 'w').write(QT_STUB)
    open(os.path.join(b, 'main.cpp'), 'w').write(QT_MAIN.replace('STATE', state_fmt))
    V = 'videoplayerlib/src/'
    open(os.path.join(b, 'probe.pro'), 'w').write('\n'.join([
        'QT += core gui printsupport widgets multimedia multimediawidgets',
        'CONFIG += c++17 console sdk_no_version_check', 'CONFIG -= app_bundle', 'TARGET = probe',
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
    mk = subprocess.run(['make', '-j2'], cwd=b, capture_output=True, text=True)
    if mk.returncode:
        errs = [l for l in (mk.stdout + mk.stderr).splitlines() if 'error' in l]
        print('Qt probe does not build: %s' % (errs[:3],))
        return (False, '')

    def run(flags, st=-1, end=-1):
        return subprocess.run([os.path.join(b, 'probe'), str(flags), str(st), str(end)], cwd=b,
                              capture_output=True, text=True, check=True).stdout.strip()
    return (True, run)


# ------------------------------------------------------------------------------------------- web-apps
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


def webapps_panel(ref, controls, media, events):
    """Run the REAL Playback part of PE.Views.ImageSettings (the media block of ChangeSettings and the
    change handlers) against stubs. controls: {'chLoop': 'checkbox'|'spinner'}; events: list of
    [handler, name, value]. Returns {'template': text, 'values': {...}, 'calls': [...]} or None."""
    view = read(WEBAPPS, 'apps/presentationeditor/main/app/view/ImageSettings.js', ref)
    tmpl = read(WEBAPPS, 'apps/presentationeditor/main/app/template/ImageSettings.template', ref)
    start = view.find('var media = this.api.asc_getMediaSettings')
    stop = view.find('var transparency = props.asc_getTransparent();', start)
    if start < 0 or stop < 0:
        return None
    media_part = view[start:stop]
    handlers = {}
    for h in ('onMediaSettingChange', 'onMediaTrimChange'):
        at = view.find(h + ': function')
        if at >= 0:
            body = brace_match(view, at)
            handlers[h] = body[body.index('function'):]
    js = r"""
const calls = [];
// every other control of the panel (whatever the tree has) is a stub that remembers its value
const ctl = () => ({ v: null, setValue(v) { this.v = v; }, getValue() { return this.v ? 'checked' : 'unchecked'; }, getNumberValue() { return this.v; } });
const me = new Proxy({ api: { asc_getMediaSettings: () => me.media, asc_setMediaSettings: s => calls.push(s) },
    fireEvent: () => {}, PlaybackTable: { hidden: null, toggleClass(c, v) { this.hidden = v; } } },
    { get(t, k) { if (!(k in t) && typeof k === 'string' && /^(ch|num)[A-Z]/.test(k)) t[k] = ctl(); return t[k]; } });
@HANDLERS@
me.apply = function () { @MEDIA@ };
me.media = @MEDIA_JSON@; me.apply();
const values = {}; for (const c of @CONTROLS@) values[c] = me[c].v;
for (const [h, name, value] of @EVENTS@) { if (!me[h]) { calls.push('no handler ' + h); continue; } me[h](name, { getValue: () => value ? 'checked' : 'unchecked', getNumberValue: () => value }); }
process.stdout.write(JSON.stringify({ values, calls }));
"""
    js = (js.replace('@MEDIA@', media_part).replace('@MEDIA_JSON@', json.dumps(media))
          .replace('@CONTROLS@', json.dumps(list(controls))).replace('@EVENTS@', json.dumps(events))
          .replace('@HANDLERS@', '\n'.join('me.%s = %s;' % (k, v) for k, v in handlers.items())))
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True)
    if r.returncode:
        return {'template': tmpl, 'error': r.stderr[-1500:]}
    res = json.loads(r.stdout)
    res['template'] = tmpl
    return res

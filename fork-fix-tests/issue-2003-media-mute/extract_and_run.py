#!/usr/bin/env python3
"""
#2003 - Presentation: an option to play a video (or audio) muted.

PowerPoint keeps it in the slide timing: <p:video><p:cMediaNode mute="1">.
We already kept it through open/save (x2t and the sdkjs model, checked with a
python-pptx deck: pptx -> Editor.bin -> sdkjs -> Editor.bin -> pptx) and the
desktop players honour it (#1922), but nothing in the editor could set it - a
video inserted here has no media node at all.

What was added:
1. sdkjs (slide/Editor/Format/Timing.js, Presentation.js, api.js):
   CTiming.getMediaNode / checkMediaNode (adds <p:video|p:audio><p:cMediaNode>
   <p:cTn fill="hold" display="0"><p:stCondLst><p:cond delay="indefinite"/>
   ...<p:tgtEl><p:spTgt spid=".."/> as PowerPoint writes it) / getMediaSettings
   / setMediaSettings; CPresentation.GetSelectedMedia / Get/SetSelectedMedia-
   Settings; api asc_getMediaSettings() / asc_setMediaSettings({"Mute": b}),
   which reopens the selected video's player so it picks the setting up.
2. web-apps: image settings panel > Playback > Mute (only for video/audio).
3. desktop-sdk: the players remembered the volume last left in a player of a
   media file (#1922) and preferred it to the media's own setting, so a Mute
   ticked in the editor after the video had been selected once (it always has:
   selecting it is how the panel is reached) was ignored for the rest of the
   session. A remembered volume now only stands while the media's own setting
   (mute, volume) is the one it was left under (mac_cefviewmedia.mm,
   qcefview_media.cpp; state kept in the .mm/.cpp, no class layout change).

Measured by hand in the real slide editor (headless Chromium,
.rd-work/wt/eb-tmp/h/rt.js) on a deck without media nodes: asc_getMediaSettings
{"Mute":false} -> asc_setMediaSettings({"Mute":true}) -> the player is sent
hideMediaControl, showMediaControl Mute=true; saved and converted by x2t:
<p:video><p:cMediaNode mute="1"><p:cTn id="2" fill="hold" display="0">
<p:stCondLst><p:cond delay="indefinite"/>...<p:spTgt spid=".."/>.

What this runs (real code, small stubs):
  1. node: the REAL sdkjs functions above against stub timing nodes / slide.
  2. web-apps: the REAL ImageSettings onMediaSettingChange + the media part of
     ChangeSettings against a stub api and checkbox; the template has the box.
  3. macOS: the REAL CCefViewMedia + AppKit player (AVPlayer) built with clang++
     (as #1922's test); 4. Qt 5 (optional): the REAL QCefView_Media +
     videoplayerlib, offscreen. Scenario: the user leaves a video at 30 %, it is
     reopened (30 %), the editor's Mute is ticked (muted), reopened (muted), Mute
     unticked (player default again).
NOT claimed: the web-apps panel rendered in the real editor (needs a GUI
check); audible output; VLC builds.

Env: RD_REPO (desktop-sdk, default ../../desktop-sdk), RD_SDKJS (../../sdkjs),
RD_WEBAPPS (../../web-apps), RD_CORE (../../core), RD_QMAKE, RD_KERNEL_DIR as in
issue-1922. BASELINE=1 reads the sources at BASE_REF / SDKJS_BASE_REF /
WEBAPPS_BASE_REF (the parents of the fixes) and must FAIL.
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
BASE_REF = os.environ.get('BASE_REF', 'b4273817^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '3d36688e80^')
WEBAPPS = os.environ.get('RD_WEBAPPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'web-apps'))
WEBAPPS_BASE_REF = os.environ.get('WEBAPPS_BASE_REF', '28c61dfec1^')
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
print('-- sdkjs: Mute set from the editor, stored as PowerPoint does')
timing = read(SDKJS, 'slide/Editor/Format/Timing.js', SDKJS_BASE_REF)
pres = read(SDKJS, 'slide/Editor/Format/Presentation.js', SDKJS_BASE_REF)
api = read(SDKJS, 'slide/api.js', SDKJS_BASE_REF)
parts = [extract(timing, a, optional=True) for a in (
    'CTiming.prototype.getMediaNode = function', 'CTiming.prototype.checkMediaNode = function',
    'function getMediaSettings(', 'CTiming.prototype.getMediaSettings = function',
    'CTiming.prototype.setMediaSettings = function')]
parts += [extract(pres, a, optional=True) for a in (
    'CPresentation.prototype.GetSelectedMedia = function', 'CPresentation.prototype.GetSelectedMediaSettings = function',
    'CPresentation.prototype.SetSelectedMediaSettings = function')]
parts += [extract(api, a, optional=True) for a in (
    'asc_docs_api.prototype.asc_getMediaSettings = function', 'asc_docs_api.prototype.asc_setMediaSettings = function')]
missing = sum(p is None for p in parts)
check(missing == 0, 'the media settings API exists in sdkjs (%d of %d functions missing)' % (missing, len(parts)))
if missing == 0:
    JS = r"""
const log = [];
const NODE_FILL_HOLD = 1;
const AscCommon = { changestype_Timing: 7 };
function Obj(kind) { this.kind = kind; }
Obj.prototype.isVideo = function () { return this.kind === 'video'; };
Obj.prototype.isAudio = function () { return this.kind === 'audio'; };
function CVideo() { Obj.call(this, 'video'); } CVideo.prototype = Object.create(Obj.prototype);
function CAudio() { Obj.call(this, 'audio'); } CAudio.prototype = Object.create(Obj.prototype);
CVideo.prototype.setCMediaNode = CAudio.prototype.setCMediaNode = function (p) { this.cMediaNode = p; };
function CCMediaNode() { this.mute = null; }
CCMediaNode.prototype.setCTn = function (p) { this.cTn = p; };
CCMediaNode.prototype.setTgtEl = function (p) { this.tgtEl = p; };
CCMediaNode.prototype.setMute = function (p) { this.mute = p; };
CCMediaNode.prototype.getTargetObjectId = function () { return this.tgtEl && this.tgtEl.spTgt && this.tgtEl.spTgt.spid; };
function CTgtEl() {} CTgtEl.prototype.setSpTgt = function (p) { this.spTgt = p; };
function CSpTgt() {} CSpTgt.prototype.setSpid = function (p) { this.spid = p; };
function CTiming() { this.children = []; }
CTiming.prototype.createCCTn = function (dur, fill, delay, type, restart, childLst) {
    return { dur, fill, delay, type, restart, childLst, setDisplay(v) { this.display = v; } };
};
CTiming.prototype.getTimingRootNode = function () {
    const ch = this.children;
    return { traverseTimeNodes(cb) { for (const n of ch) if (cb(n)) return true; return false; } };
};
CTiming.prototype.checkTimeRoot = function () { const ch = this.children; return { pushToChildTnLst(n) { ch.push(n); } }; };
CTiming.prototype.updateNodesIDs = function () { log.push('ids'); };
const AscFormat = { CTiming };
@TIMING@
AscFormat.getMediaSettings = getMediaSettings;
function Drawing(id, video) { this.id = id; this.video = video; }
Drawing.prototype.Get_Id = function () { return this.id; };
Drawing.prototype.isVideo = function () { return this.video; };
Drawing.prototype.getMediaFileName = function () { return this.video === null ? null : this.id + '.mp4'; };
const slide = { timing: null, setTiming(t) { this.timing = t; }, graphicObjects: { sel: [], getSelectedArray() { return this.sel; },
    checkShowMediaControlOnSelect() { log.push('show ' + (this.sel[0] && this.sel[0].id)); } } };
function CPresentation() { this.locked = false; }
CPresentation.prototype.GetCurrentSlide = function () { return slide; };
CPresentation.prototype.IsSelectionLocked = function () { return this.locked; };
CPresentation.prototype.StartAction = function () { log.push('start'); };
CPresentation.prototype.FinalizeAction = function () { log.push('finalize'); };
CPresentation.prototype.Document_UpdateInterfaceState = function () {};
@PRES@
const pres = new CPresentation();
function asc_docs_api() { this.WordControl = { m_oLogicDocument: pres }; }
asc_docs_api.prototype.hideMediaControl = function () { log.push('hide'); };
@API@
const api = new asc_docs_api();
const out = {};
const video = new Drawing('v1', true), audio = new Drawing('a1', false), pic = new Drawing('p1', null);
slide.graphicObjects.sel = [pic];
const mute = s => s && { 'Mute': s['Mute'] };
out.picture = api.asc_getMediaSettings();
slide.graphicObjects.sel = [video];
out.before = mute(api.asc_getMediaSettings());
log.length = 0;
api.asc_setMediaSettings({ 'Mute': true });
out.log = log.slice();
out.after = mute(api.asc_getMediaSettings());
const node = slide.timing.children[0];
out.node = node && { kind: node.kind, mute: node.cMediaNode.mute, spid: node.cMediaNode.getTargetObjectId(),
    fill: node.cMediaNode.cTn.fill, delay: node.cMediaNode.cTn.delay, display: node.cMediaNode.cTn.display,
    childLst: node.cMediaNode.cTn.childLst };
api.asc_setMediaSettings({ 'Mute': false });
out.unmuted = mute(api.asc_getMediaSettings());
out.nodes = slide.timing.children.length;
slide.graphicObjects.sel = [audio];
api.asc_setMediaSettings({ 'Mute': true });
out.audio = slide.timing.children.map(n => n.kind + ':' + n.cMediaNode.getTargetObjectId() + ':' + n.cMediaNode.mute);
pres.locked = true;
slide.graphicObjects.sel = [video];
api.asc_setMediaSettings({ 'Mute': true });
out.locked = mute(api.asc_getMediaSettings());
process.stdout.write(JSON.stringify(out));
"""
    JS = (JS.replace('@TIMING@', ';\n'.join(parts[0:5]) + ';')
            .replace('@PRES@', ';\n'.join(parts[5:8]) + ';').replace('@API@', ';\n'.join(parts[8:10]) + ';'))
    node = subprocess.run(['node', '-e', JS], capture_output=True, text=True)
    if node.returncode:
        raise SystemExit('node failed:\n' + node.stderr[-2000:])
    res = json.loads(node.stdout)
    check(res['picture'] is None, 'a picture selected -> no media settings (got %s)' % res['picture'])
    check(res['before'] == {'Mute': False}, 'a video without a media node -> Mute false (got %s)' % res['before'])
    check(res['after'] == {'Mute': True}, 'Mute set -> Mute true (got %s)' % res['after'])
    check(res['node'] == {'kind': 'video', 'mute': True, 'spid': 'v1', 'fill': 1, 'delay': 'indefinite', 'display': False, 'childLst': False},
          'the new node is PowerPoint\'s <p:video><p:cMediaNode mute="1"><p:cTn fill="hold" display="0"> delay="indefinite", spTgt v1 (got %s)' % res['node'])
    check(res['log'] == ['start', 'ids', 'finalize', 'hide', 'show v1'],
          'one action, ids renumbered, then the player is reopened (got %s)' % res['log'])
    check(res['unmuted'] == {'Mute': False} and res['nodes'] == 1, 'Mute cleared on the same node (got %s, %s nodes)' % (res['unmuted'], res['nodes']))
    check(res['audio'] == ['video:v1:false', 'audio:a1:true'], 'an audio gets a <p:audio> node (got %s)' % res['audio'])
    check(res['locked'] == {'Mute': False}, 'a locked timing is not changed (got %s)' % res['locked'])

# ---------------------------------------------------------------------------------------------
print('-- web-apps: image settings > Playback > Mute')
view = read(WEBAPPS, 'apps/presentationeditor/main/app/view/ImageSettings.js', WEBAPPS_BASE_REF)
tmpl = read(WEBAPPS, 'apps/presentationeditor/main/app/template/ImageSettings.template', WEBAPPS_BASE_REF)
check('id="image-checkbox-mute"' in tmpl and 'id="image-table-playback"' in tmpl, 'the panel template has the Playback table and the Mute box')
change = extract(view, 'onMediaSettingChange: function', optional=True)
media_part = between(view, 'var media = this.api.asc_getMediaSettings', 'var transparency = props.asc_getTransparent();') \
    if 'var media = this.api.asc_getMediaSettings' in view else None
check(change is not None and media_part is not None, 'the view reads and writes the setting')
if change and media_part:
    JS = r"""
const calls = [];
const me = { api: { asc_getMediaSettings: () => me.media, asc_setMediaSettings: s => calls.push(s) },
    fireEvent: () => {}, PlaybackTable: { hidden: null, toggleClass(c, v) { this.hidden = v; } },
    chMute: { v: null, setValue(v) { this.v = v; } }, chHideStopped: { setValue() {} } };
me.onMediaSettingChange = function @CHANGE@;
me.apply = function () { @MEDIA@ };
const out = {};
me.media = null; me.apply(); out.picture = me.PlaybackTable.hidden;
me.media = { 'Mute': true }; me.apply(); out.video = [me.PlaybackTable.hidden, me.chMute.v];
me.onMediaSettingChange('Mute', { getValue: () => 'checked' });
me.onMediaSettingChange('Mute', { getValue: () => 'unchecked' });
out.calls = calls;
process.stdout.write(JSON.stringify(out));
"""
    JS = JS.replace('@CHANGE@', change[change.index('('):]).replace('@MEDIA@', media_part)
    node = subprocess.run(['node', '-e', JS], capture_output=True, text=True)
    if node.returncode:
        raise SystemExit('node failed:\n' + node.stderr[-2000:])
    res = json.loads(node.stdout)
    check(res['picture'] is True, 'hidden for a picture')
    check(res['video'] == [False, True], 'shown for a muted video, box ticked (got %s)' % res['video'])
    check(res['calls'] == [{'Mute': True}, {'Mute': False}], 'ticking/unticking sends Mute true/false (got %s)' % res['calls'])

# ---------------------------------------------------------------------------------------------
# the volume after each step (same in both drivers)
LABELS = ['no media setting (player default)', 'user moves the slider to 30%', 'deselected and selected again',
          'Mute ticked in the editor, player reopened', 'selected again (still muted)', 'Mute unticked (media default again)']

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
	int get_From() { return 0; } bool get_IsSlideShow() { return false; }
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
static float Vol() {
	for (NSView* v in g_parent.subviews)
		if ([v.layer isKindOfClass:[AVPlayerLayer class]]) return ((AVPlayerLayer*)v.layer).player.volume;
	return -1;
}
static NSSlider* VolumeSlider(NSView* root) {
	NSSlider* found = nil;
	for (NSView* v in root.subviews) {
		if ([v isKindOfClass:[NSSlider class]] && ((NSSlider*)v).isVertical) found = (NSSlider*)v;
		NSSlider* s = VolumeSlider(v); if (s) found = s;
	}
	return found;
}
static void Drag(double part) {
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
		Show(view, L"/nonexistent/c.mp4", false, -1); printf("%.2f\n", Vol());
		Drag(0.3); printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/c.mp4", false, -1); printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/c.mp4", true, -1); printf("%.2f\n", Vol()); Hide(view);
		Show(view, L"/nonexistent/c.mp4", true, -1); printf("%.2f\n", Vol()); Hide(view);
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
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol());
	View()->ChangeVolume(30); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/c.mp4", true, -1); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/c.mp4", true, -1); printf("%d\n", Vol()); Hide(view);
	Show(view, L"/nonexistent/c.mp4", false, -1); printf("%d\n", Vol()); Hide(view);
	return 0;
}
'''

def player_checks(name, got, expected):
    if len(got) < len(expected):
        check(False, '%s: the driver printed %d of %d values: %s' % (name, len(got), len(expected), got))
        return
    for label, g, e in zip(LABELS, got, expected):
        check(g == e, '%s: %s -> volume %s (got %s)' % (name, label, e, g))


tmp = tempfile.mkdtemp(prefix='rd2003-')
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
                      [1.0, 0.3, 0.3, 0.0, 0.0, 1.0])

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
                      [50, 30, 30, 0, 0, 50])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('BASELINE run (sources from %s / %s / %s)' % (BASE_REF, SDKJS_BASE_REF, WEBAPPS_BASE_REF) if BASELINE else 'fixed sources')
if failures:
    print('FAILED: %d check(s)' % len(failures))
    sys.exit(1)
print('ALL PASS')

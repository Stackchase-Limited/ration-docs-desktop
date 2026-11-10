#!/usr/bin/env python3
"""
#1491 - during a slide show, a video on the slide swallowed the keys that change
slides (Linux/Windows, the Qt media player).

Clicking the video gives the Qt player (QAscVideoView) the keyboard, and its
keyPressEvent scrubbed on Left/Right, paused on Space, stopped on Escape and
accepted every key, so nothing reached the presentation: the presenter could not
go on, go back or end the show without the mouse. The player emitted onKeyDown,
but QCefView_Media's connection to onMediaKeyDown was commented out and the slot
was an empty stub. Nothing in the player data said whether a show was running.

Fix: sdkjs adds IsSlideShow to the player data (CMediaData.getPlayerData), the
CEF IPC carries it to CAscExternalMediaPlayerCommand, QCefView_Media sets the
view's slide-show mode from it and connects onKeyDown. In a slide show
keyPressEvent keeps only M (mute) and hands every key on; onMediaKeyDown maps the
Qt key to the browser keyCode and runs DemonstrationManager.onKeyDown in the
editor (guarded by isSlideShow()), then gives the keyboard back to the editor.

What this runs (real code, extracted by brace matching, against small stubs):
  1. C++: QAscVideoView::keyPressEvent (qascvideoview.cpp), GetEditorKeyCode and
     QCefView_Media::onMediaKeyDown (qcefview_media.cpp), compiled with the
     host C++ compiler against stubs that record what the player does and the
     JS handed to CEF. Checked: in a slide show no key scrubs/pauses/stops and
     each navigation key produces JS; in the editor Left/Right still scrub,
     Space pauses, Escape stops, and no JS is sent. Also checked: the
     onKeyDown -> onMediaKeyDown connection is live (not commented out).
  2. JS (node): the generated JS runs against a stub editor whose
     DemonstrationManager.onKeyDown is the REAL onKeyDown/onKeyDownCode from
     sdkjs slide/Drawing/Transitions.js and whose key object comes from the REAL
     AscCommon.getKeyboardEventObject (common/text_input2.js); slide moves are
     recorded. Right/Down/PageDown/Space/Enter -> next, Left/Up/PageUp -> prev,
     Home/End -> first/last, Escape -> end; nothing happens outside a show.
  3. JS (node): the REAL CMediaData.prototype.getPlayerData (common/Drawings/
     Format/Image.js) reports IsSlideShow true in a show, false while editing.

NOT claimed: a real slide show with a playing video on Linux/Windows was not run
(needs a full Qt+CEF desktop build); the CEF IPC hop (renderer argument 22 ->
cefview.cpp) was only compile-checked; presenter view (reporter) not exercised.
N, P and Backspace reach the slide show but this tree's slide show has no
binding for them (same as without a video). macOS is unaffected: it uses the
AppKit player (lib/src/mac_videoplayer), whose views never take first responder.

Env:
  RD_REPO     desktop-sdk checkout (default ../../desktop-sdk)
  RD_SDKJS    sdkjs checkout (default ../../sdkjs)
  BASELINE=1  read desktop-sdk sources from BASE_REF and sdkjs Image.js from
              SDKJS_BASE_REF (the parents of the fix commits): must FAIL.
  CXX         C++ compiler (default c++)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
SDKJS = os.environ.get('RD_SDKJS') or os.path.normpath(os.path.join(HERE, '..', '..', 'sdkjs'))
BASE_REF = os.environ.get('BASE_REF', '33fa495f^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', 'eb97eb93a8^')
BASELINE = bool(os.environ.get('BASELINE'))

VIEW = 'ChromiumBasedEditors/videoplayerlib/src/qascvideoview.cpp'
MEDIA = 'ChromiumBasedEditors/lib/qt_wrapper/src/qcefview_media.cpp'


def read(repo, rel, ref):
    if BASELINE:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


def read_current(repo, rel):
    # sdkjs sources the fix did not touch: always the working tree
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


# ---------------------------------------------------------------- C++ part
view_src = read(REPO, VIEW, BASE_REF)
media_src = read(REPO, MEDIA, BASE_REF)
key_press = extract(view_src, 'void QAscVideoView::keyPressEvent(QKeyEvent *event)', ('stepForward', 'onKeyDown'))
on_key = extract(media_src, 'void QCefView_Media::onMediaKeyDown(int key, Qt::KeyboardModifiers mods)')
key_code = extract(media_src, 'static int GetEditorKeyCode(int key)', optional=True)
if key_code is None:
    check(False, 'GetEditorKeyCode exists (Qt key -> browser keyCode)')
    key_code = 'static int GetEditorKeyCode(int) { return 0; }'
show_ctl = extract(media_src, 'void QCefView_Media::showMediaControl(', ('new QAscVideoView',))
live_connect = any(re.match(r'\s*QObject::connect\(m_pMediaView,\s*SIGNAL\(onKeyDown', l)
                   for l in show_ctl.splitlines())
check(live_connect, 'showMediaControl connects the player\'s onKeyDown to onMediaKeyDown (not commented out)')

PRELUDE = r'''
#include <cstdio>
#include <string>
#include <vector>
// Qt key values as in qnamespace.h
namespace Qt {
enum Key { Key_Space = 0x20, Key_0 = 0x30, Key_9 = 0x39, Key_A = 0x41, Key_M = 0x4d, Key_N = 0x4e, Key_O = 0x4f,
	Key_P = 0x50, Key_Z = 0x5a, Key_Escape = 0x01000000, Key_Tab = 0x01000001, Key_Backspace = 0x01000003,
	Key_Return = 0x01000004, Key_Enter = 0x01000005, Key_Home = 0x01000010, Key_End = 0x01000011,
	Key_Left = 0x01000012, Key_Up = 0x01000013, Key_Right = 0x01000014, Key_Down = 0x01000015,
	Key_PageUp = 0x01000016, Key_PageDown = 0x01000017, Key_F = 0x46 };
enum KeyboardModifier { NoModifier = 0, ControlModifier = 0x04000000 };
typedef int KeyboardModifiers;
}
#define emit
static std::vector<std::string> g_log;
static void act(const std::string& s) { g_log.push_back(s); }
struct QKeyEvent {
	int k; bool accepted = false;
	int key() const { return k; }
	Qt::KeyboardModifiers modifiers() const { return Qt::NoModifier; }
	void accept() { accepted = true; }
};
struct Player {
	void keyPressEvent(QKeyEvent* e) { act("player.keyPressEvent"); }
	void stepBack() { act("stepBack"); }
	void stepForward() { act("stepForward"); }
};
struct Playlist { void slotButtonAdd() { act("playlistAdd"); } void Next() { act("playlistNext"); } void Prev() { act("playlistPrev"); } };
struct Slider { void setValue(int) { act("slider"); } };
struct FooterInternal { Slider s; Slider* m_pSlider = &s; };
struct Footer { FooterInternal i; FooterInternal* m_pInternal = &i; };
struct Widget { void setFocus() { act("parentFocus"); } };
struct ViewPrivate {
	Player p; Playlist pl;
	Player* m_pPlayer = &p; Playlist* m_pPlaylist = &pl;
	bool m_bIsPresentationMode = true;
	bool m_bIsSlideShow = false;
};
class QAscVideoView {
public:
	ViewPrivate i; ViewPrivate* m_pInternal = &i; Footer f; Widget w;
	Footer* Footer() { return &f; }
	Widget* parentWidget() { return &w; }
	void TogglePause() { act("TogglePause"); }
	void ToggleMute() { act("ToggleMute"); }
	void Stop() { act("Stop"); }
	void onKeyDown(int key, Qt::KeyboardModifiers) { act("onKeyDown"); }
	bool isSlideShowMode() { return m_pInternal->m_bIsSlideShow; }
	void keyPressEvent(QKeyEvent* event);
};
static std::vector<std::string> g_js;
struct CCefView { void ExecuteInAllFrames(const std::string& s, const bool& = true) { g_js.push_back(s); } };
class QCefView_Media {
public:
	QAscVideoView* m_pMediaView = nullptr;
	CCefView c; CCefView* m_pCefView = &c;
	void setFocus() { act("editorFocus"); }
	void onMediaKeyDown(int key, Qt::KeyboardModifiers mods);
};
'''

MAIN = r'''
static std::string esc(const std::string& s) {
	std::string o;
	for (char c : s) { if (c == '"' || c == '\\') o += '\\'; o += c; }
	return o;
}
int main() {
	struct { const char* name; int key; } keys[] = {
		{"Right", Qt::Key_Right}, {"Down", Qt::Key_Down}, {"PageDown", Qt::Key_PageDown}, {"Space", Qt::Key_Space},
		{"Enter", Qt::Key_Return}, {"Left", Qt::Key_Left}, {"Up", Qt::Key_Up}, {"PageUp", Qt::Key_PageUp},
		{"Home", Qt::Key_Home}, {"End", Qt::Key_End}, {"Escape", Qt::Key_Escape}, {"M", Qt::Key_M}, {"N", Qt::Key_N},
		{"P", Qt::Key_P}, {"Backspace", Qt::Key_Backspace}, {"2", 0x32}};
	for (int show = 0; show < 2; ++show)
		for (auto& k : keys) {
			QAscVideoView view; view.m_pInternal->m_bIsSlideShow = show != 0;
			QCefView_Media media; media.m_pMediaView = &view;
			g_log.clear(); g_js.clear();
			QKeyEvent e{k.key};
			view.keyPressEvent(&e);
			// what the live connection does with the signal
			bool emitted = false;
			for (auto& a : g_log) if (a == "onKeyDown") emitted = true;
			if (emitted) media.onMediaKeyDown(k.key, Qt::NoModifier);
			printf("{\"show\":%d,\"key\":\"%s\",\"accepted\":%d,\"log\":[", show, k.name, e.accepted ? 1 : 0);
			for (size_t i = 0; i < g_log.size(); ++i) printf("%s\"%s\"", i ? "," : "", g_log[i].c_str());
			printf("],\"js\":[");
			for (size_t i = 0; i < g_js.size(); ++i) printf("%s\"%s\"", i ? "," : "", esc(g_js[i]).c_str());
			printf("]}\n");
		}
	return 0;
}
'''

work = tempfile.mkdtemp(prefix='rd1491-')
cpp = os.path.join(work, 't.cpp')
with open(cpp, 'w') as f:
    f.write(PRELUDE + key_press + '\n' + key_code + '\n' + on_key + '\n' + MAIN)
exe = os.path.join(work, 't')
cc = subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-w', cpp, '-o', exe], capture_output=True, text=True)
if cc.returncode:
    print(cc.stderr[:3000])
    raise SystemExit('compile failed')
rows = [json.loads(l) for l in subprocess.run([exe], capture_output=True, text=True, check=True).stdout.splitlines()]
R = {(r['show'], r['key']): r for r in rows}

PLAYER_ACTIONS = {'stepBack', 'stepForward', 'TogglePause', 'Stop', 'player.keyPressEvent', 'playlistNext', 'playlistPrev', 'slider'}
NAV = ['Right', 'Down', 'PageDown', 'Space', 'Enter', 'Left', 'Up', 'PageUp', 'Home', 'End', 'Escape']

print('-- editing (no slide show): the player keeps its keys')
check('stepForward' in R[0, 'Right']['log'] and 'stepBack' in R[0, 'Left']['log'], 'Left/Right scrub the video')
check('TogglePause' in R[0, 'Space']['log'], 'Space pauses/plays')
check('Stop' in R[0, 'Escape']['log'], 'Escape stops the player')
check(all(not R[0, k]['js'] for k in NAV), 'no key is handed to the editor')
check(all('editorFocus' not in R[0, k]['log'] for k in NAV), 'the player keeps the keyboard')

print('-- slide show')
for k in NAV:
    r = R[1, k]
    took = sorted(PLAYER_ACTIONS & set(r['log']))
    check(not took and r['accepted'] and len(r['js']) == 1 and 'editorFocus' in r['log'],
          '%-8s handed to the slide show, player does nothing%s' % (k, (' (player did: %s)' % ','.join(took)) if took else ''))
check('ToggleMute' in R[1, 'M']['log'], 'M still mutes the video')
check(len(R[1, '2']['js']) == 1, 'digits (go-to-slide number) reach the slide show')

# ---------------------------------------------------------------- JS part
trans = read_current(SDKJS, 'slide/Drawing/Transitions.js')
on_kd = extract(trans, 'this.onKeyDown = function(e)', ('onKeyDownCode',))
on_kdc = extract(trans, 'this.onKeyDownCode = function(code)', ('OnNextSlide', 'OnPrevSlide'))
text_input = read_current(SDKJS, 'common/text_input2.js')
get_kbd = extract(text_input, 'AscCommon.getKeyboardEventObject = function(code)', ('keyCode',))
image = read(SDKJS, 'common/Drawings/Format/Image.js', SDKJS_BASE_REF)
gpd = extract(image, 'CMediaData.prototype.getPlayerData = function(oFrameRect, oControlRect)', ('Theme',))
create_md = extract(image, 'function CreateMediaData()', ('DrawingId',))

JS = r'''
const vm = require('vm');
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {};
function makeEditor(inShow) {
  const moves = [];
  const window = {};
  const AscCommon = { global_keyboardEvent: {}, check_KeyboardEvent(e) { this.global_keyboardEvent.KeyCode = e.keyCode; } };
  @GETKBD@
  const DM = new (function () {
    const oThis = this;
    this.GoToSlideShortcutStack = [];
    this.HtmlPage = { m_oApi: { reporterWindow: null }, IsKeyDownButNoPress: false };
    this.OnNextSlide = () => moves.push('next');
    this.OnPrevSlide = () => moves.push('prev');
    this.GoToSlide = n => moves.push('goto:' + n);
    this.GetFirstVisibleSlide = () => 0;
    this.GetLastVisibleSlide = () => 9;
    this.GetSlidesCount = () => 10;
    @ONKD@
    @ONKDC@
  })();
  const Asc = { editor: { isInkDrawerOn: () => false, stopInkDrawer() {}, EndDemonstration: () => moves.push('end') } };
  const api = { isSlideShow: () => inShow, WordControl: { DemonstrationManager: DM } };
  window.editor = api; window.AscCommon = AscCommon;
  return { ctx: vm.createContext({ window, AscCommon, Asc }), moves };
}
for (const [key, js] of Object.entries(input.show)) {
  const ed = makeEditor(true);
  vm.runInContext(js, ed.ctx);
  out[key] = ed.moves;
}
const off = makeEditor(false);
vm.runInContext(input.show.Right, off.ctx);
out.__outside = off.moves;

// getPlayerData
const AscFormat = { CreateMediaData: null };
@CREATEMD@
function md(inShow) {
  const Asc = { editor: { isSlideShow: () => inShow } };
  const AscCommon = { GlobalSkin: { Type: 'light' } };
  const ctx = vm.createContext({ Asc, AscCommon, CreateMediaData });
  const f = vm.runInContext('(' + @GPD@ + ')', ctx);
  const drawing = { Id: 'v', selected: true, getFullRotate: () => 0, getFullFlipH: () => false, getFullFlipV: () => false };
  const self = { isValid: () => true, getDrawing: () => drawing, isFullScreen: () => false, isMute: () => false, isVideo: () => true,
    getVol: () => null, getStartTime: () => 0, getEndTime: () => 0, getName: () => 'v.mp4' };
  const r = { toObject: () => ({ X: 0, Y: 0, W: 1, H: 1 }) };
  return f.call(self, r, r)['IsSlideShow'];
}
out.__gpd = { show: md(true), edit: md(false) };
process.stdout.write(JSON.stringify(out));
'''
gpd_fn = gpd[gpd.index('function'):]
JS = (JS.replace('@GETKBD@', get_kbd + ';')
        .replace('@ONKD@', on_kd + ';')
        .replace('@ONKDC@', on_kdc + ';')
        .replace('@CREATEMD@', create_md)
        .replace('@GPD@', json.dumps(gpd_fn)))
js_in = {k: R[1, k]['js'][0] for k in NAV if len(R[1, k]['js']) == 1}
if 'Right' not in js_in:
    print('FAIL no JS was produced for Right - skipping the slide show half of the JS checks')
    failures.append('no JS for Right')
    js_in['Right'] = '0'
res = json.loads(subprocess.run(['node', '-e', JS], input=json.dumps({'show': js_in}), capture_output=True, text=True, check=True).stdout)

print('-- the generated JS against the real slide show key handler')
want = {'Right': ['next'], 'Down': ['next'], 'PageDown': ['next'], 'Space': ['next'], 'Enter': ['next'],
        'Left': ['prev'], 'Up': ['prev'], 'PageUp': ['prev'], 'Home': ['goto:0'], 'End': ['goto:9'], 'Escape': ['end']}
for k, w in want.items():
    got = res.get(k)
    check(got == w, '%-8s -> %s (got %s)' % (k, w, got))
check(res['__outside'] == [], 'the same JS does nothing when no slide show is running')

print('-- sdkjs player data')
check(res['__gpd'] == {'show': True, 'edit': False},
      'getPlayerData IsSlideShow: true in a show, false while editing (got %s)' % res['__gpd'])

print('BASELINE run (sources from %s / %s)' % (BASE_REF, SDKJS_BASE_REF) if BASELINE else 'fixed sources')
if failures:
    print('FAILED: %d check(s)' % len(failures))
    sys.exit(1)
print('ALL PASS')

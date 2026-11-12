#!/usr/bin/env python3
"""
#2130 - Linux: the desktop is set to grayscale font antialiasing, the document
follows it, but the UI text (the HTML around the document: tabs, ribbon labels)
is drawn with RGB subpixel antialiasing - colour fringes.

Cause: the document is drawn by our own font renderer; the UI is HTML drawn by
Chromium (CEF 109), which uses subpixel (LCD) text unless --disable-lcd-text is
given. Nothing in the app read the desktop's setting: the only place that turned
LCD text off was the ALT Linux special case in desktop-sdk
ChromiumBasedEditors/lib/src/cefwrapper/client_app.h (OnBeforeCommandLineProcessing,
three app classes).
Fix: IsDesktopGrayscaleText() reads Xft.rgba from the X resource database - where
GNOME (gsd-xsettings), KDE Plasma and Xfce publish their font antialiasing choice;
"none" means grayscale - and the same three places add --disable-lcd-text when it
says so. A desktop set to subpixel (rgb/bgr/...) or with no Xft.rgba is unchanged.

How it is tested: the REAL IsDesktopGrayscaleText and the REAL `if` of the first
OnBeforeCommandLineProcessing (the one with the ALT Linux check) are extracted by
brace matching and compiled with stand-ins for XOpenDisplay/XResourceManagerString/
XCloseDisplay (returning the resource string a desktop would have set),
NSFile::CFileBinary::Exists and CefCommandLine::AppendSwitch. The three call sites
must all carry the check. Cases: GNOME grayscale ("Xft.rgba:\\tnone"), KDE style
("Xft.rgba: none"), GNOME subpixel ("rgb"), no Xft.rgba, no X display, ALT Linux.
BASELINE=1 reads client_app.h from BASE_REF: no LCD switch for a grayscale desktop,
so the test FAILS.

  ./extract_and_run.py             RD_REPO (default ../../desktop-sdk), must PASS
  BASELINE=1 ./extract_and_run.py  BASE_REF, must FAIL

NOT claimed: that each desktop writes Xft.rgba (from their sources: gsd-xsettings
xft_settings_set_xresources, Plasma's font KCM via xrdb, xfsettingsd); that CEF 109
then draws grayscale UI text (that is what --disable-lcd-text does in Chromium) -
needs a Linux GUI check. The setting is read once at start: changing it needs a
restart of the app.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.abspath(os.environ.get('RD_REPO', os.path.join(HERE, '..', '..', 'desktop-sdk')))
BASE_REF = os.environ.get('BASE_REF', '54c6d5d6^')
BASELINE = bool(os.environ.get('BASELINE'))
CLIENT_APP = 'ChromiumBasedEditors/lib/src/cefwrapper/client_app.h'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', SDK, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(SDK, rel), encoding='utf-8').read()


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


src = read(CLIENT_APP)
p = src.find('static bool IsDesktopGrayscaleText()')
helper = brace_match(src, p) if p != -1 else ''
sites = [m.start() for m in re.finditer(r'if \(NSFile::CFileBinary::Exists\(L"/etc/altlinux-release"\)', src)]
if len(sites) != 3:
    raise SystemExit('expected the three ALT Linux checks in client_app.h, found %d' % len(sites))
stmts = [brace_match(src, s) for s in sites]
all_same = all('IsDesktopGrayscaleText()' in s for s in stmts) or not any('IsDesktopGrayscaleText()' in s for s in stmts)

HARNESS = r'''
#include <string>
#include <vector>
#include <stdio.h>
#include <string.h>
struct Display {};
static Display g_display; static const char* g_resources = nullptr; static bool g_hasDisplay = true; static int g_open = 0;
static Display* XOpenDisplay(const char*) { if (!g_hasDisplay) return nullptr; g_open++; return &g_display; }
static char* XResourceManagerString(Display*) { return (char*)g_resources; }
static int XCloseDisplay(Display*) { g_open--; return 0; }
static bool g_alt = false;
namespace NSFile { struct CFileBinary { static bool Exists(const std::wstring&) { return g_alt; } }; }
struct CCommandLine { std::vector<std::string> sw; void AppendSwitch(const char* s) { sw.push_back(s); } };

%(helper)s

static bool run(const char* resources, bool hasDisplay, bool alt)
{
    g_resources = resources; g_hasDisplay = hasDisplay; g_alt = alt;
    CCommandLine oCmd; CCommandLine* command_line = &oCmd;
    %(stmt)s
    if (g_open != 0) printf("  X display left open!\n");
    for (auto& s : oCmd.sw) if (s == "--disable-lcd-text") return true;
    return false;
}
static int failures = 0;
static void expect(const char* what, bool got, bool want)
{
    printf("  %%-44s -> %%-28s %%s\n", what, got ? "--disable-lcd-text" : "subpixel UI text (as before)",
           got == want ? "ok" : "FAILED");
    if (got != want) failures++;
}
int main()
{
    printf("#2130 UI text antialiasing at start-up:\n");
    expect("GNOME, grayscale (Xft.rgba:\\tnone)", run("Xft.antialias:\t1\nXft.hinting:\t1\nXft.rgba:\tnone\nXft.dpi:\t96\n", true, false), true);
    expect("KDE Plasma, subpixel off (Xft.rgba: none)", run("Xcursor.theme: breeze_cursors\nXft.rgba: none\n", true, false), true);
    expect("GNOME, subpixel (Xft.rgba:\\trgb)", run("Xft.antialias:\t1\nXft.rgba:\trgb\n", true, false), false);
    expect("no Xft.rgba in the resources", run("Xcursor.size:\t24\n", true, false), false);
    expect("no resources at all", run(nullptr, true, false), false);
    expect("no X display", run(nullptr, false, false), false);
    expect("ALT Linux (as before)", run(nullptr, true, true), true);
    return failures ? 1 : 0;
}
''' % dict(helper=helper, stmt=stmts[0])

tmp = tempfile.mkdtemp(prefix='rd2130-')
try:
    open(os.path.join(tmp, 't.cpp'), 'w').write(HARNESS)
    cxx = shutil.which('clang++') or shutil.which('g++')
    subprocess.run([cxx, '-std=c++14', '-w', os.path.join(tmp, 't.cpp'), '-o', os.path.join(tmp, 't')], check=True)
    rc = subprocess.run([os.path.join(tmp, 't')]).returncode
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print('#2130 all three OnBeforeCommandLineProcessing carry the same check: %s' % ('yes  ok' if all_same else 'no  FAILED'))
ok = rc == 0 and all_same
print('PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)

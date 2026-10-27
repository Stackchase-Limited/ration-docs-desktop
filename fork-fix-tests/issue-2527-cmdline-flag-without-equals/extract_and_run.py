#!/usr/bin/env python3
"""
#2527 - "--view / --edit / --review passed without '=' abort the app with an
uncaught std::out_of_range".

handleInputCmd (desktop-apps/win-linux/src/cascapplicationmanagerwrapper.cpp)
understood only --view=path: for "--view path" it called substr(len("--view")+1)
on the 6-character token, threw std::out_of_range, and nothing caught it.
The same function had two more of the kind: an install-plugin link with no
plugin name (reachable from a clicked web link) took substr past its end, and
an empty argument was indexed at length()-1.

The function needs Qt and the whole app, so this test lifts the three fixed
fragments out of the real source and runs them standalone:
  1. the loop that joins "--view path" into "--view=path",
  2. the guard before substr for a bare --view,
  3. the plugin-name extraction and the trailing-'/' strip.
Run against the unfixed file it fails to find fragment 1 (FAIL).
"""
import os, re, subprocess, sys, tempfile

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '../../desktop-apps/win-linux/src/cascapplicationmanagerwrapper.cpp')
src = open(SRC).read()

def grab(start, end):
    i = src.find(start)
    if i < 0:
        print('FAIL: fragment not found:', start[:60]); sys.exit(1)
    j = src.find(end, i)
    return src[i:j + len(end)]

join_loop = grab('    std::vector<wstring> vargs;\n', '        } else vargs.push_back(a);\n    }\n')
guard = grab('                if ( arg.size() <= c + 1 )', 'open_opts.wurl = arg.substr(++c);')
plugin = grab("            if (!argScheme.empty() && argScheme.back() == '/')", ': std::wstring();')

prog = r'''
#include <string>
#include <vector>
#include <cstdio>
using namespace std;
static vector<wstring> join(const vector<wstring>& vargs_in) {
JOIN
    return vargs;
}
static wstring wurl_of(const wstring& arg, size_t c) {
    wstring wurl = L"<none>";
    do {
GUARD
    } while (0);
    return wurl;
}
static wstring plugin_of(wstring argScheme, const wstring& app_action_plugin) {
PLUGIN
    return _plugin_name;
}
int main() {
    int bad = 0;
    auto expect = [&](bool ok, const char* what) { printf("%s %s\n", ok ? "ok  " : "FAIL", what); bad += !ok; };
    auto j = join({L"--view", L"/tmp/a.docx", L"--edit=/tmp/b.docx", L"--review", L"--force-use-window", L"--edit"});
    expect(j.size() == 5 && j[0] == L"--view=/tmp/a.docx", "\"--view path\" joined");
    expect(j[1] == L"--edit=/tmp/b.docx", "--edit=path untouched");
    expect(j[2] == L"--review" && j[3] == L"--force-use-window", "a following flag is not taken as the path");
    expect(j[4] == L"--edit", "trailing bare flag kept");
    expect(wurl_of(L"--view=/tmp/a.docx", 6) == L"/tmp/a.docx", "--view=path parsed");
    expect(wurl_of(L"--view", 6) == L"<none>", "bare --view skipped, no throw");
    expect(wurl_of(L"--view=", 6) == L"<none>", "--view= skipped, no throw");
    const wstring P = L"oo-office://action|install-plugin";
    expect(plugin_of(P + L"|myplugin/", P) == L"myplugin", "plugin name read, '/' stripped");
    expect(plugin_of(P, P).empty(), "link without a name: empty, no throw");
    expect(plugin_of(P + L"/", P).empty(), "link ending in '/': empty, no throw");
    expect(plugin_of(L"", P).empty(), "empty argument: no out-of-bounds read");
    return bad ? 1 : 0;
}
'''
guard_body = guard.replace('continue;', 'break;').replace('open_opts.wurl', 'wurl')
plugin_body = plugin.replace('                if ( !_plugin_name.empty() ) {', '')
prog = prog.replace('JOIN', join_loop).replace('GUARD', guard_body).replace('PLUGIN', plugin_body)
# the plugin fragment ends inside an if-block opened by rfind(); close it and give the default
prog = prog.replace('    return _plugin_name;\n}', '    return _plugin_name;\n    }\n    return std::wstring();\n}')

with tempfile.TemporaryDirectory() as t:
    c, exe = os.path.join(t, 't.cpp'), os.path.join(t, 't')
    open(c, 'w').write(prog)
    r = subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-o', exe, c], capture_output=True, text=True)
    if r.returncode:
        print(r.stderr); print('FAIL: does not compile'); sys.exit(1)
    r = subprocess.run([exe], capture_output=True, text=True)
    print(r.stdout + r.stderr, end='')
    print('PASS' if r.returncode == 0 else 'FAIL'); sys.exit(r.returncode)

#!/usr/bin/env python3
"""
#1829 - "Allow more characters in User Name": "Firstname Lastname" or "Lastname,
Firstname", as Word puts on comments and tracked changes, could not be set.

Two defects, both in desktop-apps:
1. The start page's check (common/loginpage/src/panelsettings.js, _validate_user_name)
   is a whitelist without the comma, so "Doe, John" was marked as an error and not
   applied. The typographic apostrophe (O’Brien with smart quotes) was refused too.
   (Spaces have been allowed since 2020 - that part of the report is already true.)
2. macOS only: ASCEditorJSVariables.applyParameters (macos/ONLYOFFICE/Code/Utils/
   ASCEditorJSVariables.mm) joined the editor URL parameters as raw key=value pairs,
   while the editor page (web-apps/apps/api/documents/index.html.desktop,
   getUrlParams) reads them with decodeURIComponent. Windows/Linux percent-encode the
   name; macOS did not. So names the check accepts came out wrong: '&' and '#' cut
   them, '+' became a space, and '%' made getUrlParams throw URIError - the editor
   page stops before creating the editor, so no document opened.

This test
- extracts the real _validate_user_name arrow function from panelsettings.js by brace
  matching and runs it in node;
- extracts the real -applyParameters method from ASCEditorJSVariables.mm by brace
  matching, compiles it (clang++, Objective-C++, Foundation) inside a stub class with
  stubs for NSAscApplicationWorker/CAscApplicationManager (which only record the
  string handed to InitAdditionalEditorParams) and NSString -stdwstring, and
- feeds that string, appended to an editor URL as cefview.cpp does, to the real
  getUrlParams extracted from web-apps' index.html.desktop.

Claimed: "Doe, John" and "O’Brien" pass the check, while '<', ';', '|' and tabs are
still refused; on macOS names with , & # + % ’ and non-Latin letters reach the editor
page exactly, and lang/uitheme/mode values are unchanged.
NOT claimed: the GUI (start page Apply, an editor opening) was not run; Windows/Linux
native code is untouched (it already encoded). Needs macOS (clang, Foundation) and node.

RD_REPO overrides the desktop-apps checkout (default ../../desktop-apps), RD_WEBAPPS
the web-apps one (default ../../web-apps, read from the working tree in both modes).
BASELINE=1 reads the desktop-apps files from git at BASE_REF and must FAIL there.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
WEBAPPS = os.environ.get('RD_WEBAPPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'web-apps'))
# Pinned to the parent of the commit that landed this fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'd269d54a3^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel, repo=APPS, baseline=BASELINE):
    if baseline:
        return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(repo, rel), encoding='utf-8').read()


def block(text, start):
    ob = text.index('{', start)
    depth = 0
    for i in range(ob, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise SystemExit('unbalanced braces')


def extract(text, marker):
    i = text.find(marker)
    if i < 0:
        raise SystemExit('not found: ' + marker)
    return block(text, i)


settings = read('common/loginpage/src/panelsettings.js')
validate = extract(settings, 'const _validate_user_name = name =>')
jsvars = read('macos/ONLYOFFICE/Code/Utils/ASCEditorJSVariables.mm')
apply_params = extract(jsvars, '- (void)applyParameters')
editor_page = read('apps/api/documents/index.html.desktop', WEBAPPS, False)
get_url_params = extract(editor_page, 'function getUrlParams()')

tmp = tempfile.mkdtemp(prefix='rd1829-')
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print('%s  %s%s' % ('PASS' if ok else 'FAIL', name, '' if ok else '\n        ' + detail))


# --- 1. the start page check -------------------------------------------------------
names_ok = ['John Smith', 'Doe, John', 'O’Brien, Mary', 'Zoë Ångström', 'Jean-Luc (JL) Picard']
names_bad = ['<b>x</b>', 'a;b', 'a|b', 'tab\there', '']
js = r'''
const window = {utils: {inParams: {osver: ''}}};
const navigator = {appVersion: '5.0 (Macintosh; Intel Mac OS X 10_15_7)'};
%s;
const out = {};
for (const n of JSON.parse(process.argv[2])) out[n] = !!(n.length && _validate_user_name(n));
console.log(JSON.stringify(out));
''' % validate
p = os.path.join(tmp, 'validate.js')
open(p, 'w', encoding='utf-8').write(js)
res = json.loads(subprocess.run(['node', p, json.dumps(names_ok + names_bad)],
                                capture_output=True, text=True, check=True).stdout)
print('#1829 user name characters  (%s)' % ('BASELINE ' + BASE_REF if BASELINE else APPS))
print('\nStart page check (_validate_user_name)')
for n in names_ok:
    check('accepted: %r' % n, res[n] is True, 'refused')
for n in names_bad:
    check('still refused: %r' % n, res[n] is False, 'accepted')

# --- 2. macOS: the parameters the editors are opened with ---------------------------
mm = r'''
#import <Foundation/Foundation.h>
#include <string>
#include <cstdio>
class CAscApplicationManager {
public:
    std::wstring last;
    void InitAdditionalEditorParams(std::wstring& s) { last = s; }
};
static CAscApplicationManager g_mgr;
@interface NSAscApplicationWorker : NSObject
+ (CAscApplicationManager*)getAppManager;
@end
@implementation NSAscApplicationWorker
+ (CAscApplicationManager*)getAppManager { return &g_mgr; }
@end
@interface NSString (RDWide)
- (std::wstring)stdwstring;
@end
@implementation NSString (RDWide)
- (std::wstring)stdwstring {
    NSData * d = [self dataUsingEncoding:NSUTF32LittleEndianStringEncoding];
    return std::wstring((const wchar_t*)d.bytes, d.length / sizeof(wchar_t));
}
@end
@interface RDVars : NSObject { NSMutableDictionary * _urlParams; }
- (instancetype)initWithParams:(NSMutableDictionary*)p;
- (void)applyParameters;
@end
@implementation RDVars
- (instancetype)initWithParams:(NSMutableDictionary*)p { self = [super init]; _urlParams = p; return self; }
%s
@end
int main(int argc, char** argv) {
    @autoreleasepool {
        NSMutableDictionary * p = [NSMutableDictionary dictionary];
        for (int i = 1; i + 1 < argc; i += 2)
            [p setValue:[NSString stringWithUTF8String:argv[i + 1]] forKey:[NSString stringWithUTF8String:argv[i]]];
        [[[RDVars alloc] initWithParams:p] applyParameters];
        NSString * s = [[NSString alloc] initWithBytes:g_mgr.last.data() length:g_mgr.last.size() * sizeof(wchar_t)
                                              encoding:NSUTF32LittleEndianStringEncoding];
        printf("%%s\n", [s UTF8String]);
    }
    return 0;
}
''' % apply_params
mmp = os.path.join(tmp, 'apply.mm')
exe = os.path.join(tmp, 'apply')
open(mmp, 'w', encoding='utf-8').write(mm)
r = subprocess.run(['clang++', '-x', 'objective-c++', '-std=gnu++17', '-fobjc-arc', '-w', mmp,
                    '-framework', 'Foundation', '-o', exe], capture_output=True, text=True)
if r.returncode:
    sys.stderr.write(r.stderr[-4000:])
    raise SystemExit('compile failed')

parse_js = r'''
%s
const out = {};
for (const q of JSON.parse(process.argv[2])) {
    // the address goes through URL parsing first, as in the browser: '#' starts the fragment
    global.window = {location: {search: new URL('file:///editors/web-apps/apps/api/documents/index.html?' + q).search}};
    const window = global.window;
    try { out[q] = getUrlParams(); } catch (e) { out[q] = {error: String(e)}; }
}
console.log(JSON.stringify(out));
''' % get_url_params.replace('window.location', 'global.window.location')
pp = os.path.join(tmp, 'parse.js')
open(pp, 'w', encoding='utf-8').write(parse_js)

print('\nmacOS: user name as the editor page reads it back')
user_names = ['Doe, John', 'Tom & Jerry', 'C# Team', 'A+B', '100% Smith', 'O’Brien', '王小明', 'x=y']
queries = []
for n in user_names:
    params = subprocess.run([exe, 'username', n, 'lang', 'en', 'uitheme', 'theme-dark', 'mode', 'view'],
                            capture_output=True, text=True, check=True).stdout.rstrip('\n')
    # cefview.cpp: the file's own parameters, then "&" + the additional ones
    queries.append('url=_offline_&filetype=docx&' + params)
parsed = json.loads(subprocess.run(['node', pp, json.dumps(queries)],
                                   capture_output=True, text=True, check=True).stdout)
for n, q in zip(user_names, queries):
    got = parsed[q]
    ok = (got.get('username') == n and got.get('lang') == 'en' and got.get('uitheme') == 'theme-dark'
          and got.get('mode') == 'view' and got.get('filetype') == 'docx')
    check('username %r arrives intact (lang/uitheme/mode too)' % n, ok,
          'query ...%s -> %s' % (q[len('url=_offline_&filetype=docx'):], json.dumps(got, ensure_ascii=False)))

fails = results.count(False)
print('\n%d passed, %d failed' % (len(results) - fails, fails))
sys.exit(1 if fails else 0)

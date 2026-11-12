#!/usr/bin/env python3
"""
#2466 - "Deleting default plugins (with restore function)". Native half
(desktop-sdk plugins.h) plus the editor's answer to the plugin manager
(sdkjs common/apiBase_plugins.js pluginMethod_GetInstalledPlugins).

Plugins installed with the application (DeepL/Translator, YouTube, ...) live in
CPluginsManager::m_strDirectory, inside the application. RemovePlugin only
looks in the user folder, so for them it returns false, and the editor marks
every one of them canRemoved=false - the plugin manager shows no Remove button.

New, behind the setting "plugins-hide-builtin" (start page Settings, off by
default; reaches the renderer as the startup property of the same name and
sets CPluginsManager::m_bCanHideSystemPlugins):
  - such a plugin is offered for removal (its config in the list carries
    "canRemoved": true, and the editor then does not protect it);
  - RemovePlugin does not touch the application folder; it writes the GUID to
    <user plugins>/hidden-builtin-plugins and the plugin leaves every list;
  - GetPluginsJson(false) (GetBackupPlugins, the plugin manager's "restore"
    list) offers it with "backup": true, under the application folder's url;
  - RestorePlugin (what PluginInstall does for a "backup" config) takes it off
    the list; the plugin manager itself can never be hidden.
With the setting off nothing changes: RemovePlugin is false, the file is
ignored, nothing is marked removable.

This compiles the REAL plugins.h (with utils.h, Logger.h, plugins_policy.h
from the same tree) into a small driver linked against core's prebuilt kernel
library (as issue-2107-plugin-remove-native does), lays out the macOS app's
folders under a temp dir, and runs the REAL pluginMethod_GetInstalledPlugins
(brace-matched out of apiBase_plugins.js) in node against the driver's list.

The REAL store _loadBackupPlugins (onlyoffice.github.io store/scripts/code.js)
is run against the driver's restore list as well.

Checks: setting off = today's behaviour (no canRemoved, RemovePlugin false,
an existing hidden file ignored); setting on: canRemoved on built-ins but not
on the plugin manager, editor reports canRemoved true; remove hides it (the
application folder untouched), restore list offers it, restore brings it back
and empties the file; the plugin manager cannot be hidden; a user plugin is
still removed as before; a user-updated copy of a built-in is still listed.

Env:
  RD_REPO     desktop-sdk checkout (default ../../desktop-sdk)
  RD_SDKJS    sdkjs checkout (default ../../sdkjs)
  RD_CORE     core checkout with a built kernel lib (default ../../core)
  RD_APPS     desktop-apps checkout (default ../../desktop-apps)
  RD_STORE    onlyoffice.github.io checkout (default ../../onlyoffice.github.io)
  BASELINE=1  reads the sources at BASE_REF / SDKJS_BASE_REF / STORE_BASE_REF / APPS_BASE_REF;
              must FAIL (each of the three alone fails too).

NOT claimed: Windows (not compiled here), the plugin manager's own UI
(the store's restore click is read, not run), the start page checkbox and its
macOS/Windows/Linux storage (desktop-apps: presence of the key in each place
only), a run in the app.
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
SDKJS = os.environ.get('RD_SDKJS') or os.path.normpath(os.path.join(HERE, '..', '..', 'sdkjs'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
APPS = os.environ.get('RD_APPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
STORE = os.environ.get('RD_STORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'onlyoffice.github.io'))
# Pinned to the parents of the commits that landed the feature, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '1db9f146^')
SDKJS_BASE_REF = os.environ.get('SDKJS_BASE_REF', '532aac2b28^')
STORE_BASE_REF = os.environ.get('STORE_BASE_REF', 'bea6535b^')
APPS_BASE_REF = os.environ.get('APPS_BASE_REF', '6c7c62a2b^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'
HEADERS = ['plugins.h', 'utils.h', 'Logger.h', 'plugins_policy.h']

DRIVER = r'''
#include "desktop-sdk/ChromiumBasedEditors/lib/src/plugins.h"
#include <cstdio>
// plugins_policy.cpp is not linked: the list code calls only this one
std::set<std::string> NSPluginsPolicy::GetDisabledGuids(const NSPluginsPolicy::CPolicy&) { return std::set<std::string>(); }
template <class T> static void SetHide(T& m, bool b) { m.m_bCanHideSystemPlugins = b; }
int main(int argc, char** argv)
{
	if (argc < 5) return 2;
	CPluginsManager m;
	m.m_strDirectory = UTF8_TO_U(std::string(argv[1]));
	m.m_strUserDirectory = UTF8_TO_U(std::string(argv[2]));
	SetHide(m, std::string(argv[3]) == "1");
	std::string cmd = argv[4];
	if (cmd == "list") { printf("%s\n", m.GetPluginsJson(true, true).c_str()); return 0; }
	if (cmd == "backups") { printf("%s\n", m.GetPluginsJson(false, true).c_str()); return 0; }
	if (cmd == "remove" && argc >= 6) { printf("%s\n", m.RemovePlugin(UTF8_TO_U(std::string(argv[5])), false) ? "true" : "false"); return 0; }
	if (cmd == "restore" && argc >= 6) { printf("%s\n", m.RestorePlugin(UTF8_TO_U(std::string(argv[5]))) ? "true" : "false"); return 0; }
	return 2;
}
'''

PM = '{AA2EA9B6-9EC2-415F-9762-634EE8D9A95E}'      # the plugin manager
TR = '{7327FC95-16DA-41D9-9AF2-0E7F449F6800}'      # Translator (DeepL)
YT = '{38E022EA-AD92-45FC-B22B-49DF39746DB4}'      # YouTube, updated by the user
U3 = '{22222222-0000-0000-0000-000000000003}'      # the user's own plugin


def git_show(repo, ref, rel):
    return subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)],
                          capture_output=True, text=True, check=True).stdout


def read(rel):
    if BASELINE:
        return git_show(REPO, BASE_REF, rel)
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def read_sdkjs(rel):
    if BASELINE:
        return git_show(SDKJS, SDKJS_BASE_REF, rel)
    return open(os.path.join(SDKJS, rel), encoding='utf-8').read()


def read_apps(rel):
    if BASELINE:
        return git_show(APPS, APPS_BASE_REF, rel)
    return open(os.path.join(APPS, rel), encoding='utf-8').read()


def setting_wired():
    """Where the setting travels: start page key -> user setting -> startup property -> CPluginsManager.
    Presence checks only (the native/ObjC code is not run here)."""
    missing = []
    want = [
        (read_apps, 'common/loginpage/src/panelsettings.js', ['removebuiltinplugins']),
        (read_apps, 'macos/ONLYOFFICE/Code/Controllers/Common/ASCCommonViewController.mm', ['"plugins-hide-builtin"', '@"removebuiltinplugins"']),
        (read_apps, 'macos/ONLYOFFICE/Code/Controllers/Common/ASCEventsController.mm', ['"plugins-hide-builtin"', '@"removebuiltinplugins"']),
        (read_apps, 'win-linux/src/prop/cmainwindowimpl.cpp', ['"plugins-hide-builtin"', '"removebuiltinplugins"']),
        (read_apps, 'win-linux/src/cascapplicationmanagerwrapper.cpp', ['"plugins-hide-builtin"', '"removebuiltinplugins"']),
        (read, SRC + 'applicationmanager_p.h', ['"plugins-hide-builtin"']),
        (read, SRC + 'applicationmanager.cpp', ['"plugins-hide-builtin=1"']),
        (read, SRC + 'cefwrapper/client_renderer_wrapper.cpp', ['"plugins-hide-builtin"', 'm_bCanHideSystemPlugins = m_bCanHideSystemPlugins']),
    ]
    for reader, rel, needles in want:
        text = reader(rel)
        missing += ['%s: %s' % (rel.split('/')[-1], n) for n in needles if n not in text]
    n = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp').count('oPlugins.m_bCanHideSystemPlugins = m_bCanHideSystemPlugins')
    if n != 4:
        missing.append('renderer sets the flag on %d of 4 plugin managers' % n)
    return missing


def read_store(rel):
    if BASELINE:
        return git_show(STORE, STORE_BASE_REF, rel)
    return open(os.path.join(STORE, rel), encoding='utf-8').read()


def store_restore_list(backups_json):
    """The REAL store _loadBackupPlugins, given the native restore list as GetBackupPlugins."""
    fn = block(read_store('store/scripts/code.js'), 'function _loadBackupPlugins() {')
    assert fn, '_loadBackupPlugins not found'
    js = r'''
const isLocal = true;
global.window = { AscDesktopEditor: { GetBackupPlugins: () => %s } };
%s
process.stdout.write(JSON.stringify(_loadBackupPlugins().map((p) => [p.obj.name, !!p.obj.builtin, p.obj.baseUrl])));
''' % (json.dumps(backups_json), fn)
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip().splitlines()[-1])
    return json.loads(r.stdout)


def libdir():
    names = {('Darwin', 'arm64'): 'mac_arm64', ('Darwin', 'x86_64'): 'mac_64',
             ('Linux', 'x86_64'): 'linux_64', ('Linux', 'aarch64'): 'linux_arm64'}
    d = os.path.join(CORE, 'build', 'lib', names.get((platform.system(), platform.machine()), ''))
    if not os.path.isdir(d):
        sys.exit('core kernel lib not built: %s' % d)
    return d


def build(work):
    inc = os.path.join(work, 'inc')
    dst = os.path.join(inc, 'desktop-sdk', SRC)
    os.makedirs(dst)
    for h in HEADERS:
        with open(os.path.join(dst, h), 'w', encoding='utf-8') as f:
            f.write(read(SRC + h))
    os.symlink(CORE, os.path.join(inc, 'core'))
    cpp = os.path.join(work, 'drv.cpp')
    with open(cpp, 'w') as f:
        f.write(DRIVER)
    exe = os.path.join(work, 'drv')
    lib = libdir()
    cmd = ['clang++' if shutil.which('clang++') else 'g++', '-std=c++14', '-w', '-I' + inc,
           '-I' + os.path.join(CORE, 'DesktopEditor/freetype-2.10.4/include'), cpp, '-o', exe]
    if platform.system() == 'Darwin':
        cmd += ['-D_MAC', '-DMAC', '-D_UNIX', '-DUNIX', '-F' + lib, '-framework', 'kernel', '-Wl,-rpath,' + lib]
    else:
        cmd += ['-D_LINUX', '-DLINUX', '-D_UNIX', '-DUNIX', '-L' + lib, '-lkernel', '-Wl,-rpath,' + lib]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # the baseline has no m_bCanHideSystemPlugins: report it as the failure it is
        return None, r.stderr.strip().splitlines()[:3]
    return exe, None


def mk(d, guid, name, version):
    os.makedirs(d)
    with open(os.path.join(d, 'config.json'), 'w') as f:
        json.dump({'name': name, 'guid': 'asc.' + guid, 'version': version,
                   'variations': [{'description': name, 'url': 'index.html', 'isVisual': True}]}, f, indent=1)
    with open(os.path.join(d, 'index.html'), 'w') as f:
        f.write('x')


def block(source, marker):
    at = source.find(marker)
    if at < 0:
        return None
    depth = 0
    i = source.index('{', at + len(marker) - 1)
    while i < len(source):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[at:i + 1]
        i += 1
    raise ValueError('unbalanced ' + marker)


def editor_answer(list_json):
    """The REAL pluginMethod_GetInstalledPlugins, given the native list as GetInstallPlugins."""
    src = read_sdkjs('common/apiBase_plugins.js')
    fn = block(src, 'Api.prototype["pluginMethod_GetInstalledPlugins"] = function()')
    assert fn, 'pluginMethod_GetInstalledPlugins not found'
    data = json.loads(list_json)
    plugins = [{'guid': p['guid'], 'isConnector': False, 'name': p['name']} for g in data for p in g['pluginsData']]
    js = r'''
const Api = function () {};
const g_list = %s, g_plugins = %s;
global.window = { AscDesktopEditor: { GetInstallPlugins: () => g_list },
                  location: { protocol: 'file:', href: 'file:///app/index.html' },
                  g_asc_plugins: { plugins: g_plugins.map((p) => ({ ...p, serialize: () => ({ name: p.name }) })), systemPlugins: [] } };
%s;
process.stdout.write(JSON.stringify(new Api()["pluginMethod_GetInstalledPlugins"]().map((p) => [p.obj.name, p.canRemoved])));
''' % (json.dumps(list_json), json.dumps(plugins), fn)
    r = subprocess.run(['node', '-e', js], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip().splitlines()[-1])
    return dict(json.loads(r.stdout))


def main():
    work = tempfile.mkdtemp(prefix='rd2466-')
    failures = []

    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what)
        if not ok:
            failures.append(what)

    try:
        exe, err = build(work)
        check(exe is not None, 'plugins.h has CPluginsManager::m_bCanHideSystemPlugins (%s)' % (err or 'built'))
        if exe is None:
            raise SystemExit
        root = os.path.join(work, 'fx')
        sysd = os.path.join(root, 'Ration Docs.app/Contents/Resources/editors/sdkjs-plugins')
        usr = os.path.join(root, 'Library/Application Support/com.stackchase.rationdocs.test/data/sdkjs-plugins')
        mk(os.path.join(sysd, PM), PM, 'Plugin Manager', '1.0.0')
        mk(os.path.join(sysd, TR), TR, 'Translator', '1.0.0')
        mk(os.path.join(sysd, YT), YT, 'YouTube', '1.0.0')
        mk(os.path.join(usr, YT), YT, 'YouTube update', '2.0.0')
        mk(os.path.join(usr, U3), U3, 'U3 user', '1.0.0')
        hidden_file = os.path.join(usr, 'hidden-builtin-plugins')
        app_before = sorted(os.listdir(sysd))

        def run(flag, *a):
            return subprocess.run([exe, sysd, usr, flag] + list(a), capture_output=True, text=True, check=True).stdout.strip()

        def names(flag):
            d = json.loads(run(flag, 'list'))
            return sorted(p['name'] for g in d for p in g['pluginsData'])

        def removable(flag):
            d = json.loads(run(flag, 'list'))
            return sorted(p['name'] for p in d[0]['pluginsData'] if p.get('canRemoved') is True)

        def backups(flag):
            d = json.loads(run(flag, 'backups'))
            return [(g['url'], sorted(p['name'] for p in g['pluginsData'] if p.get('backup') and p.get('builtin'))) for g in d]

        miss = setting_wired()
        check(not miss, 'the setting is wired start page -> settings.xml -> renderer (%s)' % (miss or 'all found'))

        # --- setting off: today's behaviour
        check(removable('0') == [], 'off: nothing of the application marked removable (%s)' % removable('0'))
        r = run('0', 'remove', 'asc.' + TR)
        check(r == 'false' and 'Translator' in names('0') and not os.path.exists(hidden_file),
              'off: RemovePlugin(Translator)=%s, still listed, no hidden file' % r)
        with open(hidden_file, 'w') as f:
            f.write(TR + '\n')
        check('Translator' in names('0') and backups('0') == [],
              'off: an existing hidden file is ignored (%s / %s)' % (names('0'), backups('0')))
        os.remove(hidden_file)
        ans = editor_answer(run('0', 'list'))
        check(ans.get('Translator') is False and ans.get('U3 user') is True,
              'off: editor answers canRemoved Translator=%s, user plugin=%s' % (ans.get('Translator'), ans.get('U3 user')))

        # --- setting on
        check(removable('1') == ['Translator'],
              'on: built-ins marked removable, not the plugin manager (%s)' % removable('1'))
        ans = editor_answer(run('1', 'list'))
        check(ans.get('Translator') is True and ans.get('Plugin Manager') is False,
              'on: editor answers canRemoved Translator=%s, Plugin Manager=%s' % (ans.get('Translator'), ans.get('Plugin Manager')))
        r = run('1', 'remove', 'asc.' + TR)
        check(r == 'true' and 'Translator' not in names('1'), 'on: RemovePlugin(Translator)=%s, gone from the list %s' % (r, names('1')))
        check(sorted(os.listdir(sysd)) == app_before and os.path.isfile(os.path.join(sysd, TR, 'config.json')),
              'on: the application folder is untouched')
        b = backups('1')
        check(any(u.rstrip('/').endswith('editors/sdkjs-plugins') and n == ['Translator'] for u, n in b),
              'on: the restore list offers Translator ("backup", "builtin") under the application folder (%s)' % b)
        # a user backup too, so the application's group is the second one
        mk(os.path.join(usr, 'backup', U3), U3, 'U3 backup', '0.9.0')
        lst = store_restore_list(run('1', 'backups'))
        check(['Translator', True] in [x[:2] for x in lst] and ['U3 backup', False] in [x[:2] for x in lst] and
              any(x[0] == 'Translator' and x[2].endswith('editors/sdkjs-plugins/' + TR + '/') for x in lst),
              'on: the plugin manager (store _loadBackupPlugins) offers both groups for restoring (%s)' % [x[:2] for x in lst])
        shutil.rmtree(os.path.join(usr, 'backup'))
        r = run('1', 'remove', 'asc.' + PM)
        check(r == 'false' and 'Plugin Manager' in names('1'), 'on: the plugin manager cannot be hidden (%s)' % r)
        r = run('1', 'restore', 'asc.' + TR)
        check(r == 'true' and 'Translator' in names('1') and not os.path.exists(hidden_file),
              'on: RestorePlugin(Translator)=%s, listed again, hidden file gone' % r)
        check('YouTube update' in names('1'), 'on: a user update of a built-in is still listed')
        r = run('1', 'remove', 'asc.' + U3)
        check(r == 'true' and 'U3 user' not in names('1') and not os.path.isdir(os.path.join(usr, U3)),
              'on: a user plugin is removed as before (%s)' % r)
    except SystemExit:
        pass
    finally:
        shutil.rmtree(work, ignore_errors=True)

    tag = ' [BASELINE %s / %s / %s / %s]' % (BASE_REF, SDKJS_BASE_REF, STORE_BASE_REF, APPS_BASE_REF) if BASELINE else ''
    if failures:
        print('FAIL #2466: %d check(s) failed%s' % (len(failures), tag))
        sys.exit(1)
    print('PASS #2466: built-in plugins can be hidden and restored, only with the setting on%s' % tag)


if __name__ == '__main__':
    main()

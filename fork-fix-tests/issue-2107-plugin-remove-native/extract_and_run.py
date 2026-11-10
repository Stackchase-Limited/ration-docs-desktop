#!/usr/bin/env python3
"""
#2107 - a plugin installed for all users cannot be uninstalled, and the plugin
manager does not say so. Native half (desktop-sdk plugins.h).

CPluginsManager lists plugins from two folders - m_strDirectory (installed for
all users, inside the application) and m_strUserDirectory - but RemovePlugin
only ever looks in the user folder. For a plugin installed for all users it
returns false and changes nothing; that part is intended (the application
folder is not ours to write: Program Files, /opt, the signed macOS bundle) and
is kept. The plugin manager now reports that false (onlyoffice.github.io
store, see issue-2107-plugin-remove-ui-test.js).

The bug fixed here is the other direction: RemovePlugin claimed success when it
had not removed the plugin. It deleted file by file with
NSDirectory::DeleteDirectory, ignored the outcome and returned true. With a
user plugins folder the process cannot write, the plugin's files were deleted,
its empty folder stayed, and the editor was told "removed" - a half-removed
plugin, and with backup=false nothing left to restore. The backup branch also
had an inverted check (`if (!Exists) DeleteDirectory`), so an old backup of
the same plugin was never cleared and the new copy merged into it. Now the
folder is taken out with one rename first (nothing touched if refused), the
backup is a rename too, and false means nothing changed.

This compiles the real plugins.h (with utils.h and Logger.h from the same
tree) into a small driver linked against core's prebuilt kernel library, lays
out the folders the macOS app reads - <bundle>/Contents/Resources/editors/
sdkjs-plugins and <app data>/data/sdkjs-plugins, under a temp dir - and checks:
  1. a plugin installed for all users: RemovePlugin false, still listed;
  2. a user update (v2) over a system plugin (v1), backup: true, the system
     copy is listed again, the backup holds v2;
  3. a stale backup of the same plugin is replaced, not merged into;
  4/5. user plugins folder read-only, backup off/on: false, the plugin's files
     intact and still listed, no backup created;            <- FAILS on baseline
  6. writable again: true, folder gone, no temp folder left behind.
Checks 4/5 need a non-root user (root ignores the read-only mode); as root
they are skipped and the run says so.

Env:
  RD_REPO   desktop-sdk checkout (default ../../desktop-sdk)
  RD_CORE   core checkout with a built kernel lib (default ../../core);
            uses core/build/lib/<mac_arm64|mac_64|linux_64|linux_arm64>
  BASELINE=1  reads the three headers from BASE_REF via git show; must FAIL.

NOT claimed: Windows (MoveFileW branch not compiled here); the editor UI.
"""
import glob
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'ad09162a^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'
HEADERS = ['plugins.h', 'utils.h', 'Logger.h']

DRIVER = r'''
#include "desktop-sdk/ChromiumBasedEditors/lib/src/plugins.h"
#include <cstdio>
int main(int argc, char** argv)
{
	if (argc < 4) return 2;
	CPluginsManager m;
	m.m_strDirectory = UTF8_TO_U(std::string(argv[1]));
	m.m_strUserDirectory = UTF8_TO_U(std::string(argv[2]));
	std::string cmd = argv[3];
	if (cmd == "list") { printf("%s\n", m.GetPluginsJson(true, true).c_str()); return 0; }
	if (cmd == "remove" && argc >= 6)
	{
		bool r = m.RemovePlugin(UTF8_TO_U(std::string(argv[4])), std::string(argv[5]) == "1");
		printf("%s\n", r ? "true" : "false");
		return 0;
	}
	return 2;
}
'''

S1 = '{11111111-0000-0000-0000-000000000001}'
S2 = '{11111111-0000-0000-0000-000000000002}'
U3 = '{22222222-0000-0000-0000-000000000003}'


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def libdir():
    sysname = platform.system()
    arch = platform.machine()
    names = {('Darwin', 'arm64'): 'mac_arm64', ('Darwin', 'x86_64'): 'mac_64',
             ('Linux', 'x86_64'): 'linux_64', ('Linux', 'aarch64'): 'linux_arm64'}
    d = os.path.join(CORE, 'build', 'lib', names.get((sysname, arch), ''))
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
    subprocess.run(cmd, check=True)
    return exe


def mk(d, guid, name, version):
    os.makedirs(d)
    with open(os.path.join(d, 'config.json'), 'w') as f:
        json.dump({'name': name, 'guid': 'asc.' + guid, 'version': version,
                   'variations': [{'description': name, 'url': 'index.html', 'isVisual': True}]}, f, indent=1)
    with open(os.path.join(d, 'index.html'), 'w') as f:
        f.write('x')


def main():
    work = tempfile.mkdtemp(prefix='rd2107-')
    failures = []

    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what)
        if not ok:
            failures.append(what)

    try:
        exe = build(work)
        root = os.path.join(work, 'fx')
        sysd = os.path.join(root, 'Ration Docs.app/Contents/Resources/editors/sdkjs-plugins')
        usr = os.path.join(root, 'Library/Application Support/com.stackchase.rationdocs.test/data/sdkjs-plugins')
        mk(os.path.join(sysd, S1), S1, 'S1 system', '1.0.0')
        mk(os.path.join(sysd, S2), S2, 'S2 system', '1.0.0')
        mk(os.path.join(usr, S2), S2, 'S2 user update', '2.0.0')
        mk(os.path.join(usr, U3), U3, 'U3 user', '1.0.0')
        # an old backup of S2 with a file the new copy does not have
        os.makedirs(os.path.join(usr, 'backup', S2))
        with open(os.path.join(usr, 'backup', S2, 'stale.txt'), 'w') as f:
            f.write('old')

        def run(*a):
            return subprocess.run([exe, sysd, usr] + list(a), capture_output=True, text=True, check=True).stdout.strip()

        def listed():
            d = json.loads(run('list'))
            return [p['name'] for p in d[0]['pluginsData']], [p['name'] for p in d[1]['pluginsData']]

        s, u = listed()
        check(s == ['S1 system'] and sorted(u) == ['S2 user update', 'U3 user'], 'initial list %s / %s' % (s, u))

        r = run('remove', 'asc.' + S1, '0')
        s, u = listed()
        check(r == 'false' and 'S1 system' in s, '1. installed for all users: RemovePlugin=%s, still listed' % r)

        r = run('remove', 'asc.' + S2, '1')
        s, u = listed()
        check(r == 'true' and 'S2 system' in s and 'S2 user update' not in u,
              '2. user update removed (%s), system copy listed again: %s' % (r, s))
        bk = os.path.join(usr, 'backup', S2)
        ver = json.load(open(os.path.join(bk, 'config.json'))).get('version') if os.path.exists(os.path.join(bk, 'config.json')) else None
        check(ver == '2.0.0', '2. backup holds the removed v2 (%s)' % ver)
        check(not os.path.exists(os.path.join(bk, 'stale.txt')), '3. stale backup replaced, not merged into')

        if os.geteuid() == 0:
            print('skip 4/5: running as root, a read-only folder does not stop root')
        else:
            for backup in ('0', '1'):
                os.chmod(usr, stat.S_IRUSR | stat.S_IXUSR)
                try:
                    r = run('remove', 'asc.' + U3, backup)
                finally:
                    os.chmod(usr, stat.S_IRWXU)
                intact = sorted(os.listdir(os.path.join(usr, U3))) == ['config.json', 'index.html'] if os.path.isdir(os.path.join(usr, U3)) else False
                s, u = listed()
                n = '4' if backup == '0' else '5'
                check(r == 'false', '%s. read-only user folder, backup=%s: RemovePlugin=%s (must not claim success)' % (n, backup, r))
                check(intact and 'U3 user' in u, '%s. plugin files intact and still listed (%s)' % (n, u))
                check(not os.path.exists(os.path.join(usr, 'backup', U3)), '%s. no backup made of a plugin that stayed' % n)

        r = run('remove', 'asc.' + U3, '0')
        s, u = listed()
        left = sorted(e for e in os.listdir(usr) if e != 'backup')
        check(r == 'true' and 'U3 user' not in u and left == [], '6. writable: removed (%s), folder left: %s' % (r, left))
    finally:
        for p in glob.glob(os.path.join(work, '**'), recursive=True):
            try:
                os.chmod(p, stat.S_IRWXU)
            except OSError:
                pass
        shutil.rmtree(work, ignore_errors=True)

    tag = ' [BASELINE %s]' % BASE_REF if BASELINE else ''
    if failures:
        print('FAIL #2107 native: %d check(s) failed%s' % (len(failures), tag))
        sys.exit(1)
    print('PASS #2107 native: RemovePlugin reports what it did%s' % tag)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
#1967 - "Option to disable Plugins via config for managed devices": an
administrator wants to switch plugins off for every user of a machine (all of
them, some of them, or only the plugin manager/store), from a machine-wide
configuration rather than per user.

Before: nothing machine-wide reached the plugin lists. desktop-sdk's
CPluginsManager::GetDisableGUIDS() (plugins.h) filters every list, but only the
per-user disable-ai setting ever filled it; plugins_support=false existed but
on macOS nothing set it, and on Windows/Linux only an undocumented, inverted
registry value did.

Now desktop-sdk plugins_policy.h/.cpp reads DisablePlugins,
DisablePluginManager and DisabledPluginGUIDs once in the browser process
(cefapplication.cpp Init_CEF) from the platform's managed-settings place - on
macOS the app's preferences domain via CFPreferences, which is where a
configuration profile lands - fills GetDisableGUIDS(), and hands the result to
the renderer as startup properties (applicationmanager.cpp
GetRendererStartupProperties: "disabled-plugins", "plugins_support=false"),
where client_renderer_wrapper.cpp adds the GUIDs to the renderer's own set
before GetInstallPlugins lists anything.

This test compiles the real plugins.h / plugins_policy.{h,cpp} /
client_renderer_params.h into a small driver, together with the statements
extracted (by marker) from Init_CEF, GetRendererStartupProperties and the
renderer's startup, and runs it as both processes would: browser state ->
startup properties -> a cleared renderer state -> GetInstallPlugins' list.
The driver carries an embedded Info.plist whose bundle id is a TEMPORARY
preferences domain (com.stackchase.rationdocs.policytest.<pid>), so the
production NSPluginsPolicy::Load() reads it exactly as the app reads its own
domain. Values are written there with `defaults write`, and the domain is
deleted afterwards. The real app's domain is never touched.

Checks (macOS):
  1. no policy: every plugin is listed, no policy property is sent;
  2. DisablePluginManager + DisabledPluginGUIDs (array, "asc." prefix, lower
     case): the plugin manager and that plugin are missing from the
     renderer's list, the rest stay;                     <- FAILS on baseline
  3. DisabledPluginGUIDs as one string "{A};{B}": both missing;  <- baseline
  4. DisablePlugins: plugins_support=false reaches the renderer and its list
     is empty;                                           <- FAILS on baseline
  5. the Linux file format (ParseConfig) gives the same policy, and with
     DisablePluginManager CanInstallPlugins() is false (applicationmanager.cpp
     refuses ADD_PLUGIN / InstallPluginFromStore then);
  6. with only a GUID list, installing stays allowed.
On baseline the policy files do not exist; the driver is built from the old
plugins.h with the marker segments empty, i.e. what the app did then.

Env:
  RD_REPO   desktop-sdk checkout (default ../../desktop-sdk)
  RD_CORE   core checkout with a built kernel lib (default ../../core)
  BASELINE=1  reads sources from BASE_REF via git show; must FAIL.

NOT claimed: the Windows registry reader and the Linux file reader (not
compiled here - only ParseConfig, which the Linux reader feeds); a real
configuration profile (CFPreferences gives managed values precedence; here
the value is an ordinary user-domain value); the web-apps Plugins tab, which
is not changed - it is only shown when the list GetInstallPlugins returns has
a visible plugin (web-apps common/main/lib/controller/Plugins.js
refreshPluginsList / onResetPlugins).
"""
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
# Pinned to the parent of the commit that landed the fix, never HEAD.
BASE_REF = os.environ.get('BASE_REF', 'df192078^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'
HEADERS = ['plugins.h', 'utils.h', 'Logger.h', 'cefwrapper/client_renderer_params.h']
POLICY = ['plugins_policy.h', 'plugins_policy.cpp']

MANAGER = '{AA2EA9B6-9EC2-415F-9762-634EE8D9A95E}'
S1 = '{1967AAAA-0000-4000-8000-0000000000A1}'
S2 = '{1967BBBB-0000-4000-8000-0000000000B2}'
U3 = '{1967CCCC-0000-4000-8000-0000000000C3}'

DRIVER = r'''
#include "desktop-sdk/ChromiumBasedEditors/lib/src/plugins.h"
#include "desktop-sdk/ChromiumBasedEditors/lib/src/cefwrapper/client_renderer_params.h"
#include <cstdio>

static std::vector<std::string> BrowserProcess()
{
	// cefapplication.cpp, CApplicationCEF::Init_CEF
	@@INIT@@

	// applicationmanager.cpp, CAscApplicationManager::GetRendererStartupProperties (tail)
	struct { bool plugins_support; } m_oSettings = { true };
	std::vector<std::string> props;
	@@PROPS@@
	return props;
}

int main(int argc, char** argv)
{
	if (argc < 3) return 2;
	std::vector<std::string> props = BrowserProcess();

	// the renderer is another process: nothing of the browser's state
	CPluginsManager::GetDisableGUIDS().clear();
	CAscRendererProcessParams& default_params = CAscRendererProcessParams::getInstance();
	default_params.Check(props);
	bool m_bIsPluginsSupport = true;

	// client_renderer_wrapper.cpp, CAscEditorNativeV8Handler constructor
	@@RENDERER@@

	// client_renderer_wrapper.cpp, "GetInstallPlugins"
	CPluginsManager oPlugins;
	oPlugins.m_strDirectory = UTF8_TO_U(std::string(argv[1]));
	oPlugins.m_strUserDirectory = UTF8_TO_U(std::string(argv[2]));
	std::string sData = oPlugins.GetPluginsJson(true, true, true, m_bIsPluginsSupport);

	std::string sProps = "[";
	for (size_t i = 0; i < props.size(); ++i)
		sProps += (i ? ",\"" : "\"") + props[i] + "\"";
	sProps += "]";
	printf("{\"props\": %s, \"plugins\": %s}\n", sProps.c_str(), sData.c_str());
	return 0;
}
'''

CONF_DRIVER = r'''
#include "desktop-sdk/ChromiumBasedEditors/lib/src/plugins_policy.h"
#include <cstdio>
#include <fstream>
#include <sstream>
int main(int argc, char** argv)
{
	std::ifstream f(argv[1]); std::stringstream s; s << f.rdbuf();
	NSPluginsPolicy::CPolicy p;
	NSPluginsPolicy::ParseConfig(s.str(), p);
	std::set<std::string> g = NSPluginsPolicy::GetDisabledGuids(p);
	printf("{\"DisablePlugins\": %s, \"DisablePluginManager\": %s, \"guids\": [", p.DisablePlugins ? "true" : "false", p.DisablePluginManager ? "true" : "false");
	int n = 0;
	for (std::set<std::string>::iterator i = g.begin(); i != g.end(); ++i)
		printf("%s\"%s\"", n++ ? "," : "", i->c_str());
	printf("], \"canInstall\": %s}\n", NSPluginsPolicy::CanInstallPlugins(p) ? "true" : "false");
	return 0;
}
'''


def read(rel, missing_ok=False):
    if BASELINE:
        r = subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)], capture_output=True, text=True)
        if r.returncode != 0:
            if missing_ok:
                return None
            sys.exit('git show %s:%s failed: %s' % (BASE_REF, rel, r.stderr.strip()))
        return r.stdout
    p = os.path.join(REPO, rel)
    if missing_ok and not os.path.exists(p):
        return None
    return open(p, encoding='utf-8').read()


def segment(text, start, end, inclusive_end=True):
    """The source from the line holding `start` to the line holding `end`."""
    if text is None:
        return ''
    a = text.find(start)
    if a < 0:
        return ''
    a = text.rfind('\n', 0, a) + 1
    b = text.find(end, a)
    if b < 0:
        sys.exit('marker %r not found after %r' % (end, start))
    b = text.find('\n', b) if inclusive_end else text.rfind('\n', 0, b)
    return text[a:b]


def libdir():
    names = {('Darwin', 'arm64'): 'mac_arm64', ('Darwin', 'x86_64'): 'mac_64'}
    d = os.path.join(CORE, 'build', 'lib', names.get((platform.system(), platform.machine()), ''))
    if not os.path.isdir(d):
        sys.exit('core kernel lib not built: %s' % d)
    return d


def build(work, domain):
    inc = os.path.join(work, 'inc')
    dst = os.path.join(inc, 'desktop-sdk', SRC)
    os.makedirs(os.path.join(dst, 'cefwrapper'))
    for h in HEADERS:
        with open(os.path.join(dst, h), 'w', encoding='utf-8') as f:
            f.write(read(SRC + h))
    have_policy = True
    for p in POLICY:
        t = read(SRC + p, missing_ok=True)
        if t is None:
            have_policy = False
            continue
        with open(os.path.join(dst, p), 'w', encoding='utf-8') as f:
            f.write(t)
    os.symlink(CORE, os.path.join(inc, 'core'))

    cef = read(SRC + 'cefapplication.cpp')
    app = read(SRC + 'applicationmanager.cpp')
    rnd = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp')
    init = segment(cef, 'NSPluginsPolicy::Load()', 'CPluginsManager::DisableByPolicy')
    props = segment(app, 'NSPluginsPolicy::CPolicy& oPluginsPolicy = NSPluginsPolicy::Get()', 'return props;', inclusive_end=False)
    if not props:
        # baseline: the plugins_support line as it was
        props = segment(app, 'if (!m_oSettings.plugins_support)', 'props.push_back("plugins_support=false")')
    renderer = segment(rnd, 'if ("false" == default_params.GetValue("plugins_support"))', 'm_bIsPluginsSupport = false;')
    renderer += '\n' + segment(rnd, 'default_params.GetValue("disabled-plugins")', 'default_params.GetValue("disabled-plugins")')
    src = DRIVER.replace('@@INIT@@', init).replace('@@PROPS@@', props).replace('@@RENDERER@@', renderer)
    print('extracted: init %d, props %d, renderer %d lines%s' % (
        len(init.splitlines()), len(props.splitlines()), len(renderer.strip().splitlines()),
        '' if have_policy else ' (no plugins_policy.* at this ref)'))

    plist = os.path.join(work, 'Info.plist')
    with open(plist, 'wb') as f:
        plistlib.dump({'CFBundleIdentifier': domain, 'CFBundleName': 'rd1967'}, f)
    cpp = os.path.join(work, 'drv.cpp')
    with open(cpp, 'w') as f:
        f.write(src)
    lib = libdir()
    exe = os.path.join(work, 'drv')
    cmd = ['clang++', '-std=c++14', '-w', '-I' + inc, cpp]
    if have_policy:
        cmd.append(os.path.join(dst, 'plugins_policy.cpp'))
    cmd += ['-o', exe, '-D_MAC', '-DMAC', '-D_UNIX', '-DUNIX', '-F' + lib, '-framework', 'kernel',
            '-framework', 'CoreFoundation', '-Wl,-rpath,' + lib, '-Wl,-sectcreate,__TEXT,__info_plist,' + plist]
    subprocess.run(cmd, check=True)

    conf = None
    if have_policy:
        ccpp = os.path.join(work, 'conf.cpp')
        with open(ccpp, 'w') as f:
            f.write(CONF_DRIVER)
        conf = os.path.join(work, 'conf')
        subprocess.run(['clang++', '-std=c++14', '-w', '-I' + inc, ccpp, os.path.join(dst, 'plugins_policy.cpp'),
                        '-o', conf, '-framework', 'CoreFoundation'], check=True)
    return exe, conf


def mk(d, guid, name):
    os.makedirs(d)
    with open(os.path.join(d, 'config.json'), 'w') as f:
        json.dump({'name': name, 'guid': 'asc.' + guid, 'version': '1.0.0',
                   'variations': [{'description': name, 'url': 'index.html', 'isVisual': True}]}, f, indent=1)


def main():
    if platform.system() != 'Darwin':
        sys.exit('macOS only (CFPreferences reader)')
    domain = 'com.stackchase.rationdocs.policytest.%d' % os.getpid()
    work = tempfile.mkdtemp(prefix='rd1967-')
    failures = []

    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what)
        if not ok:
            failures.append(what)

    def defaults(*a):
        subprocess.run(['defaults'] + list(a), check=True, capture_output=True)

    def clear():
        subprocess.run(['defaults', 'delete', domain], capture_output=True)

    try:
        exe, conf = build(work, domain)
        sysd = os.path.join(work, 'fx', 'Ration Docs.app/Contents/Resources/editors/sdkjs-plugins')
        usr = os.path.join(work, 'fx', 'Library/Application Support/com.stackchase.rationdocs.test/data/sdkjs-plugins')
        mk(os.path.join(sysd, MANAGER), MANAGER, 'Plugin Manager')
        mk(os.path.join(sysd, S1), S1, 'S1')
        mk(os.path.join(sysd, S2), S2, 'S2')
        mk(os.path.join(usr, U3), U3, 'U3')

        def run():
            out = json.loads(subprocess.run([exe, sysd, usr], capture_output=True, text=True, check=True).stdout)
            names = sorted(p['name'] for part in out['plugins'] for p in part['pluginsData'])
            return out['props'], names

        clear()
        props, names = run()
        check(names == ['Plugin Manager', 'S1', 'S2', 'U3'] and props == [],
              '1. no policy: all listed %s, policy props %s' % (names, props))

        defaults('write', domain, 'DisablePluginManager', '-bool', 'true')
        # -array items are parsed as property lists: a "{...}" needs quotes
        defaults('write', domain, 'DisabledPluginGUIDs', '-array', '"asc.%s"' % S1.lower(), 'NOT-INSTALLED')
        props, names = run()
        check(names == ['S2', 'U3'], '2. manager + S1 (array, asc., lower case) disabled: renderer lists %s' % names)
        check('plugins_support=false' not in props, '2. plugins themselves stay on (props %s)' % props)

        clear()
        defaults('write', domain, 'DisabledPluginGUIDs', '-string', '%s;%s' % (S2, U3))
        props, names = run()
        check(names == ['Plugin Manager', 'S1'], '3. "{S2};{U3}" as one string: renderer lists %s' % names)

        clear()
        defaults('write', domain, 'DisablePlugins', '-bool', 'true')
        props, names = run()
        check('plugins_support=false' in props, '4. DisablePlugins: plugins_support=false sent (%s)' % props)
        check(names == [], '4. DisablePlugins: renderer lists nothing (%s)' % names)

        if conf is None:
            check(False, '5. Linux file format: no plugins_policy at this ref')
        else:
            cf = os.path.join(work, 'policy.conf')
            with open(cf, 'w') as f:
                f.write('# Ration Docs plugin policy\nDisablePlugins = no\nDisablePluginManager=1\n'
                        'DisabledPluginGUIDs="asc.%s, %s"\n' % (S1.lower(), S2))
            got = json.loads(subprocess.run([conf, cf], capture_output=True, text=True, check=True).stdout)
            check(got == {'DisablePlugins': False, 'DisablePluginManager': True, 'guids': sorted([MANAGER, S1, S2]),
                          'canInstall': False}, '5. Linux policy.conf parsed: %s' % got)
            with open(cf, 'w') as f:
                f.write('DisabledPluginGUIDs=%s\n' % S1)
            got = json.loads(subprocess.run([conf, cf], capture_output=True, text=True, check=True).stdout)
            check(got['canInstall'] is True, '6. only a GUID list: users may still add plugins (%s)' % got)
    finally:
        clear()
        try:
            os.remove(os.path.expanduser('~/Library/Preferences/%s.plist' % domain))
        except OSError:
            pass
        shutil.rmtree(work, ignore_errors=True)

    tag = ' [BASELINE %s]' % BASE_REF if BASELINE else ''
    if failures:
        print('FAIL #1967: %d check(s) failed%s' % (len(failures), tag))
        sys.exit(1)
    print('PASS #1967: the machine-wide plugin policy reaches the renderer\'s plugin list%s' % tag)


if __name__ == '__main__':
    main()

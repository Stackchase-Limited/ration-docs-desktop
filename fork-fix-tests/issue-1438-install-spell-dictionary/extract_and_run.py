#!/usr/bin/env python3
"""
#1438 - "Adding new spellcheckers for other languages through GUI".

The desktop spell checker (desktop-sdk spellchecker.cpp, browser process) knew
only the dictionaries in <app>/dictionaries (plus, since #195, the
distribution's on Linux). A new language meant copying files into the
application folder - impossible in a Snap, a signed macOS bundle or as a
non-admin Windows user.

Now Settings > "Add spelling dictionary..." (desktop-apps start page) opens the
app's file dialog and calls AscDesktopEditor.InstallSpellCheckDictionary(path)
(renderer, client_renderer_wrapper.cpp; only for a file picked in a dialog).
That runs NSSpellDictionaries::Install (new spell_dictionaries.h): the .dic and
.aff must both be there, the file name gives the language (de_CH, pt-BR,
de_DE_frami -> de_DE), only "SET UTF-8" affix files, copied to
<user dictionaries>/installed/<lang>_<REGION>.{aff,dic}. The browser process
then has the spell checker re-register that folder on its own thread
(AddInstalledDictionaries), where an added dictionary wins for its language.

This compiles the REAL spell_dictionaries.h and the REAL
AddInstalledDictionaries/SetLanguage methods (brace-matched out of
spellchecker.cpp into a stub holding the same maps) against core's prebuilt
kernel and hunspell libraries, and checks:
  1. a UTF-8 pair named de_CH_frami is installed as de_CH (LCID 0x0807);
  2. refused: a lone .dic, a name without a region (xx.dic), a non-UTF-8 one;
  3. after the spell checker registers the folder, Hunspell knows a word only
     the added dictionary has (and not an unknown one) for LCID 0x0807;
  4. an added dictionary replaces one registered (and loaded) before for its
     language;
  5. wiring (presence only): the renderer function is listed and gated by
     IsFileFromDialog, the browser message reloads the spell checker, the
     start page has the button.
Env:
  RD_REPO   desktop-sdk checkout (default ../../desktop-sdk)
  RD_APPS   desktop-apps checkout (default ../../desktop-apps)
  RD_CORE   core checkout with built kernel + hunspell (default ../../core)
  BASELINE=1  reads sources at BASE_REF / APPS_BASE_REF via git show; must FAIL.
NOT claimed: the file dialog, the renderer->browser message at run time, an
editor actually underlining with the new dictionary (needs a GUI check),
Windows (not compiled here).
"""
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
APPS = os.environ.get('RD_APPS') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-apps'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
# Pinned to the parents of the commits that landed the feature, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '4efb34f6^')
APPS_BASE_REF = os.environ.get('APPS_BASE_REF', '3fb2865cc^')
BASELINE = bool(os.environ.get('BASELINE'))
SRC = 'ChromiumBasedEditors/lib/src/'


def git_show(repo, ref, rel):
    r = subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (ref, rel)], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def read(rel, repo=None, ref=None):
    repo = repo or REPO
    if BASELINE:
        return git_show(repo, ref or BASE_REF, rel)
    p = os.path.join(repo, rel)
    return open(p, encoding='utf-8').read() if os.path.exists(p) else None


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


DRIVER = r'''
#include "desktop-sdk/ChromiumBasedEditors/lib/src/spell_dictionaries.h"
#include "core/Common/3dParty/hunspell/hunspell/src/hunspell/hunspell.h"
#include <cstdio>
#ifndef U_TO_UTF8
#define U_TO_UTF8(val) NSFile::CUtf8Converter::GetUtf8StringFromUnicode2(val.c_str(), (LONG)val.length())
#endif
#ifndef UTF8_TO_U
#define UTF8_TO_U(val) NSFile::CUtf8Converter::GetUnicodeStringFromUTF8((BYTE*)val.c_str(), (LONG)val.length())
#endif
struct CSpell
{
	class CDictionaryFiles { public: std::string path_aff; std::string path_dic; };
	std::map<int, Hunhandle*>       m_map_dictionaries;
	std::map<int, CDictionaryFiles> m_map_dictionaries_files;
	std::wstring                    m_sUserDictionaries;
	%(ADD)s
	%(SET)s
};
static std::wstring W(const char* s) { std::string a(s); return UTF8_TO_U(a); }
int main(int argc, char** argv)
{
	std::string cmd = argv[1];
	if (cmd == "install")
	{
		std::wstring sTag;
		int r = (int)NSSpellDictionaries::Install(W(argv[2]), W(argv[3]), sTag);
		printf("%%d %%s\n", r, U_TO_UTF8(sTag).c_str());
		return 0;
	}
	if (cmd == "spell") // spell <userdir> <lcid> <word> [<shipped aff> <shipped dic> <word2>]
	{
		CSpell s;
		s.m_sUserDictionaries = W(argv[2]);
		int lcid = atoi(argv[3]);
		if (argc > 7)
		{
			// a dictionary registered (and loaded) before, as Init does for ours
			CSpell::CDictionaryFiles f; f.path_aff = argv[5]; f.path_dic = argv[6];
			s.m_map_dictionaries_files[lcid] = f;
			Hunhandle* h = s.SetLanguage(lcid);
			printf("before:%%d ", h ? Hunspell_spell(h, argv[7]) : -1);
		}
		s.AddInstalledDictionaries();
		Hunhandle* h = s.SetLanguage(lcid);
		printf("%%d\n", h ? Hunspell_spell(h, argv[4]) : -1);
		return 0;
	}
	return 2;
}
'''


def libdir():
    names = {('Darwin', 'arm64'): 'mac_arm64', ('Darwin', 'x86_64'): 'mac_64',
             ('Linux', 'x86_64'): 'linux_64', ('Linux', 'aarch64'): 'linux_arm64'}
    d = os.path.join(CORE, 'build', 'lib', names.get((platform.system(), platform.machine()), ''))
    if not os.path.isdir(d):
        sys.exit('core libs not built: %s' % d)
    return d


def build(work):
    header = read(SRC + 'spell_dictionaries.h')
    sc = read(SRC + 'spellchecker.cpp')
    if header is None:
        return None, 'no spell_dictionaries.h'
    add = block(sc, 'void AddInstalledDictionaries()')
    setl = block(sc, 'Hunhandle* SetLanguage(const int& nLang)')
    if not add or not setl:
        return None, 'AddInstalledDictionaries/SetLanguage not found in spellchecker.cpp'
    inc = os.path.join(work, 'inc')
    dst = os.path.join(inc, 'desktop-sdk', SRC)
    os.makedirs(dst)
    with open(os.path.join(dst, 'spell_dictionaries.h'), 'w', encoding='utf-8') as f:
        f.write(header)
    os.symlink(CORE, os.path.join(inc, 'core'))
    cpp = os.path.join(work, 'drv.cpp')
    with open(cpp, 'w') as f:
        f.write(DRIVER % {'ADD': add, 'SET': setl})
    exe = os.path.join(work, 'drv')
    lib = libdir()
    cmd = ['clang++' if shutil.which('clang++') else 'g++', '-std=c++14', '-w', '-I' + inc, cpp, '-o', exe]
    if platform.system() == 'Darwin':
        cmd += ['-D_MAC', '-DMAC', '-D_UNIX', '-DUNIX', '-F' + lib, '-framework', 'kernel', '-framework', 'hunspell',
                '-Wl,-rpath,' + lib]
    else:
        cmd += ['-D_LINUX', '-DLINUX', '-D_UNIX', '-DUNIX', '-L' + lib, '-lkernel', '-lhunspell', '-Wl,-rpath,' + lib]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        return None, r.stderr.strip().splitlines()[:3]
    return exe, None


def write_dict(folder, name, words, charset='UTF-8'):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name + '.aff'), 'w', encoding='utf-8') as f:
        f.write('SET %s\nTRY abcdefghijklmnopqrstuvwxyz\n' % charset)
    with open(os.path.join(folder, name + '.dic'), 'w', encoding='utf-8') as f:
        f.write('%d\n%s\n' % (len(words), '\n'.join(words)))
    return os.path.join(folder, name + '.dic')


def main():
    work = tempfile.mkdtemp(prefix='rd1438-')
    failures = []

    def check(ok, what):
        print(('ok   ' if ok else 'FAIL ') + what)
        if not ok:
            failures.append(what)

    try:
        exe, err = build(work)
        check(exe is not None, 'spell_dictionaries.h and the spell checker methods compile (%s)' % (err or 'built'))
        if exe:
            pick = os.path.join(work, 'Downloads')
            user = os.path.join(work, 'appdata', 'data', 'dictionaries')

            def run(*a):
                return subprocess.run([exe] + list(a), capture_output=True, text=True, check=True).stdout.strip()

            dic = write_dict(pick, 'de_CH_frami', ['Grüezi', 'Velo'])
            r = run('install', dic, user)
            inst = os.path.join(user, 'installed')
            check(r == '0 de_CH' and sorted(os.listdir(inst)) == ['de_CH.aff', 'de_CH.dic'],
                  '1. de_CH_frami.dic installed as de_CH (%s, %s)' % (r, sorted(os.listdir(inst)) if os.path.isdir(inst) else '-'))

            lone = os.path.join(pick, 'fr_CA.dic')
            open(lone, 'w').write('1\nbonjour\n')
            check(run('install', lone, user).split()[0] == '1', '2. a .dic without its .aff is refused (pair)')
            check(run('install', write_dict(pick, 'xx', ['a']), user).split()[0] == '2', '2. a name without a region is refused (name)')
            check(run('install', write_dict(pick, 'is_IS', ['halló'], 'ISO8859-1'), user).split()[0] == '3',
                  '2. a non-UTF-8 dictionary is refused (encoding)')
            check(sorted(os.listdir(inst)) == ['de_CH.aff', 'de_CH.dic'], '2. nothing else was copied')

            lcid = str(0x0807)
            r = run('spell', user, lcid, 'Grüezi')
            check(r == '1', '3. Hunspell knows "Grüezi" for de-CH from the added dictionary (%s)' % r)
            r = run('spell', user, lcid, 'Xylofonkatze')
            check(r == '0', '3. and an unknown word is wrong (%s)' % r)

            shipped = os.path.join(work, 'app', 'dictionaries', 'de_CH')
            write_dict(shipped, 'de_CH', ['Hallo'])
            r = run('spell', user, lcid, 'Grüezi', os.path.join(shipped, 'de_CH.aff'), os.path.join(shipped, 'de_CH.dic'), 'Hallo')
            check(r == 'before:1 1', '4. an added dictionary replaces one registered and loaded before (%s)' % r)

        # 5. wiring, presence only
        rw = read(SRC + 'cefwrapper/client_renderer_wrapper.cpp') or ''
        cv = read(SRC + 'cefview.cpp') or ''
        ps = read('common/loginpage/src/panelsettings.js', APPS, APPS_BASE_REF) or ''
        fn = block(rw, 'else if (name == "InstallSpellCheckDictionary")') or ''
        listed = '"InstallSpellCheckDictionary",' in rw
        check(listed and 'IsFileFromDialog' in fn and 'spell_dictionaries_changed' in fn,
              '5. renderer InstallSpellCheckDictionary listed, only for dialog-picked files')
        check('spell_dictionaries_changed' in cv and 'ReloadInstalledDictionaries' in cv,
              '5. the browser process reloads the spell checker on "spell_dictionaries_changed"')
        check('InstallSpellCheckDictionary' in ps and "OpenFilenameDialog('*.dic *.aff'" in ps,
              '5. the start page offers "Add spelling dictionary..."')
    finally:
        shutil.rmtree(work, ignore_errors=True)

    tag = ' [BASELINE %s / %s]' % (BASE_REF, APPS_BASE_REF) if BASELINE else ''
    if failures:
        print('FAIL #1438: %d check(s) failed%s' % (len(failures), tag))
        sys.exit(1)
    print('PASS #1438: a Hunspell pair is installed from a picked file and used for its language%s' % tag)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
#195 - "Integrate Dictionary with system dictionary on Ubuntu/Linux": the
desktop spell checker used only the dictionaries shipped with the app, so a
language the app ships none for (Icelandic, Canadian/Swiss French, Austrian
and Luxembourg German, ...) was never checked on Linux even when the
distribution had installed hunspell dictionaries for it.

Cause: desktop-sdk ChromiumBasedEditors/lib/src/spellchecker.cpp
CAscSpellChecker_Private::Init registers <app>/dictionaries/<name>/<name>.aff
for the names in core's hunspell autogen/records.h and nothing else; a word in
a language without an entry is answered "correct" (SetLanguage -> NULL).
Fix: on Linux, Init also scans /usr/share/hunspell, /usr/share/myspell/dicts
and /usr/share/myspell (AddSystemDictionaries): <lang>_<REGION>.aff/.dic
(symlinks too) whose tag is a known LCID (core's MS-LCID.h) and that has no
dictionary of ours is registered; ours always win. Only "SET UTF-8"
dictionaries are used, since the editors send UTF-8 and hunspell takes words
in the dictionary's encoding.

This compiles the REAL CJsonTextItem, CJsonSpellParser and
CAscSpellChecker_Private (spellchecker.cpp) and CPluginsManager's real JSON
helpers (plugins.h) against core headers, the app's kernel.framework and real
hunspell.framework, with stubs only for the app manager event plumbing (as
issue-0630-remove-from-dictionary). Two edits are made to the extracted text,
both test plumbing: the Linux-only guard around the scan is opened (this runs
on macOS) and the three system folders are pointed at a temp folder holding:
is_IS (UTF-8, a language we ship none for), fr_CA.aff -> fr.aff symlinks,
de_DE (we ship one: must not replace ours), et_EE with SET ISO8859-1 (must be
skipped). It then sends real "spell" tasks through AddTask/OnTimer.

Claimed: Icelandic and fr-CA words are checked against the system
dictionaries (known word correct, garbage wrong); our de_DE still answers for
de-DE; the ISO8859-1 one is not used (Estonian stays unchecked, as before).
With RD_SYSTEM_DICTS=<dir> the is-IS/fr-CA checks run against a real distro
folder instead (e.g. Ubuntu 24.04's hunspell-is and hunspell-fr-classical).
NOT claimed: a Linux run of the app (macOS-built test; the TU was syntax-
compiled for Linux), languages whose tag MS-LCID.h does not know.

  RD_REPO     desktop-sdk checkout (default ../../desktop-sdk)
  RD_CORE     core checkout for headers (default ../../core)
  RD_PAYLOAD  app payload with kernel/UnicodeConverter/hunspell frameworks
  BASELINE=1  reads spellchecker.cpp from BASE_REF (parent of the fix): FAILS.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
CORE = os.environ.get('RD_CORE') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
PAYLOAD = os.environ.get('RD_PAYLOAD', '/Users/osindero/dev/active/rationdocs/.rd-work/payload')
SPELL = 'ChromiumBasedEditors/lib/src/spellchecker.cpp'
PLUGINS = 'ChromiumBasedEditors/lib/src/plugins.h'
# Pinned to the parent of the fix commit, never HEAD.
BASE_REF = os.environ.get('BASE_REF', '7e446b0c^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    return open(os.path.join(REPO, rel), encoding='utf-8').read()


def block(text, start):
    """From start to the brace closing the first '{', skipping string/char literals and comments."""
    i = text.index('{', start)
    depth = 0
    while True:
        c = text[i]
        if c in '"\'':
            j = i + 1
            while text[j] != c:
                j += 2 if text[j] == '\\' else 1
            i = j
        elif text.startswith('//', i):
            i = text.index('\n', i)
        elif text.startswith('/*', i):
            i = text.index('*/', i) + 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1


def cls(text, name):
    at = text.index('class ' + name)
    return block(text, at) + ';\n'


def method(text, sig):
    return block(text, text.index(sig)) + '\n'


spell = read(SPELL)


def spell_dictionaries():
    """spell_dictionaries.h (#1438, desktop-sdk e2d1d5ed), which spellchecker.cpp includes since then,
    inlined with core paths made absolute; nothing before it."""
    if '#include "./spell_dictionaries.h"' not in spell:
        return ''
    return read('ChromiumBasedEditors/lib/src/spell_dictionaries.h').replace('"../../../../core/', '"%s/' % CORE)
plugins = read(PLUGINS)
records = os.path.join(CORE, 'Common/3dParty/hunspell/autogen/records.h')

tmp = tempfile.mkdtemp(prefix='rd195-')
sysdir = os.environ.get('RD_SYSTEM_DICTS') or os.path.join(tmp, 'system')
private = cls(spell, 'CAscSpellChecker_Private').replace(
    '"../../../../core/Common/3dParty/hunspell/autogen/records.h"', '"%s"' % records)
# test plumbing only: run the Linux-only scan here, on the temp folder
private = private.replace('#if defined(_LINUX) && !defined(_MAC)', '#if 1')
for d in ('/usr/share/hunspell', '/usr/share/myspell/dicts', '/usr/share/myspell'):
    private = private.replace('"%s"' % d, '"%s"' % sysdir)

src = r'''
#include <string>
#include <list>
#include <map>
#include <vector>
#include <algorithm>
#include <iostream>
#include "%(core)s/DesktopEditor/common/File.h"
#include "%(core)s/DesktopEditor/common/Directory.h"
#include "%(core)s/DesktopEditor/graphics/TemporaryCS.h"
#include "%(core)s/DesktopEditor/graphics/Timer.h"
#include "%(core)s/Common/3dParty/hunspell/hunspell/src/hunspell/hunspell.h"
#include <dirent.h>
#include "%(core)s/Common/MS-LCID.h"
%(spelldict)s

typedef long long int_64_type;
#define ASC_MENU_EVENT_TYPE_CEF_SPELLCHECK 1
namespace NSEditorApi {
	struct CAscSpellCheckType {
		std::string r; void put_EditorId(int) {} void put_FrameId(int_64_type) {} void put_Result(const std::string& s) { r = s; }
	};
	struct CAscMenuEvent { void* m_pData = nullptr; int m_nType = 0; };
}
static std::vector<std::string> g_answers;
struct CAscApplicationManager {
	void Apply(NSEditorApi::CAscMenuEvent* e) {
		auto* d = (NSEditorApi::CAscSpellCheckType*)e->m_pData; g_answers.push_back(d->r); delete d; delete e;
	}
};
class CPluginsManager {
public:
%(getstr)s
%(getarr)s
};
%(textitem)s
%(parser)s
%(private)s

int main(int argc, char** argv) {
	std::wstring dicts = NSFile::CUtf8Converter::GetUnicodeStringFromUTF8((BYTE*)argv[1], (LONG)strlen(argv[1]));
	std::wstring user = NSFile::CUtf8Converter::GetUnicodeStringFromUTF8((BYTE*)argv[2], (LONG)strlen(argv[2]));
	CAscSpellChecker_Private p;
	CAscApplicationManager m;
	p.m_pManager = (decltype(p.m_pManager))&m;
	p.Init(dicts, user);
	for (int i = 3; i < argc; ++i) {
		std::string task = argv[i];
		if (0 == task.find("spell:")) {
			std::string w = task.substr(6);
			std::cout << "SPELL " << w << " " << (p.m_pUserAllDict && Hunspell_spell(p.m_pUserAllDict, w.c_str()) ? 1 : 0) << std::endl;
			continue;
		}
		g_answers.clear();
		p.AddTask(1, task, 1);
		p.OnTimer();
		std::cout << "ANSWER " << (g_answers.empty() ? std::string("<none>") : g_answers[0]) << std::endl;
	}
	return 0;
}
''' % dict(core=CORE, spelldict=spell_dictionaries(),
           getstr=method(plugins, 'static std::string GetStringValue('),
           getarr=method(plugins, 'static std::string GetArrayValue('),
           textitem=cls(spell, 'CJsonTextItem'),
           parser=cls(spell, 'CJsonSpellParser'),
           private=private)

failed = []


def check(cond, msg):
    print(('ok   - ' if cond else 'FAIL - ') + msg)
    if not cond:
        failed.append(msg)


def w(path, text, enc='utf-8'):
    with open(path, 'wb') as f:
        f.write(text.encode(enc))


try:
    cpp = os.path.join(tmp, 't.cpp')
    open(cpp, 'w').write(src)
    exe = os.path.join(tmp, 't')
    fw = os.path.join(PAYLOAD, 'converter')
    cmd = ['clang++', '-std=gnu++17', '-w', '-D_MAC', '-DMAC', '-DLINUX', '-D_LINUX', '-o', exe, cpp,
           '-F', fw, '-F', PAYLOAD, '-framework', 'kernel', '-framework', 'hunspell',
           '-Wl,-rpath,' + fw, '-Wl,-rpath,' + PAYLOAD]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-3000:])
        sys.exit('compile failed')
    # "ours": a de_DE that knows only "Ourword"
    dicts = os.path.join(tmp, 'dicts')
    os.makedirs(os.path.join(dicts, 'de_DE'))
    w(os.path.join(dicts, 'de_DE', 'de_DE.aff'), 'SET UTF-8\n')
    w(os.path.join(dicts, 'de_DE', 'de_DE.dic'), '1\nOurword\n')
    real = bool(os.environ.get('RD_SYSTEM_DICTS'))
    if not real:
        os.makedirs(sysdir)
        w(os.path.join(sysdir, 'is_IS.aff'), '# Icelandic\nSET UTF-8\nTRY aeiou\n')
        w(os.path.join(sysdir, 'is_IS.dic'), '2\nhús\nÞetta\n')
        w(os.path.join(sysdir, 'fr.aff'), 'SET UTF-8\n')
        w(os.path.join(sysdir, 'fr.dic'), '1\nbâtiment\n')
        os.symlink('fr.aff', os.path.join(sysdir, 'fr_CA.aff'))
        os.symlink('fr.dic', os.path.join(sysdir, 'fr_CA.dic'))
        w(os.path.join(sysdir, 'de_DE.aff'), 'SET UTF-8\n')
        w(os.path.join(sysdir, 'de_DE.dic'), '1\nHaus\n')
        w(os.path.join(sysdir, 'et_EE.aff'), 'SET ISO8859-1\n', 'latin-1')
        w(os.path.join(sysdir, 'et_EE.dic'), '1\nmaja\n', 'latin-1')
    user = os.path.join(tmp, 'user')

    def spell_task(words, lang):
        return json.dumps({'type': 'spell', 'usrWords': words, 'usrLang': [lang] * len(words)}, ensure_ascii=False)
    tasks = [spell_task(['hús', 'Þetta', 'xqzzyv'], 0x040F),   # is-IS: we ship none
             spell_task(['bâtiment', 'xqzzyv'], 0x0C0C),         # fr-CA: we ship none
             spell_task(['Ourword', 'Haus'], 0x0407),            # de-DE: ours
             spell_task(['xqzzyv'], 0x0425)]                     # et-EE: ISO8859-1 system one
    r = subprocess.run([exe, dicts, user] + tasks, capture_output=True, text=True)
    out = r.stdout.splitlines()
    print('\n'.join('   | ' + l[:200] for l in out))

    def correct(i):
        try:
            return json.loads(out[i][len('ANSWER '):])['usrCorrect']
        except Exception:
            return None
    check(r.returncode == 0 and len(out) == len(tasks), 'driver ran every task')
    check(correct(0) == [True, True, False], 'is-IS is checked with the system dictionary: %s' % correct(0))
    check(correct(1) == [True, False], 'fr-CA is checked through the fr_CA -> fr symlinks: %s' % correct(1))
    if not real:
        check(correct(2) == [True, False], 'de-DE still uses our dictionary, not the system one: %s' % correct(2))
        check(correct(3) == [True], 'an ISO8859-1 system dictionary is not used: %s' % correct(3))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failed:
    print('%d check(s) failed%s' % (len(failed), ' (BASELINE %s)' % BASE_REF if BASELINE else ''))
    sys.exit(1)
print('all checks passed')

#!/usr/bin/env python3
"""
#630 - "Remove from dictionary": a word added to the spelling dictionary by
mistake (right click > Add to dictionary) could never be taken out again.

Native side (desktop-sdk ChromiumBasedEditors/lib/src/spellchecker.cpp): the
user dictionary is <user>/dictionaries/all/all.dic, shared by every editor.
CJsonSpellParser knew the tasks spell / suggest / add / clear only, so nothing
could list the words in it or remove one; CAscSpellChecker_Private only ever
appended to the file (AddUserWords_All) or wiped it (clear).
Fix: two more tasks. {"type":"list"} answers {"type":"list","usrWords":[...]}
with the words of all.dic, JSON-escaped (the answer is run as a JavaScript
literal, asc_nativeOnSpellCheck(<answer>)); {"type":"remove","usrWords":[...]}
rewrites all.dic without those words (header count updated) and reloads the
hunspell handle. sdkjs/web-apps add the api and the dialog (separate test).

This compiles the REAL classes CJsonTextItem, CJsonSpellParser and
CAscSpellChecker_Private from spellchecker.cpp, the REAL
CPluginsManager::GetStringValue/GetArrayValue from plugins.h, against core's
File.h/Directory.h/Timer.h (linked with the app's kernel.framework) and the
app's real hunspell.framework, with stubs only for the app manager event
plumbing (CAscApplicationManager::Apply records the answer). It drives the
private class the way the timer does: AddTask(...) then OnTimer().

Claimed: add -> list shows the word and hunspell accepts it; remove -> list no
longer shows it, hunspell rejects it, other words (one with a backslash and
one with a quote-free JSON-hostile character) are kept and listed escaped; the
file's count line matches; removing an absent word changes nothing.
NOT claimed: the editors' UI and api (see issue-0630-remove-from-dictionary-
ui-test.js), Windows/Linux runs (macOS only: needs the payload frameworks;
the TU was syntax-compiled for Linux separately).

  RD_REPO   desktop-sdk checkout (default ../../desktop-sdk)
  RD_CORE   core checkout for headers (default ../../core)
  RD_PAYLOAD  app payload with kernel/UnicodeConverter/hunspell frameworks
            (default /Users/osindero/dev/active/rationdocs/.rd-work/payload)
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
BASE_REF = os.environ.get('BASE_REF', '852aa207^')
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

private = cls(spell, 'CAscSpellChecker_Private').replace(
    '"../../../../core/Common/3dParty/hunspell/autogen/records.h"', '"%s"' % records)

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
#include "%(core)s/Common/MS-LCID.h"  // what spellchecker.cpp includes besides (#195)
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

tmp = tempfile.mkdtemp(prefix='rd630-')
failed = []
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
    dicts = os.path.join(tmp, 'dicts'); os.makedirs(dicts)
    user = os.path.join(tmp, 'user')
    weird = 'qu\\x'  # backslash in a word: must come back escaped
    tasks = ['{"type":"add","usrWords":["teh"]}',
             '{"type":"add","usrWords":["%s"]}' % weird,
             'spell:teh',
             '{"type":"list"}',
             '{"type":"remove","usrWords":["teh"]}',
             '{"type":"list"}',
             'spell:teh',
             'spell:' + weird,
             '{"type":"remove","usrWords":["absent"]}',
             '{"type":"list"}']
    r = subprocess.run([exe, dicts, user] + tasks, capture_output=True, text=True)
    out = r.stdout.splitlines()
    print('\n'.join('   | ' + l for l in out))

    def check(cond, msg):
        print(('ok   - ' if cond else 'FAIL - ') + msg)
        if not cond:
            failed.append(msg)

    def listed(line):
        try:
            obj = json.loads(line[len('ANSWER '):])
            return obj.get('usrWords') if obj.get('type') == 'list' else None
        except Exception:
            return None

    check(r.returncode == 0 and len(out) == len(tasks), 'driver ran every task')
    check(len(out) > 2 and out[2] == 'SPELL teh 1', 'added word is accepted by hunspell')
    l1 = listed(out[3]) if len(out) > 3 else None
    check(l1 is not None and 'teh' in l1 and weird in l1, 'list answers the user words (escaped JSON): %s' % l1)
    check(len(out) > 4 and out[4] == 'ANSWER {"type":"remove"}', 'remove is answered')
    l2 = listed(out[5]) if len(out) > 5 else None
    check(l2 is not None and 'teh' not in l2 and weird in l2, 'after remove, list no longer has it: %s' % l2)
    check(len(out) > 6 and out[6] == 'SPELL teh 0', 'removed word is rejected by hunspell again')
    check(len(out) > 7 and out[7] == 'SPELL %s 1' % weird, 'the other added word is still accepted')
    l3 = listed(out[9]) if len(out) > 9 else None
    check(l3 is not None and l3 == l2, 'removing an absent word changes nothing')
    dic = open(os.path.join(user, 'all', 'all.dic'), 'rb').read().decode('utf-8-sig').split('\n')
    check(dic[0].strip().isdigit() and int(dic[0]) == len([w for w in dic[1:] if w]), 'all.dic count line matches: %r' % dic)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failed:
    print('%d check(s) failed%s' % (len(failed), ' (BASELINE %s)' % BASE_REF if BASELINE else ''))
    sys.exit(1)
print('all checks passed')

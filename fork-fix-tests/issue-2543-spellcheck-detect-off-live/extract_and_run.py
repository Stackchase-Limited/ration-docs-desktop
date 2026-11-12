#!/usr/bin/env python3
"""
#2543 - "Spell check language constantly reverts to the Windows display language
(en-US) instead of keeping de-CH", and the "Disabling 'Spelling language detection'
has no effect" comments on #2503. Related: #2496.

Behaviour by design: while "Spelling language detection" is Auto, the desktop app
polls the keyboard layout (CAscKeyboardChecker::Check) and sends its LANGID to
every editor, which stores it in window.asc_current_keyboard_layout; Word then
stamps it on each run typed into (ParaRun.private_CheckLanguageBeforeAdd). On
Windows the LANGID is the input *language* the layout is installed under, so a
Swiss-German keyboard added to English (United States) reports en-US. Setting
detection to "Disabled" is the switch that keeps the document's own language.

The 9.4 bug: switching it off did not reach any open document. CUserSettings::Set
saves the setting, SaveSettings calls CAscKeyboardChecker::SetEnabled(false), and
that only resets the checker's own m_nLanguage to -1 - nothing is sent. Every
editor already open keeps the last LANGID it was sent and goes on retagging typed
text with it until the app is restarted (a newly opened editor is fine: it is sent
the checker's current -1 on create_editor_api).

(In 10.0 there is a second, separate cause, not in our tree: the rewritten start
page offers "auto"/"enabled"/"disabled", but the native side only recognises
"off", so "disabled" is stored as the default and the setting never sticks -
that is #2496. Our 9.4 start page sends "auto"/"off".)

Fix: CUserSettings::Set (applicationmanager.cpp) sends the keyboard state to all
views when "spell-check-input-mode" changes, the same way it already pushes
"force-scale" to them.

What runs here, extracted by brace matching and compiled with stubs:
  real  CUserSettings_Private, CUserSettings::Set/Get, GetUserSettings,
        CAscApplicationManager::CheckKeyboard/SendKeyboardAttack (applicationmanager.cpp),
        CAscApplicationManager_Private::SaveSettings (applicationmanager_p.h),
        CAscKeyboardChecker ctor/SetEnabled/Check/Send (keyboardchecker.cpp).
  stub  the file system (settings.xml in memory), XML node reading, the OS layout
        query (returns a fixed LANGID) and the view: Apply records the LANGID that
        cefview would hand the renderer as window.asc_current_keyboard_layout.

BASELINE=1 reads the three files from BASE_REF (default: the parent of the commit
that landed this fix) and MUST FAIL step 2. The integrator re-pins BASE_REF after
cherry-picking. Never point it at HEAD.

NOT verified: a GUI run (the renderer side, cefview -> client_renderer_wrapper ->
window.asc_current_keyboard_layout, is unchanged and not exercised), and the
Windows question of which LANGID a given layout reports.
Environment: RD_REPO = desktop-sdk checkout (default ../../desktop-sdk).
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'desktop-sdk'))
SRC = 'ChromiumBasedEditors/lib/src/'
BASE_REF = os.environ.get('BASE_REF', '2c10dedf^')
BASELINE = bool(os.environ.get('BASELINE'))


def read(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, text=True, check=True).stdout
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


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
    raise SystemExit('unbalanced braces')


def extract(src, signature):
    at = src.find(signature)
    if at == -1:
        raise SystemExit('%s not found - the extractor needs updating' % signature)
    return brace_match(src, at)


STUBS = r'''
#include <string>
#include <map>
#include <vector>
#include <cstdio>
#include <cstdlib>

#define RELEASEOBJECT(p) { if (p) { delete p; p = NULL; } }
static std::string  U_TO_UTF8(const std::wstring& s) { return std::string(s.begin(), s.end()); }
static std::wstring UTF8_TO_U(const std::string& s)  { return std::wstring(s.begin(), s.end()); }

// --- in-memory file system: settings.xml lives here
static std::map<std::wstring, std::wstring> g_files;
namespace NSFile { struct CFileBinary {
	static bool SaveToFile(const std::wstring& path, const std::wstring& data) { g_files[path] = data; return true; } }; }
namespace NSStringUtils {
	struct CStringBuilder {
		std::wstring s;
		void WriteString(const std::wstring& w) { s += w; }
		void AddCharSafe(wchar_t c) { s += c; }
		void WriteEncodeXmlString(const std::wstring& w) { s += w; }
		std::wstring GetData() { return s; }
	};
	static double GetDouble(const std::string& s) { return atof(s.c_str()); }
}
// a flat <Settings><name>value</name>...</Settings> reader, enough for SetManager
namespace XmlUtils { struct CXmlNode {
	std::wstring name, text; std::vector<CXmlNode> kids;
	bool FromXmlFile(const std::wstring& path) {
		auto it = g_files.find(path); if (it == g_files.end()) return false;
		const std::wstring& x = it->second; size_t p = x.find(L"<Settings>"); if (p == std::wstring::npos) return false;
		p += 10;
		while (true) {
			if (x.compare(p, 2, L"</") == 0) break;
			size_t e = x.find(L'>', p); CXmlNode k; k.name = x.substr(p + 1, e - p - 1);
			size_t c = x.find(L"</" + k.name + L">", e); k.text = x.substr(e + 1, c - e - 1);
			kids.push_back(k); p = c + k.name.size() + 3;
		}
		return true;
	}
	bool GetChilds(std::vector<CXmlNode>& v) { v = kids; return true; }
	std::wstring GetName() { return name; }
	std::wstring GetText() { return text; }
}; }
namespace NSAscCrypto { enum AscCryptoType { None = 0 }; }
namespace NSCommon { struct CSystemWindowScale { static bool IsInit() { return true; } static void SetUseSystemScaling(bool) {} }; }
struct CPluginsManager { static void DisableAI() {} };

namespace NSEditorApi {
	struct IMenuEventDataBase { virtual ~IMenuEventDataBase() {} };
	struct CAscKeyboardLayout : IMenuEventDataBase {
		int m_nLanguage = 0;
		void put_Language(int v) { m_nLanguage = v; } int get_Language() { return m_nLanguage; } };
	struct CAscMenuEvent { int m_nType = 0; IMenuEventDataBase* m_pData = nullptr; ~CAscMenuEvent() { delete m_pData; } };
}
static const int ASC_MENU_EVENT_TYPE_CEF_KEYBOARDLAYOUT = 7001;

// --- the "renderer": what an open editor last received as asc_current_keyboard_layout
static int g_rendererLayout = -99;
static int g_sends = 0;
struct CCefView { void moveEvent() {} };

class CAscApplicationManager;
class CAscKeyboardChecker {
public:
	CAscKeyboardChecker(); ~CAscKeyboardChecker();
	void Check(CAscApplicationManager* pManager, int nLangInput = -1);
	void Send(CAscApplicationManager* pManager);
	void SetEnabled(const bool& bIsEnabled);
protected:
	bool m_bIsEnabled; int m_nLanguage;
};

class CUserSettings_Private;
class CUserSettings {
public:
	CUserSettings(); ~CUserSettings();
	std::wstring Get(const std::wstring& name);
	void Set(const std::wstring& name, const std::wstring& value);
	CUserSettings_Private* m_pInternal;
};

struct CAscApplicationManager_Private;
class CAscApplicationManager {
public:
	struct { std::wstring fonts_cache_info_path = L"/app/fonts"; } m_oSettings;
	CAscApplicationManager_Private* m_pInternal;
	int m_nOsLayout = 0x0807;                       // de-CH
	int GetPlatformKeyboardLayout() { return m_nOsLayout; }
	void Apply(NSEditorApi::CAscMenuEvent* pEvent) {
		if (pEvent->m_nType == ASC_MENU_EVENT_TYPE_CEF_KEYBOARDLAYOUT) {
			g_rendererLayout = ((NSEditorApi::CAscKeyboardLayout*)pEvent->m_pData)->get_Language();
			g_sends++;
		}
		delete pEvent;
	}
	void CheckKeyboard();
	void SendKeyboardAttack();
	CUserSettings* GetUserSettings();
};

struct CAscApplicationManager_Private {
	CAscApplicationManager* m_pMain = nullptr;
	std::map<std::string, std::string> m_mapSettings;
	std::map<int, CCefView*> m_mapViews;
	CAscKeyboardChecker m_oKeyboardChecker;
	double m_dForceDisplayScale = -1;
	NSAscCrypto::AscCryptoType m_nCurrentCryptoMode = NSAscCrypto::None;
	bool m_bIsEnableConvertLogs = false, m_bIsUseExternalMessageLoop = false,
	     m_bIsUseSpellCheckKeyboardInput = true, m_bDebugInfoSupport = false,
	     m_bSupportMultiplugins = false, m_bLoggingBrowserUrls = false, m_bDisableAI = false,
	     m_bCanHideSystemPlugins = false; // #2466 (desktop-sdk 1db9f146) reads plugins-hide-builtin in the same block
	void LoadSettings() {}      // refreshes the manager's own map; not needed here
	%(SAVE)s
};
'''

MAIN = r'''
static int fails = 0;
static void expect(const char* what, int want) {
	bool ok = g_rendererLayout == want;
	if (!ok) fails++;
	printf("  %s  %-62s editor has %d (want %d)\n", ok ? "ok  " : "FAIL", what, g_rendererLayout, want);
}
static void setDetect(CAscApplicationManager& m, const wchar_t* v) {
	CUserSettings* s = m.GetUserSettings(); s->Set(L"spell-check-input-mode", v); delete s;
}
int main() {
	CAscApplicationManager m;
	m.m_pInternal = new CAscApplicationManager_Private();
	m.m_pInternal->m_pMain = &m;
	m.m_pInternal->SaveSettings();                           // startup: detection Auto

	m.CheckKeyboard();                                       // timer tick, keyboard de-CH
	expect("1 Auto: the open editor follows the keyboard (de-CH)", 0x0807);

	setDetect(m, L"0");                                      // user picks Disabled
	expect("2 Disabled: the open editor is told to stop (-1) at once", -1);
	{	// control (#2496): the choice reaches settings.xml and reads back after a "restart"
		bool saved = g_files[L"/app/fonts/../settings.xml"].find(L"<spell-check-input-mode>0</spell-check-input-mode>") != std::wstring::npos;
		CUserSettings* s = m.GetUserSettings(); bool back = s->Get(L"spell-check-input-mode") == L"0"; delete s;
		if (!(saved && back)) fails++;
		printf("  %s  %-62s saved=%d readback=%d\n", (saved && back) ? "ok  " : "FAIL", "2b Disabled is persisted to settings.xml", (int)saved, (int)back);
	}

	m.CheckKeyboard();
	expect("3 Disabled: later timer ticks send nothing new", -1);

	m.SendKeyboardAttack();                                  // a new editor's create_editor_api
	expect("4 Disabled: a newly opened editor gets -1", -1);

	setDetect(m, L"default");                                // back to Auto
	m.CheckKeyboard();
	expect("5 Auto again: the next tick sends the keyboard again", 0x0807);

	m.m_nOsLayout = 0x0409; m.CheckKeyboard();
	expect("6 Auto: a layout switch to en-US is followed", 0x0409);

	printf("settings.xml: %ls\n", g_files[L"/app/fonts/../settings.xml"].c_str());
	return fails ? 1 : 0;
}
'''


def main():
    am = read(SRC + 'applicationmanager.cpp')
    amp = read(SRC + 'applicationmanager_p.h')
    kc = read(SRC + 'keyboardchecker.cpp')

    parts = [STUBS % {'SAVE': extract(amp, 'void SaveSettings(')}]
    for sig in ('CAscKeyboardChecker::CAscKeyboardChecker()', 'CAscKeyboardChecker::~CAscKeyboardChecker()',
                'void CAscKeyboardChecker::SetEnabled(', 'void CAscKeyboardChecker::Check(',
                'void CAscKeyboardChecker::Send('):
        parts.append(extract(kc, sig))
    parts.append(extract(am, 'class CUserSettings_Private') + ';')
    for sig in ('CUserSettings::CUserSettings()', 'CUserSettings::~CUserSettings()',
                'std::wstring CUserSettings::Get(', 'void CUserSettings::Set(',
                'void CAscApplicationManager::CheckKeyboard()', 'void CAscApplicationManager::SendKeyboardAttack()',
                'CUserSettings* CAscApplicationManager::GetUserSettings()'):
        parts.append(extract(am, sig))
    parts.append(MAIN)

    work = tempfile.mkdtemp(prefix='rd2543-')
    try:
        cpp = os.path.join(work, 't.cpp')
        exe = os.path.join(work, 't')
        with open(cpp, 'w') as f:
            f.write('\n'.join(parts))
        subprocess.run(['c++', '-std=c++17', '-w', cpp, '-o', exe], check=True)
        r = subprocess.run([exe], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode < 0:
            print('  FAIL  harness crashed (signal %d)' % -r.returncode)
        if BASELINE:
            print('BASELINE (%s): step 2 must FAIL' % BASE_REF)
        print('%s #2543' % ('FAIL' if r.returncode else 'PASS'))
        return 1 if r.returncode else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())

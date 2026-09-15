#!/usr/bin/env python3
r"""setup_paths must configure the same directories however often it is called.

Found while checking ONLYOFFICE/DesktopEditors#2123 (the recent-files list). The
reported cause there did not hold up, but this did:

    QString user_data_path = Utils::getUserPath() + APP_DATA_PATH;
    auto setup_paths = [&user_data_path](CAscApplicationManager * manager) {
        ...
            Utils::makepath(user_data_path.append("/data"));   // IN PLACE

The capture is by reference and QString::append mutates in place, so the captured
variable stayed one directory deeper after the call returned. There is exactly one
call site today, so nothing is broken in the shipping build - but a second call
appended "/data" again and moved recover_path, cookie_path, fonts_cache_info_path,
user_plugins_path and recents.xml to .../data/data/, abandoning the user's recovery
files and recent list with no error at all.

That is a latent defect rather than a live one, so the test asserts the property
that makes it safe: calling setup_paths twice must produce identical paths.

This extracts the REAL lambda body out of desktop-apps/win-linux/src/main.cpp by
brace matching and compiles it against minimal stubs - QString (with the real
in-place append semantics), Utils, and a settings struct. Nothing is retyped.

  ./extract_and_run.py             the working tree, must PASS
  BASELINE=1 ./extract_and_run.py  the pinned parent commit, must FAIL

Exit 0 = pass, 1 = fail.
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.join(ROOT, "desktop-apps")
REL = "win-linux/src/main.cpp"

# Pinned to the parent of the commit that landed this fix. It must NOT default to
# HEAD: once the fix is committed HEAD carries it, the baseline stops differing,
# and the test passes forever while testing nothing.
BASE_REF = os.environ.get("BASE_REF", "1509c6228ed5f0040c3df56bdd6b4fcfa5bca65a")
BASELINE = bool(os.environ.get("BASELINE"))


def source():
    if BASELINE:
        r = subprocess.run(["git", "-C", REPO, "show", "%s:%s" % (BASE_REF, REL)],
                           capture_output=True)
        if r.returncode != 0:
            sys.stderr.write(r.stderr.decode("utf-8", "replace"))
            raise SystemExit("could not read %s at %s" % (REL, BASE_REF))
        return r.stdout.decode("utf-8", "replace")
    with open(os.path.join(REPO, REL), encoding="utf-8") as fh:
        return fh.read()


def extract_lambda(src):
    """Slice the setup_paths lambda body out by brace matching."""
    at = src.index("auto setup_paths = [")
    open_brace = src.index("{", src.index("(CAscApplicationManager", at))
    depth = 0
    for i in range(open_brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                body = src[open_brace + 1:i]
                capture = src[src.index("[", at):src.index("]", at) + 1]
                return capture, body
    raise AssertionError("unbalanced braces in setup_paths")


CAPTURE, BODY = extract_lambda(source())

# Prove we sliced the right thing and the whole thing, rather than a prefix that
# happens to compile.
assert "spell_dictionaries_path" in BODY, "extraction truncated - tail missing"
assert 'append("/data")' in BODY, "extraction missing the in-place append"
assert "connection_error_path" in BODY, "extraction truncated - last line missing"

HARNESS = r"""
#include <string>
#include <vector>
#include <cstdio>

/* A QString stub with the semantics that matter here: append() MUTATES and
   returns a reference, operator+ does not. That is the real Qt behaviour and the
   whole point of the defect. */
struct QString {
    std::string s;
    QString() {}
    QString(const char* p) : s(p) {}
    QString(const std::string& p) : s(p) {}
    QString& append(const char* p) { s += p; return *this; }
    QString operator+(const char* p) const { return QString(s + p); }
    QString operator+(const QString& o) const { return QString(s + o.s); }
    std::wstring toStdWString() const { return std::wstring(s.begin(), s.end()); }
    std::string toStdString() const { return s; }
    bool isEmpty() const { return s.empty(); }
    static QString fromStdWString(const std::wstring& w) { return QString(std::string(w.begin(), w.end())); }
    QString& fromStdWString_(const std::wstring&) { return *this; }
};
static std::string asc(const std::wstring& w) { return std::string(w.begin(), w.end()); }

struct Settings {
    std::wstring user_data_path, user_templates_path, cookie_path, recover_path;
    std::wstring fonts_cache_info_path, spell_dictionaries_path, file_converter_path;
    std::wstring user_plugins_path, local_editors_path, system_templates_path;
    std::wstring connection_error_path;
    std::vector<std::wstring> additional_fonts_folder;
    std::string country;
    void SetUserDataPath(const std::wstring& v) { user_data_path = v; }
};
struct CAscApplicationManager { Settings m_oSettings; };

namespace Utils {
    static QString getAppCommonPath() { return QString(COMMON_DATA_PATH); }
    static void makepath(const QString&) {}
    static QString systemLocationCode() { return QString("GB"); }
}
namespace NSFile { static std::wstring GetProcessDirectory() { return L"/opt/app"; } }

/* QString().fromStdWString(x) in the original is a static-ish call on a temporary. */
static QString g_tmp;

int main() {
    QString user_data_path = QString("/home/u/.local/share/RationDocs");

    auto setup_paths = CAPTURE_HERE (CAscApplicationManager * manager) {
BODY_HERE
    };

    CAscApplicationManager a, b;
    setup_paths(&a);
    setup_paths(&b);   /* the second call is the whole test */

    struct { const char* name; const std::wstring* x; const std::wstring* y; } fields[] = {
        {"recover_path",          &a.m_oSettings.recover_path,          &b.m_oSettings.recover_path},
        {"cookie_path",           &a.m_oSettings.cookie_path,           &b.m_oSettings.cookie_path},
        {"fonts_cache_info_path", &a.m_oSettings.fonts_cache_info_path, &b.m_oSettings.fonts_cache_info_path},
        {"user_plugins_path",     &a.m_oSettings.user_plugins_path,     &b.m_oSettings.user_plugins_path},
        {"user_data_path",        &a.m_oSettings.user_data_path,        &b.m_oSettings.user_data_path},
    };

    int bad = 0;
    for (size_t i = 0; i < sizeof(fields)/sizeof(fields[0]); ++i) {
        bool same = (*fields[i].x == *fields[i].y);
        if (!same) ++bad;
        printf("  %-5s %-22s first=%-52s second=%s\n",
               same ? "ok" : "FAIL", fields[i].name,
               asc(*fields[i].x).c_str(), asc(*fields[i].y).c_str());
    }
    /* recents.xml is derived as recover_path + "/../recents.xml" by the readers. */
    printf("\n  recents.xml would resolve under: %s\n",
           (asc(a.m_oSettings.recover_path) + "/../recents.xml").c_str());
    if (bad) {
        printf("\nFAILED - calling setup_paths twice moved %d path(s); the recovery\n"
               "         files and recent list of the first call are abandoned.\n", bad);
        return 1;
    }
    printf("\nok - setup_paths configures the same directories however often it runs\n");
    return 0;
}
"""


def resolve_ifdefs(body, windows):
    """Pick one side of the body's #ifdef _WIN32 ... #else ... #endif by hand.

    Compiling with -D_WIN32 on macOS is not an option: libc++ then takes its own
    Windows headers and the translation unit fails before it reaches our code. So
    the branch is resolved textually, which also keeps the extracted lines exactly
    as they appear in main.cpp.
    """
    out, state = [], "outside"
    for line in body.split("\n"):
        t = line.strip()
        if t.startswith("#ifdef _WIN32"):
            state = "win"; continue
        if t.startswith("#else") and state == "win":
            state = "notwin"; continue
        if t.startswith("#endif") and state in ("win", "notwin"):
            state = "outside"; continue
        if state == "win" and not windows:
            continue
        if state == "notwin" and windows:
            continue
        out.append(line)
    return "\n".join(out)


def run(common_data_path, label):
    windows = bool(common_data_path)
    body = resolve_ifdefs(BODY, windows=True)  # the appending branch is Windows-only
    src = HARNESS.replace("CAPTURE_HERE", CAPTURE).replace("BODY_HERE", body)
    # QString().fromStdWString(...) -> our static helper
    src = src.replace("QString().fromStdWString(", "QString::fromStdWString(")
    with tempfile.TemporaryDirectory() as work:
        cpp = os.path.join(work, "t.cpp")
        exe = os.path.join(work, "t")
        with open(cpp, "w", encoding="utf-8") as fh:
            fh.write(src)
        cc = subprocess.run(
            ["clang++", "-std=gnu++11", "-w",
             '-DCOMMON_DATA_PATH="%s"' % common_data_path, "-o", exe, cpp],
            capture_output=True)
        if cc.returncode != 0:
            sys.stderr.write(cc.stdout.decode("utf-8", "replace"))
            sys.stderr.write(cc.stderr.decode("utf-8", "replace"))
            raise SystemExit("harness did not compile")
        print("\n%s" % label, flush=True)
        r = subprocess.run([exe])
        return r.returncode


def main():
    print("source: %s" % ("git %s (BASELINE)" % BASE_REF if BASELINE else "working tree"), flush=True)
    # The in-place append is inside the Windows branch that runs only when a common
    # app-data path exists, so that is the configuration under test. The empty case
    # is checked too, to show it was never affected either way.
    rc = 0
    rc |= run("C:/ProgramData/RationDocs", "with a common app-data path (the Windows branch that appends):")
    rc |= run("", "with no common app-data path (the branch that never appended):")
    return 1 if rc else 0


if __name__ == "__main__":
    sys.exit(main())

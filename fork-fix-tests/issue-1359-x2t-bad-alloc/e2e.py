#!/usr/bin/env python3
r"""End-to-end: make the real x2t run out of memory mid-conversion and see what
it does about it.

Before this fix x2t caught nothing, so the std::bad_alloc that a file exhausting
X2T_MEMORY_LIMIT produces went to terminate() and the process died on SIGABRT.
A dead converter gives the editor no exit code to read, which is why #1359's
reporter saw the generic "Something has gone wrong..." on their 85MB CSV.

How the allocation is made to fail depends on the platform, because x2t's own
cap cannot be made to bite everywhere:

  Linux   RLIMIT_AS, set on the child before exec.  This is the real mechanism -
          the same kind of limit x2t sets on itself with setrlimit(RLIMIT_DATA)
          in Common/3dParty/misc/proclimits.h - so on Linux this test reproduces
          the reporter's failure exactly rather than simulating it.

  macOS   setrlimit is a genuine no-op here: RLIMIT_DATA and RLIMIT_AS are both
          rejected with EINVAL, so X2T_MEMORY_LIMIT changes nothing on this
          machine and an unbounded run is SIGKILLed by the OS instead of getting
          a NULL from malloc.  So operator new is interposed instead, with
          DYLD_INSERT_LIBRARIES, and made to throw std::bad_alloc for
          allocations at or above RD_BADALLOC_BYTES.  The throw, the unwind, the
          handler and the exit code are all the real ones; only the trigger is
          synthetic.

Expected:

    fixed x2t      rc=93   AVS_FILEUTILS_ERROR_CONVERT_LIMITS, and a message
    pre-fix x2t    rc=134  SIGABRT from terminate(), nothing to report

Usage:
  ./e2e.py                            test core/build/bin/<plat>/x2t
  RD_X2T=<path> ./e2e.py              test another build (a pre-fix one must FAIL)

Exit 0 = pass, 1 = fail, 77 = nothing to test.
"""

import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
FONTS = os.path.join(ROOT, "core-fonts")

FORMAT_CSV = 260
FORMAT_XLSX = 257
DELIMITER_COMMA = 4
ENCODING_UTF8 = 46

# getReturnErrorCode(AVS_FILEUTILS_ERROR_CONVERT_LIMITS) - see
# core/Common/OfficeFileErrorDescription.h and cextracttools.cpp.
EXIT_CONVERT_LIMITS = 93

# Small enough to convert in a second or two unlimited, big enough that the CSV
# reader - which materialises the whole workbook at roughly 120x the file size -
# asks for far more than the cap below.
ROWS = 200000
LIMIT_BYTES = 32 * 1024 * 1024          # macOS: largest single allocation allowed
LINUX_AS_BYTES = 768 * 1024 * 1024      # Linux: RLIMIT_AS for the child

INTERPOSE_SRC = r'''
// Fail operator new at or above RD_BADALLOC_BYTES, the way a heap limit does.
#include <new>
#include <cstddef>
#include <cstdlib>

static size_t g_threshold = (size_t)-1;
static bool   g_init = false;

static inline size_t threshold()
{
    if (!g_init) {
        const char* s = getenv("RD_BADALLOC_BYTES");
        g_threshold = s ? (size_t)strtoull(s, 0, 10) : (size_t)-1;
        g_init = true;
    }
    return g_threshold;
}

static void* rd_alloc(size_t sz)
{
    if (sz >= threshold())
        throw std::bad_alloc();
    void* p = malloc(sz ? sz : 1);
    if (!p)
        throw std::bad_alloc();
    return p;
}

void* rd_new(size_t sz)     { return rd_alloc(sz); }
void* rd_new_arr(size_t sz) { return rd_alloc(sz); }

typedef struct { const void* replacement; const void* replacee; } interpose_t;

__attribute__((used)) static const interpose_t rd_interposers[]
__attribute__((section("__DATA,__interpose"))) = {
    { (const void*)&rd_new,     (const void*)(void*(*)(size_t))(&::operator new)   },
    { (const void*)&rd_new_arr, (const void*)(void*(*)(size_t))(&::operator new[]) },
};
'''


def find_x2t():
    if os.environ.get("RD_X2T"):
        return os.environ["RD_X2T"]
    for plat in ("mac_arm64", "mac_x86_64", "linux_x86_64"):
        p = os.path.join(ROOT, "core", "build", "bin", plat, "x2t")
        if os.path.exists(p):
            return p
    p = os.path.join(ROOT, "desktop-apps", "build", "Ration Docs.app",
                     "Contents", "Resources", "converter", "x2t")
    return p if os.path.exists(p) else None


X2T = find_x2t()
if not X2T:
    sys.stderr.write("no x2t built - skipping\n")
    raise SystemExit(77)

IS_MAC = platform.system() == "Darwin"
FRAMEWORKS = os.path.join(ROOT, "core", "build", "lib", "mac_arm64")


def write_inputs(work):
    src = os.path.join(work, "in.csv")
    with open(src, "w", encoding="utf-8") as fh:
        for i in range(ROWS):
            fh.write(",".join(str(i * j) for j in range(1, 9)))
            fh.write("\n")
    dst = os.path.join(work, "out.xlsx")
    task = os.path.join(work, "task.xml")
    with open(task, "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<TaskQueueDataConvert xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
            "<m_sFileFrom>%s</m_sFileFrom>\n"
            "<m_sFileTo>%s</m_sFileTo>\n"
            "<m_nFormatFrom>%d</m_nFormatFrom>\n"
            "<m_nFormatTo>%d</m_nFormatTo>\n"
            "<m_nCsvTxtEncoding>%d</m_nCsvTxtEncoding>\n"
            "<m_nCsvDelimiter>%d</m_nCsvDelimiter>\n"
            "<m_sFontDir>%s</m_sFontDir>\n"
            "</TaskQueueDataConvert>\n"
            % (src, dst, FORMAT_CSV, FORMAT_XLSX, ENCODING_UTF8, DELIMITER_COMMA, FONTS)
        )
    return task, dst, os.path.getsize(src)


def build_interposer(work):
    dylib = os.path.join(work, "badalloc.dylib")
    cpp = os.path.join(work, "badalloc.cpp")
    with open(cpp, "w", encoding="utf-8") as fh:
        fh.write(INTERPOSE_SRC)
    c = subprocess.run(["clang++", "-std=c++11", "-O1", "-dynamiclib", "-o", dylib, cpp],
                       capture_output=True, text=True)
    if c.returncode != 0:
        sys.stderr.write(c.stdout + c.stderr)
        return None
    return dylib


def run(task, starve, dylib):
    env = dict(os.environ)
    if os.path.isdir(FRAMEWORKS):
        env["DYLD_FRAMEWORK_PATH"] = FRAMEWORKS
    pre = None
    if starve:
        if IS_MAC:
            env["DYLD_INSERT_LIBRARIES"] = dylib
            env["RD_BADALLOC_BYTES"] = str(LIMIT_BYTES)
        else:
            import resource

            def pre():  # noqa: E306  - set the limit on the child, before exec
                resource.setrlimit(resource.RLIMIT_AS,
                                   (LINUX_AS_BYTES, LINUX_AS_BYTES))
    p = subprocess.run([X2T, task], env=env, capture_output=True, preexec_fn=pre)
    return p.returncode, (p.stderr or b"").decode("utf-8", "replace").strip()


def main():
    print("x2t:      %s" % X2T)
    print("platform: %s (%s)\n" % (platform.system(),
                                   "interposed operator new" if IS_MAC
                                   else "RLIMIT_AS on the child"))
    failures = []
    with tempfile.TemporaryDirectory() as work:
        task, dst, size = write_inputs(work)
        print("input:    %s rows, %.1f MB" % (ROWS, size / 1048576.0))

        dylib = build_interposer(work) if IS_MAC else None
        if IS_MAC and not dylib:
            sys.stderr.write("could not build the interposer - skipping\n")
            return 77

        # 1. unconstrained: the conversion must still work
        rc, err = run(task, False, dylib)
        ok = (rc == 0 and os.path.exists(dst))
        print("  %-3s unconstrained                      rc=%-4d %s"
              % ("ok" if ok else "!!", rc,
                 "wrote %d bytes" % os.path.getsize(dst) if os.path.exists(dst)
                 else "no output"))
        if not ok:
            failures.append("the conversion does not work without a memory limit")

        if os.path.exists(dst):
            os.remove(dst)

        # 2. constrained: it must REPORT, not die
        rc, err = run(task, True, dylib)
        died_on_signal = rc < 0 or rc >= 128
        ok = (rc == EXIT_CONVERT_LIMITS)
        print("  %-3s out of memory                      rc=%-4d %s"
              % ("ok" if ok else "!!", rc,
                 "killed by a signal" if died_on_signal
                 else "AVS_FILEUTILS_ERROR_CONVERT_LIMITS" if ok
                 else "some other error"))
        if err:
            for line in err.splitlines()[-2:]:
                print("      x2t said: %s" % line)
        if not ok:
            if died_on_signal:
                failures.append("x2t died on a signal (rc=%d) instead of returning %d - "
                                "the editor cannot tell this from a corrupt file"
                                % (rc, EXIT_CONVERT_LIMITS))
            else:
                failures.append("x2t returned %d, not %d" % (rc, EXIT_CONVERT_LIMITS))

    print()
    if failures:
        for f in failures:
            print("  " + f)
        print("\n%d failure(s) - #1359 (the memory cap half)" % len(failures))
        return 1
    print("running out of memory is reported as an error code, not a crash")
    return 0


if __name__ == "__main__":
    sys.exit(main())

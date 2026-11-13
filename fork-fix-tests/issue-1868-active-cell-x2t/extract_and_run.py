#!/usr/bin/env python3
"""
#1868 (caret half, core side) - x2t wrote the sheetView <selection> stored in Editor.bin,
which for a desktop save is the one from when the file was opened: moving the caret makes
no change record, so the saved file reopened with the cursor where it started.

The editor now sends "activeCells" in the save parameters (sdkjs getAdditionalSaveParams,
see issue-1868-active-cell-save-test.js): "<sheet index>:<active cell>:<range>" pairs
joined by ';'. In core, InputParams::getActiveCellsFromJsonParams lifts it out of
m_sJsonParams (same validation as topLeftCells: only [0-9A-Za-z:;$], else nothing) into
fileOptions/@activeCells, SerializeCommon::ReadActiveCells reads it into
SaveParams::mapActiveCells, and BinaryWorksheetsTableReader::ApplyActiveCellOverride sets
the active cell and sqref of the sheetView's selection - the active pane's when panes are
frozen - before the sheetViews are written (xlsx and xlsb writers).

This extracts the REAL getSheetPairsFromJsonParams/getActiveCellsFromJsonParams
(X2tConverter/src/cextracttools.h) and ApplyActiveCellOverride
(OOXML/Binary/Sheets/Writer/BinaryReaderS.cpp), compiles them with stub OOX types and runs:
the parameter is lifted (and refused when it carries markup), a stale selection is
replaced, a sheet with no selection gets one, the frozen-pane case updates only the active
pane's selection, a sheet the parameter does not name is untouched.
NOT claimed here: the ';' splitting (SerializeCommon::ReadSheetIndexPairs, shared with
topLeftCells and unchanged in behaviour) and the xlsx output, which was checked by hand with
an x2t built from this tree (Editor.bin stored C5, activeCells "0:D9:D9" -> saved
<selection activeCell="D9" sqref="D9"/>).

  python3 fork-fix-tests/issue-1868-active-cell-x2t/extract_and_run.py
  RD_REPO=<core checkout> (default ../../core)   BASELINE=1 -> must FAIL
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('RD_REPO') or os.path.normpath(os.path.join(HERE, '..', '..', 'core'))
BASE_REF = os.environ.get('BASE_REF', 'd353ff8898^')
BASELINE = bool(os.environ.get('BASELINE'))


def src(rel):
    if BASELINE:
        return subprocess.run(['git', '-C', REPO, 'show', '%s:%s' % (BASE_REF, rel)],
                              capture_output=True, check=True).stdout.decode('utf-8-sig')
    return open(os.path.join(REPO, rel), encoding='utf-8-sig').read()


def extract(text, marker):
    at = text.find(marker)
    if at < 0:
        return None
    depth = 0
    for i in range(text.index('{', at), len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[at:i + 1]
    return None


STUBS = r'''
#include <string>
#include <map>
#include <vector>
#include <cstdio>
typedef int _INT32;
template<class T> struct nullable {
    T* p = nullptr;
    bool IsInit() const { return p != nullptr; }
    T* operator->() { return p; }
    const T* operator->() const { return p; }
    void reset() { delete p; p = nullptr; }
    void Init() { reset(); p = new T(); }
    nullable& operator=(const T& v) { reset(); p = new T(v); return *this; }
    const T& get() const { return *p; }
};
typedef nullable<std::wstring> nullable_string;
namespace SimpleTypes {
    struct CUnsignedDecimalNumber { unsigned v = 0; unsigned GetValue() const { return v; } };
    namespace Spreadsheet { struct CActivePane { int v = 0; int GetValue() const { return v; } }; }
}
namespace OOX { namespace Spreadsheet {
    struct CSelection {
        nullable_string m_oActiveCell;
        nullable<SimpleTypes::CUnsignedDecimalNumber> m_oActiveCellId;
        nullable_string m_oSqref;
        nullable<SimpleTypes::Spreadsheet::CActivePane> m_oPane;
    };
    struct CPane { nullable<SimpleTypes::Spreadsheet::CActivePane> m_oActivePane; };
    struct CSheetView { std::vector<CSelection*> m_arrItems; nullable<CPane> m_oPane; nullable_string m_oTopLeftCell; };
}}
struct SaveParams { std::map<_INT32, std::wstring> mapTopLeftCells; std::map<_INT32, std::wstring> mapActiveCells; };
struct BinaryWorksheetsTableReader {
    SaveParams m_oSaveParams;
    std::vector<int> m_arWorksheets;
    void ApplyActiveCellOverride(OOX::Spreadsheet::CSheetView* pSheetView);
};
struct InputParams {
    std::wstring* m_sJsonParams = nullptr;
    @@PARAMS@@
};
@@APPLY@@
'''

DRIVER = r'''
static int g_fail = 0;
static void check(const char* name, bool ok) { printf("%s %s\n", ok ? "ok  " : "FAIL", name); if (!ok) g_fail++; }
static std::wstring str(const nullable_string& s) { return s.IsInit() ? s.get() : L"<none>"; }
static OOX::Spreadsheet::CSelection* sel(const wchar_t* cell, const wchar_t* sqref, int pane = -1, int id = -1)
{
    auto* s = new OOX::Spreadsheet::CSelection();
    s->m_oActiveCell = std::wstring(cell); s->m_oSqref = std::wstring(sqref);
    if (pane >= 0) { s->m_oPane.Init(); s->m_oPane->v = pane; }
    if (id >= 0) { s->m_oActiveCellId.Init(); s->m_oActiveCellId->v = id; }
    return s;
}
int main()
{
    InputParams ip;
    std::wstring json = L"{\"spreadsheetLayout\":{\"fitToWidth\":0},\"topLeftCells\":\"0:A1\",\"activeCells\":\"0:C5:C5;1:B2:B2:D7\"}";
    ip.m_sJsonParams = &json;
    check("activeCells lifted out of the save parameters", ip.getActiveCellsFromJsonParams() == L"0:C5:C5;1:B2:B2:D7");
    check("topLeftCells still lifted", ip.getTopLeftCellsFromJsonParams() == L"0:A1");
    std::wstring bad = L"{\"activeCells\":\"0:C5'/><x a='\"}";
    ip.m_sJsonParams = &bad;
    check("a value carrying markup is refused", ip.getActiveCellsFromJsonParams().empty());

    BinaryWorksheetsTableReader r;
    r.m_oSaveParams.mapActiveCells[0] = L"D9:D9";
    r.m_oSaveParams.mapActiveCells[1] = L"B2:B2:D7";
    r.m_oSaveParams.mapActiveCells[2] = L"E3:E3";

    OOX::Spreadsheet::CSheetView v0; v0.m_arrItems.push_back(sel(L"C5", L"C5", -1, 1));
    r.ApplyActiveCellOverride(&v0);
    check("stale open-time selection replaced by the caret",
          str(v0.m_arrItems[0]->m_oActiveCell) == L"D9" && str(v0.m_arrItems[0]->m_oSqref) == L"D9" && !v0.m_arrItems[0]->m_oActiveCellId.IsInit());

    r.m_arWorksheets.push_back(0);
    OOX::Spreadsheet::CSheetView v1;
    r.ApplyActiveCellOverride(&v1);
    check("sheet with no stored selection gets one",
          v1.m_arrItems.size() == 1 && str(v1.m_arrItems[0]->m_oActiveCell) == L"B2" && str(v1.m_arrItems[0]->m_oSqref) == L"B2:D7");

    r.m_arWorksheets.push_back(1);
    OOX::Spreadsheet::CSheetView v2;  // frozen panes: topRight(1) and bottomRight(0), active pane bottomRight
    v2.m_oPane.Init(); v2.m_oPane->m_oActivePane.Init(); v2.m_oPane->m_oActivePane->v = 0;
    v2.m_arrItems.push_back(sel(L"F1", L"F1", 1));
    v2.m_arrItems.push_back(sel(L"A20", L"A20", 0));
    r.ApplyActiveCellOverride(&v2);
    check("frozen panes: the active pane's selection takes the caret, the other is kept",
          str(v2.m_arrItems[1]->m_oActiveCell) == L"E3" && str(v2.m_arrItems[0]->m_oActiveCell) == L"F1");

    r.m_arWorksheets.push_back(2);
    OOX::Spreadsheet::CSheetView v3; v3.m_arrItems.push_back(sel(L"C5", L"C5"));
    r.ApplyActiveCellOverride(&v3);
    check("a sheet the parameter does not name is untouched", str(v3.m_arrItems[0]->m_oActiveCell) == L"C5");
    return g_fail ? 1 : 0;
}
'''


def main():
    if not shutil.which('clang++'):
        print('CANNOT RUN: clang++ not found')
        return 2
    params = extract(src('X2tConverter/src/cextracttools.h'), 'std::wstring getSheetPairsFromJsonParams(')
    active = extract(src('X2tConverter/src/cextracttools.h'), 'std::wstring getActiveCellsFromJsonParams(')
    topleft = extract(src('X2tConverter/src/cextracttools.h'), 'std::wstring getTopLeftCellsFromJsonParams(')
    apply_ = extract(src('OOXML/Binary/Sheets/Writer/BinaryReaderS.cpp'),
                     'void BinaryWorksheetsTableReader::ApplyActiveCellOverride(')
    if not (params and active and topleft and apply_):
        print('FAIL #1868: x2t has no active-cell override (getActiveCellsFromJsonParams / '
              'ApplyActiveCellOverride not found)' + (' (baseline, as expected)' if BASELINE else ''))
        return 1
    code = STUBS.replace('@@PARAMS@@', topleft + '\n' + active + '\n' + params).replace('@@APPLY@@', apply_) + DRIVER
    tmp = tempfile.mkdtemp(prefix='i1868-')
    try:
        cpp = os.path.join(tmp, 't.cpp')
        open(cpp, 'w').write(code)
        exe = os.path.join(tmp, 't')
        r = subprocess.run(['clang++', '-std=c++14', '-w', cpp, '-o', exe], capture_output=True, text=True)
        if r.returncode:
            print(r.stderr[-3000:])
            print('CANNOT RUN: compile failed')
            return 2
        r = subprocess.run([exe], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        if r.returncode:
            print('FAIL #1868: the caret does not reach the saved selection' + (' (baseline, as expected)' if BASELINE else ''))
            return 1
        print('PASS #1868: x2t writes the caret the editor sent' + (' (BASELINE?!)' if BASELINE else ''))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())

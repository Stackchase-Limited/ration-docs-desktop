#!/bin/sh
# #2022 - "Spreadsheet CSV not exporting with full commas".
#
# Saving a sheet as CSV pads every short row out to the width of the used
# range - except the last one. CSheetData::fromXLSB flags the final row
# (core/OOXML/XlsxFormat/Worksheets/SheetData.cpp:5002) and the `&& !bLast`
# guard in CSVWriter::Impl::WriteRowEnd then skips its trailing delimiters, so
# any reader that counts fields per line drops the last row's last columns.
#
#   BASELINE=1 ./run.sh   re-reads CSVWriter.cpp from git HEAD; must FAIL.
set -e
cd "$(dirname "$0")"
python3 ./extract.py > harness.cpp
clang++ -std=c++14 -Wall -Wno-unused-parameter -o harness harness.cpp
./harness
rm -f harness harness.cpp

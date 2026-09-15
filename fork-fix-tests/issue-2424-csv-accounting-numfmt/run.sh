#!/bin/sh
# Found while reproducing #2424 (cells with the Accounting number format).
#
# The reported symptom - Accounting cells printing as #### - is decided in
# sdkjs, not here, and did not reproduce through x2t's PDF path. What did
# reproduce, with the shipped x2t, is a separate core defect on the same
# format: saving the sheet as CSV writes the number format's padding
# directives into the cell.
#
#   $ x2t acct.xlsx acct.csv        # 8745, Accounting, before the fix
#   _ * 8745.00_ ,_ ¥* 8745.00_ ,8745.00
#
# CSVWriter::Impl::ConvertValueCellToString pastes format_code.substr(0,
# pos_start) and substr(pos_end + 1) around a boost::format directive as if
# they were plain text. numfmt_literal resolves them properly.
#
#   BASELINE=1 ./run.sh   re-reads CSVWriter.cpp from git HEAD; must FAIL.
set -e
cd "$(dirname "$0")"
python3 ./extract.py > harness.cpp
clang++ -std=c++14 -Wall -o harness harness.cpp
./harness
rm -f harness harness.cpp

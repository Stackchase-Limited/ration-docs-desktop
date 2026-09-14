#!/bin/sh
# #2301 - a hexadecimal value in a CSV was imported as a number.
#
# DigitReader::ReadDigit decides whether a CSV cell is a number by handing it to
# wcstod. wcstod accepts C99 hexadecimal floating literals, so "0x1A" is 26,
# "0XFF" is 255, and the reporter's 41-character wallet address parses cleanly as
# 4.15e46 - consuming every character, so nothing downstream can tell it was not
# meant as a number. The text is thrown away.
#
# This extracts the real IsHexLiteral by brace matching and checks it against the
# values wcstod gets wrong, and against ordinary numbers it must not touch. It
# also demonstrates the defect rather than asserting it: for every hex input it
# first confirms wcstod really does accept the whole string.
set -e
cd "$(dirname "$0")"
SRC=../../core/OOXML/Binary/Sheets/Reader/CellFormatController/DigitReader.cpp
python3 ./extract.py "$SRC" > harness.cpp
clang++ -std=c++14 -Wall -o harness harness.cpp
./harness
rm -f harness harness.cpp

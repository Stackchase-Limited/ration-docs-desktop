#!/bin/bash
# Convert a document with x2t, headlessly - no GUI, no editor.
#
#   harness/bin/x2t.sh in.xlsx out.csv
#   harness/bin/x2t.sh in.docx out.pdf
#   harness/bin/x2t.sh in.xlsx out.bin 8193      # explicit format id
#
# Useful for the file-format and converter bugs, where the question is what
# ends up in the output rather than what the UI did. Format ids come from
# core/Common/OfficeFileFormats.h.
set -euo pipefail
cd "$(dirname "$0")/.."
source lib/env.sh
rd_require_app

IN="${1:-}"
OUT="${2:-}"
FMT="${3:-}"
[ -n "$IN" ] && [ -n "$OUT" ] || { echo "usage: x2t.sh <in> <out> [formatId]" >&2; exit 2; }
[ -f "$IN" ] || { echo "x2t.sh: no such file: $IN" >&2; exit 1; }

X2T="$(rd_x2t)"
[ -n "$X2T" ] || { echo "x2t.sh: no x2t found (build the app, or install an editor)" >&2; exit 1; }
# Run it from its own directory so the sibling frameworks resolve.
CONV="$(dirname "$X2T")"
FRAMEWORKS="$(rd_x2t_frameworks "$X2T")"

# AVS_OFFICESTUDIO_FILE_* from core/Common/OfficeFileFormats.h
if [ -z "$FMT" ]; then
	case "${OUT##*.}" in
		docx) FMT=65   ;;  # DOCUMENT + 0x01
		odt)  FMT=67   ;;
		txt)  FMT=69   ;;
		rtf)  FMT=68   ;;
		pptx) FMT=129  ;;  # PRESENTATION + 0x01
		odp)  FMT=131  ;;
		xlsx) FMT=257  ;;  # SPREADSHEET + 0x01
		ods)  FMT=259  ;;
		csv)  FMT=260  ;;
		pdf)  FMT=513  ;;  # CROSSPLATFORM + 0x01
		# .bin is the editors' internal format and the extension does not say which
		# editor, so refuse rather than guess - picking Word for a spreadsheet bin
		# fails inside x2t with the opaque error 88 (CONVERT_PARAMS).
		bin)  echo "x2t.sh: .bin is ambiguous - pass a format id: 8193 word, 8194 spreadsheet, 8195 presentation, 8196 pdf, 8197 draw" >&2; exit 2 ;;
		*) echo "x2t.sh: unknown output type '${OUT##*.}' - pass a format id" >&2; exit 2 ;;
	esac
fi

# A text-ish input needs more than the output format. x2t works the conversion
# direction out from the extensions, but for csv/tsv/txt it refuses with 89
# (CONVERT_NEED_PARAMS) unless the source format and the delimiter are spelled out -
# the encoding and delimiter are not guessable, so it will not guess. Without these
# three lines every CSV input fails with an error code that says nothing about why.
#
# Encoding is the table INDEX from core/UnicodeConverter/UnicodeConverter_Encodings.h
# (46 is UTF-8), not a Windows code page - see #1359, where the two being confused
# segfaulted the converter. Override either with RD_CSV_ENCODING / RD_CSV_DELIMITER.
FROM_XML=""
case "${IN##*.}" in
	csv)  FROM_XML="<m_nFormatFrom>260</m_nFormatFrom>" ;;
	tsv)  FROM_XML="<m_nFormatFrom>262</m_nFormatFrom>" ;;
	txt)  FROM_XML="<m_nFormatFrom>69</m_nFormatFrom>"  ;;
esac
if [ -n "$FROM_XML" ]; then
	FROM_XML="$FROM_XML
<m_nCsvTxtEncoding>${RD_CSV_ENCODING:-46}</m_nCsvTxtEncoding>
<m_nCsvDelimiter>${RD_CSV_DELIMITER:-4}</m_nCsvDelimiter>"
fi

FONTS="$(dirname "$(rd_settings_file)")/fonts"
PARAMS="$(mktemp -t rd-x2t).xml"
cat > "$PARAMS" <<XML
<?xml version="1.0" encoding="utf-8"?><TaskQueueDataConvert>
<m_sFileFrom>$(cd "$(dirname "$IN")" && pwd)/$(basename "$IN")</m_sFileFrom>
<m_sFileTo>$OUT</m_sFileTo>
$FROM_XML
<m_nFormatTo>$FMT</m_nFormatTo>
<m_sFontDir>$FONTS</m_sFontDir>
</TaskQueueDataConvert>
XML

set +e
( cd "$CONV" && DYLD_LIBRARY_PATH="$CONV" LD_LIBRARY_PATH="$CONV" \
  DYLD_FRAMEWORK_PATH="$FRAMEWORKS" "./$(basename "$X2T")" "$PARAMS" )
rc=$?
set -e
rm -f "$PARAMS"

if [ $rc -ne 0 ]; then
	echo "x2t failed with code $rc (format $FMT)" >&2
	exit $rc
fi
echo "wrote $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes, format $FMT)"

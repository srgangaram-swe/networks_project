#!/bin/sh
# Compile the report from its tracked sources; keep auxiliary files local.
set -eu
for REPORT_TOOL in pdflatex bibtex rg; do
    command -v "$REPORT_TOOL" >/dev/null || {
        echo "Missing report build tool: $REPORT_TOOL" >&2
        exit 1
    }
done
cd "$(dirname "$0")/.."
REPORT_ROOT="$(pwd)"
REPORT_BUILD="$REPORT_ROOT/.local/report-build"
mkdir -p "$REPORT_BUILD"
cd deliverables
pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$REPORT_BUILD" report.tex
(
    cd "$REPORT_BUILD"
    BIBINPUTS="$REPORT_ROOT/deliverables:" bibtex report
)
pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$REPORT_BUILD" report.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$REPORT_BUILD" report.tex
if rg 'LaTeX Warning: (Citation|Reference).*undefined|There were undefined references|Overfull' "$REPORT_BUILD/report.log"; then
    echo 'Review unresolved references or overflowing report content.' >&2
    exit 1
fi
cp "$REPORT_BUILD/report.pdf" "$REPORT_ROOT/deliverables/report.pdf"

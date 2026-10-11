#!/usr/bin/env bash
# Run the sample inputs in examples/data through the CLI.
#
# Needs: thereabouts data install core postal airports ip locode phone plates
# Run:   bash examples/cli/batch.sh [DATA_DIR]
# Set THEREABOUTS to run a different launcher, e.g. THEREABOUTS="npx thereabouts".
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="$HERE/../data"
read -r -a CMD <<< "${THEREABOUTS:-thereabouts}"
if [ $# -ge 1 ]; then CMD+=(--data-dir "$1"); fi

# 1. Reverse has a native batch mode: reverse FILE (or -). The CSV needs a header with lat/lon
#    (or latitude/longitude, lng). Input columns pass through, then result columns are
#    appended with the prefix thereabouts_ (thereabouts_status, thereabouts_city.name, ...).
#    Exit status 5 means some rows were invalid; the rest were still processed.
echo "== reverse: city_points.csv to CSV with selected result columns =="
"${CMD[@]}" reverse "$DATA/city_points.csv" --csv --fields status,city.name,country.code,match |
  head -n 6
echo "... (47 rows in total; expected_city and thereabouts_city.name should agree)"

echo
echo "== reverse: the same file as NDJSON, one object per row, through stdin =="
"${CMD[@]}" reverse - --format ndjson --fields status,city.name,country.code < "$DATA/city_points.csv" |
  head -n 3

# 2. The other verbs take one value per call, so loop over the rows.
#    The files have no quoted fields, so a plain comma split is safe here.
echo
echo "== postal: postal.csv =="
tail -n +2 "$DATA/postal.csv" | while IFS=, read -r code country expected; do
  printf '%-10s expected %-14s ' "$code" "$expected"
  "${CMD[@]}" postal "$code" --country "$country" --format ndjson --fields status,city.name,country.code
done

echo
echo "== airport: airports.csv =="
tail -n +2 "$DATA/airports.csv" | while IFS=, read -r code scheme country name; do
  printf '%-6s expected %-22s ' "$code" "$name"
  "${CMD[@]}" airport "$code" --scheme "$scheme" --format ndjson --fields status,city.name,country.code
done

echo
echo "== locode: locode.csv =="
tail -n +2 "$DATA/locode.csv" | while IFS=, read -r code country name; do
  printf '%-6s expected %-12s ' "$code" "$name"
  "${CMD[@]}" locode "$code" --format ndjson --fields status,city.name,country.code
done

echo
echo "== phone: phone.csv =="
tail -n +2 "$DATA/phone.csv" | while IFS=, read -r number country; do
  printf '%-20s expected %-3s ' "$number" "$country"
  "${CMD[@]}" phone "$number" --format ndjson --fields status,country.code
done

echo
echo "== ip: ip.csv =="
tail -n +2 "$DATA/ip.csv" | while IFS=, read -r address country note; do
  printf '%-22s expected %-4s ' "$address" "${country:-none}"
  "${CMD[@]}" ip "$address" --format ndjson --fields status,country.code
done

echo
echo "== plate: plates.csv (no country given, so some rows are ambiguous) =="
tail -n +2 "$DATA/plates.csv" | while IFS=, read -r plate country; do
  printf '%-14s expected %-3s ' "$plate" "$country"
  "${CMD[@]}" plate "$plate" --format ndjson --fields status,country.code
done

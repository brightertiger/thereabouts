#!/usr/bin/env bash
# One command per lookup family. Output is JSON (--json) so the shape is easy to read.
#
# Needs: thereabouts data install core postal airports ip locode phone plates
# Run:   bash examples/cli/quickstart.sh [DATA_DIR]
# With no DATA_DIR the CLI uses THEREABOUTS_DATA or the platform default store.
# Set THEREABOUTS to run a different launcher, e.g. THEREABOUTS="npx thereabouts".
set -u

read -r -a CMD <<< "${THEREABOUTS:-thereabouts}"
if [ $# -ge 1 ]; then CMD+=(--data-dir "$1"); fi

run() { printf '\n$ thereabouts %s\n' "$*"; "${CMD[@]}" "$@" || printf '(exit %s)\n' "$?"; }

# Every result has the same keys: status, kind, match, country, state, city, timezone,
# point, cell, distance_band, candidates, rank_basis (and hint / evidence when present).
# status is matched | ambiguous | not_found | invalid_input | unsupported_granularity.

# reverse: coordinates to place.
# Expect: status "matched", kind "cell", match "contained",
#         country.code "FR", city.name "Paris", timezone "Europe/Paris".
run reverse --lat 48.8566 --lon 2.3522 --json

# Same lookup with evidence: adds an "evidence" object (city_method, land_method, reason).
run reverse --lat 48.8566 --lon 2.3522 --json --evidence

# Open water is an answer, not an error.
# Expect: status "not_found", country null; with --evidence, evidence.reason "no_land".
run reverse --lat 19.0 --lon 72.6 --json --evidence

# h3: the stored ancestor of a cell at resolution 0 to 8.
# Expect: status "matched" and the city/country containing the cell (Paris area).
run h3 881fb46625fffff --json

# geocode: towns and cities by name. Street addresses are not supported.
# Expect: status "matched", city.name "Paris", country.code "FR".
run geocode "Paris" --country FR --json

# A name shared by many cities stays ambiguous unless you ask for the largest.
# Expect: status "ambiguous" with ranked "candidates"; the second call returns one match.
run geocode "Springfield" --country US --limit 5 --fields status,rank_basis,candidates
run geocode "Springfield" --country US --prefer population --fields status,city.name,state.name

# postal: the country is required.
# Expect: status "matched", kind "postal", city.name "Paris", country.code "FR".
run postal 75001 --country FR --fields status,kind,city.name,country.code

# airport: IATA then ICAO unless --scheme is given.
# Expect: kind "airport", country.code "FR", city.name "Tremblay-en-France" (the canonical
# settlement, not the postal town).
run airport CDG --scheme iata --fields status,kind,city.name,country.code
run airport EGLL --scheme icao --fields status,kind,city.name,country.code

# locode: five characters, or three characters plus --country.
# Expect: kind "trade_location", country.code "BE", city.name "Antwerp".
run locode BEANR --fields status,kind,city.name,country.code

# phone: international E.164 with a leading +. The result is a calling-code prefix.
# Expect: kind "phone_prefix", country.code "BE", city null.
run phone "+32 2 555 1234" --fields status,kind,country.code,city.name

# ip: IPv4 or IPv6 literal. The location belongs to the provider's range, not the device.
# Expect: kind "ip_range", country.code "US" (city is the range's city, e.g. Mountain View).
run ip 8.8.8.8 --fields status,kind,country.code,city.name
# A documentation address has no country. Release 2026.10 answers status "matched" with
# country null (older text said not_found); either way there is no country to trust.
run ip 192.0.2.1 --fields status,kind,country.code

# plate: registration format evidence. Pass --country to keep the context exact.
# Expect: status "matched" or "ambiguous" (candidates list the countries with that format).
run plate "05-GJV-1" --fields status,kind,country.code,rank_basis
run plate "05-GJV-1" --country NL --fields status,kind,country.code

# Management commands. They print installed packs and never touch the network.
run data path
run data list
run info --json

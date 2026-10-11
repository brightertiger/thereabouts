# Sample inputs

Plain CSV files with a header row and no comment lines, so the command line can read them
directly. Every file has fewer than 200 rows. The `expected_*` columns are the answers each
example script compares against.

| File | Rows | Needs pack | Where the expected answers come from |
| --- | ---: | --- | --- |
| `city_points.csv` | 47 | core | Evaluation ground truth: every second and fourth row of `eval/city_points/points.csv` (columns `id`, `group`, `lat`, `lon`, `expected_name`, `accepted_names`, `country_code`), minus the one row marked ambiguous. Each point was desk-reviewed against public sources on 2026-10-02. The city rule is the owner's: the containing city, never a ward or district, but independent neighbours (Howrah, Noida, Thane, Navi Mumbai, Yokohama, Petaling Jaya) keep their own names. `accepted_names` is a `\|` separated list of names that count as the same settlement. |
| `plates.csv` | 20 | plates | Evaluation ground truth: the `country_code` and transcribed plate text of 20 entries in `eval/plate_country/evaluation.yaml` (the regex escapes in `pattern` removed). A plate is format evidence, not a register, so a plate may legitimately come back `ambiguous` with the expected country among the candidates. |
| `postal.csv` | 11 | postal | Hand-picked, well-known postcodes. Not part of the evaluation. `expected_city` is the place the code is named for, so a result for a neighbouring locality still counts as a plausible match. |
| `airports.csv` | 13 | airports | Hand-picked IATA and ICAO codes of major airports. Not part of the evaluation. The airport's own `city` is the canonical settlement, not the postal town: Paris-Charles de Gaulle reports Tremblay-en-France. |
| `locode.csv` | 10 | locode | Hand-picked UN/LOCODEs of major ports. Not part of the evaluation. |
| `phone.csv` | 9 | phone | Hand-picked E.164 numbers using numbers reserved for illustration where one exists. A phone result is a calling-code prefix, not proof the number exists. `+1` is shared by several countries and may be `ambiguous`. |
| `ip.csv` | 9 | ip | Public resolvers with a well-known country, plus the documentation (RFC 5737, RFC 3849), private and loopback ranges, which should be `not_found`. An IP result is the provider's range location, not the device. |

The expected answers are a smoke check for a first run. Some rows will differ from the
expectation on a given release, and the examples print a mismatch instead of failing.

# Query recipes

Tested SQL for common analytical questions over the Thereabouts dataset. Every block here runs against a small fixture release in the test suite and against the full release in the world end-to-end test. Column names, units and coded values are in `tables.md`; look them up there or with `describe` rather than guessing.

Set `DATASET` to the release directory (`.../dataset/<version>`). For an https base URL, build the views with `open_dataset` from `SKILL.md`, which reads `manifest.json` because DuckDB cannot glob over HTTP.

```python
import json
from pathlib import Path

import duckdb

manifest = json.loads((Path(DATASET) / "manifest.json").read_text())
con = duckdb.connect()
for table in sorted({entry["kind"] for entry in manifest["tables"]}):
    con.sql(
        f"CREATE VIEW {table} AS SELECT * FROM "
        f"read_parquet('{DATASET}/{table}/**/*.parquet', hive_partitioning = false)"
    )
```

## Follow a pack answer into the tables

A lookup returns identifiers. Locate the port of Antwerp, then read its canonical city row.

```mcp
locode {"code": "BEANR"}
```

```json
{"status": "matched", "kind": "trade_location", "city": {"id": "city:geonames:2803138"}}
```

```sql
SELECT city_id, name, kind, population
FROM canonical_cities
WHERE city_id = 'city:geonames:2803138'
```

```csv
city_id,name,kind,population
city:geonames:2803138,Antwerp,city,529247
```

Places that roll up into a city are mapped by `place_to_city`. A place whose method is `spatial_absorption` or `policy_part` is part of the city, not a separate result:

```sql
SELECT p.name, m.method
FROM place_to_city m
JOIN places p USING (place_id)
WHERE m.city_id = 'city:geonames:2988507' AND m.place_id <> m.city_id
```

```csv
name,method
Paris 1er Arrondissement,spatial_absorption
```

## Find every row for a code

The packs return a ranked answer. Use SQL when the user wants all observations.

```sql
SELECT place_name, admin1_name
FROM postal_codes
WHERE country_code = 'IN' AND postal_code = '744301'
ORDER BY place_name
```

```csv
place_name,admin1_name
Mus,
Passa,
```

Ports are the UN/LOCODE entries whose function field starts with `1`. The field has eight positions; `1` port, `2` rail, `3` road, `4` airport, `5` postal, `6` multimodal, `7` fixed transport, `B` border crossing, and `-` where the function is absent.

```sql
SELECT locode, name
FROM trade_locations
WHERE country_code = 'BE' AND function LIKE '1%'
ORDER BY locode
```

```csv
locode,name
BEANR,Antwerpen
```

```sql
SELECT name, icao_code, municipality
FROM airports
WHERE iata_code = 'CDG'
```

```csv
name,icao_code,municipality
Charles de Gaulle International Airport,LFPG,"Paris (Roissy-en-France, Val-d'Oise)"
```

## Rank and count

The most populous canonical city in each country:

```sql
SELECT country_code, name, population
FROM canonical_cities
QUALIFY rank() OVER (PARTITION BY country_code ORDER BY population DESC) = 1
ORDER BY country_code
```

```csv
country_code,name,population
BE,Brussels,1019022
FR,Paris,2138551
US,Mountain View,80435
```

Cities and towns per country. `kind` is `city` or `town`:

```sql
SELECT country_code, kind, count(*) AS places
FROM canonical_cities
GROUP BY 1, 2
ORDER BY 1, 2
```

```csv
country_code,kind,places
BE,city,2
FR,city,1
FR,town,1
US,city,1
```

Settlements by kind. The count is of `places` rows, which include absorbed parts and districts, so it is not a count of cities:

```sql
SELECT settlement_kind, count(*) AS places
FROM places
GROUP BY 1
ORDER BY 2 DESC, 1
```

```csv
settlement_kind,places
state,5
city,4
country,4
settlement,2
city_part,1
town,1
```

## Hierarchy

Cities of a subdivision, joined on `parent_id`:

```sql
SELECT c.name, c.role
FROM places c
JOIN places s ON c.parent_id = s.place_id
WHERE s.name = 'Île-de-France' AND c.role IN ('city', 'town')
ORDER BY c.name
```

```csv
name,role
Paris,city
```

Countries with their codes and currency:

```sql
SELECT name, alpha3, calling_code, currency
FROM countries
WHERE country_code IN ('BE', 'FR')
ORDER BY name
```

```csv
name,alpha3,calling_code,currency
Belgium,BEL,32,EUR
France,FRA,33,EUR
```

## Measure with cells

`cells` stores one row per land cell, compacted: a row of resolution 7 stands for 7 resolution 8 cells. Weight every row by `7^(8 - h3_resolution)` to count resolution 8 cells. Cell counts approximate area, because H3 cells differ slightly in size.

How much of each country's land has its city chosen by a distant nearest-settlement rule:

```sql
SELECT
  country_id,
  sum(power(7, 8 - h3_resolution))::BIGINT AS r8_cells,
  round(
    100 * sum(power(7, 8 - h3_resolution))
      FILTER (WHERE city_method = 'rural_nearest_distant')
    / sum(power(7, 8 - h3_resolution)),
    1
  ) AS distant_percent
FROM cells
GROUP BY 1
ORDER BY 1
```

```csv
country_id,r8_cells,distant_percent
country:BE,50,
country:FR,9,
country:US,8,87.5
```

`distant_percent` is null where no cell has that method. Report it as 0 only if that is what you mean.

## IP addresses, phone numbers and timezones

An address is stored as 16 big-endian bytes, with IPv4 left-padded with zeros. Compute the bytes in Python with `ipaddress.ip_address("8.8.8.8").packed.rjust(16, b"\0").hex()` and compare as hex blobs:

```sql
SELECT ip_start, ip_end, city, region
FROM ip_ranges
WHERE ip_version = 4
  AND ip_start_packed <= from_hex('00000000000000000000000008080808')
  AND ip_end_packed >= from_hex('00000000000000000000000008080808')
```

```csv
ip_start,ip_end,city,region
8.8.8.0,8.8.8.255,Mountain View,California
```

The longest published prefix of a number, without the plus. Prefixes repeat once per language, so fix one:

```sql
SELECT prefix, description, array_to_string(country_codes, '/') AS countries
FROM phone_prefixes
WHERE '3225551234' LIKE prefix || '%' AND language = 'en'
ORDER BY length(prefix) DESC
LIMIT 1
```

```csv
prefix,description,countries
322,Brussels,BE
```

Timezones of a country. `table` is a reserved word, so quote it; `zone.tab` lists one row per timezone and country:

```sql
SELECT tzid
FROM zone_tables
WHERE "table" = 'zone.tab' AND country_codes = 'BE'
```

```csv
tzid
Europe/Brussels
```

`timezone_cells` assigns a timezone to H3 cells independently of land, at resolutions 0 to 8, and zones can overlap. For a point, prefer the `timezone` field of `reverse`.

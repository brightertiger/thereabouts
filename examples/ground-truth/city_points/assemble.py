"""Export the manually selected, externally researched reference set.

No network calls, geocoder imports, or access outside this directory.
"""

import csv
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
FIELDS = [
    "id",
    "group",
    "role",
    "latitude",
    "longitude",
    "expected_name",
    "accepted_names",
    "expected_kind",
    "country_code",
    "expected_wikidata",
    "expected_geonames_id",
    "what_is_here",
    "source_url",
    "source_checked",
    "reason",
    "confidence",
    "ambiguous",
    "split",
]
ALIASES = {
    "Dhaka": "ঢাকা|Dacca",
    "Istanbul": "İstanbul",
    "Mumbai": "मुंबई|Bombay",
    "Delhi": "दिल्ली|دہلی|Dilli",
    "Kolkata": "কলকাতা|Calcutta",
    "Tianjin": "天津|天津市|Tientsin",
    "Shanghai": "上海|上海市",
    "Tokyo": "東京|東京都|Tōkyō|Tokio",
    "London": "Greater London",
    "New York": "New York City|City of New York|NYC",
    "Howrah": "হাওড়া|Haora|Hāora",
    "Noida": "नोएडा",
    "Thane": "ठाणे|Thana",
    "Navi Mumbai": "नवी मुंबई|New Bombay",
    "Yokohama": "横浜|横浜市|Yokohama-shi",
    "Petaling Jaya": "PJ|八打灵再也",
    "Oak Park": "Village of Oak Park",
    "Evanston": "City of Evanston",
    "Wilmette": "Village of Wilmette",
    "St Andrews": "St. Andrews|Saint Andrews|Cill Rìmhinn",
    "Bayeux": "",
    "Paraty": "Parati",
    "Swakopmund": "Tsoaxaub|Otjozondjii",
    "Takayama": "高山|高山市|Hida-Takayama|Hida Takayama",
    "Oamaru": "Ōamaru",
    "Castle Combe": "",
    "Clovelly": "",
    "Plockton": "Am Ploc",
    "Reine": "",
    "Vik": "Vík|Vík í Mýrdal|Vik i Myrdal",
    "Monsanto": "Monsanto da Beira",
    "Ogimachi": "荻町|Ōgimachi",
    "Khinalug": "Xınalıq|Khinalig|Khinaliq|Khynalyg",
    "Bario": "Pa' Ramapuh Atas|Pa Ramapuh Atas",
    "Mawlynnong": "",
    "Hogsback": "",
    "Nieu-Bethesda": "Nieu Bethesda",
    "New Norcia": "",
    "Nundle": "",
    "Terlingua": "Terlingua Ghost Town",
    "Ocracoke": "Ocracoke Village",
    "Purmamarca": "",
    "Cachora": "San Pedro de Cachora",
}
# These 6 have a Wikipedia description plus a
# map cross-check, but no sufficiently specific second non-OSM membership
# source verified during this collection. Do not imply an official address.
ONE_NON_OSM = {
    "kolkata-06",
    "tianjin-01",
    "tianjin-05",
    "howrah-03",
    "howrah-04",
    "swakopmund-02",
}
MEDIUM = ONE_NON_OSM | {
    "istanbul-05",
    "istanbul-06",
    "kolkata-05",
    "tianjin-02",
    "tianjin-04",
    "tianjin-06",
    "shanghai-02",
    "shanghai-03",
    "noida-03",
    "noida-04",
    "yokohama-03",
    "st-andrews-01",
    "bayeux-02",
    "paraty-02",
    "oamaru-01",
    "reine-01",
    "ogimachi-01",
    "bario-01",
    "mawlynnong-01",
    "nieu-bethesda-01",
    "new-norcia-01",
    "terlingua-01",
    "purmamarca-01",
    "cachora-01",
}
WHAT = {
    "dhaka-06": "Uttara High School and College playground; Sector 7, Uttara",
    "mumbai-02": "Veermata Jijabai garden grounds beside Dr. Bhau Daji Lad Museum; Byculla",
    "kolkata-04": "Science City approach near J.B.S. Haldane Avenue; Tangra",
    "tianjin-01": "Haihe Square / western forecourt beside Tianjin railway station; Hebei-Hedong station precinct",
    "tianjin-06": "Tianjin Binhai International Airport grounds near the terminal approach; Dongli",
    "shanghai-02": "Jing'an Temple precinct, Fumin Road approach; Jing'an",
    "shanghai-03": "Longhua Temple environs near West Longhua Road; Xuhui",
    "howrah-01": "Howrah Municipal Corporation headquarters, 4 Mahatma Gandhi Road; Howrah Maidan",
    "thane-03": "Hiranandani Foundation School on Wood Street; Hiranandani Estate, Thane",
    "yokohama-03": "Zoorasia southern entrance approach on Nakahara Kaido; Kamishiranecho, Asahi Ward",
    "wilmette-02": "Centennial Park and pool, 2300 Old Glenview Road; Wilmette",
    "st-andrews-01": "St Salvator's Chapel clocktower, North Street; central St Andrews",
    "paraty-01": "Rua Comendador Jose Luiz in the historic centre; Centro Historico, Paraty",
    "swakopmund-02": "New Swakopmund railway station precinct; Mandume ya Ndemufayo Street",
    "oamaru-01": "Forrester Gallery, 9 Thames Street; central Oamaru",
    "castle-combe-01": "The Street near Combe Cottage; lower Castle Combe village",
    "clovelly-01": "High Street in Clovelly village",
    "plockton-01": "Innes Street in Plockton village",
    "reine-01": "Kirkeveien in Reine village, Moskenes",
    "vik-01": "Bakkabraut in the older village centre of Vik",
    "monsanto-01": "Devesa / Avenida Fernando Ramos Rocha approach to Monsanto hill village",
    "ogimachi-01": "Wada House in Ogimachi village, Shirakawa; not the centroid of the three UNESCO villages",
    "khinalug-01": "Xinaliq village road in the core of Khinalug",
    "bario-01": "Bario airfield beside Pa' Ramapuh Atas, within the dispersed Bario village cluster",
    "mawlynnong-01": "Central Mawlynnong village, East Khasi Hills",
    "hogsback-01": "Central Hogsback village road, Amathole Mountains",
    "nieu-bethesda-01": "Owl House museum, New Street / Martins Street; Nieu-Bethesda",
    "new-norcia-01": "Benedictine community visitor precinct on New Norcia Road; New Norcia",
    "nundle-01": "Durbin Street within Nundle village",
    "terlingua-01": "Starlight Theatre at the historic Terlingua ghost-town centre",
    "ocracoke-01": "Ocracoke Lighthouse, 360 Lighthouse Road; Ocracoke village",
    "purmamarca-01": "Plaza 9 de Julio beside the municipal office; Purmamarca village",
    "cachora-01": "Northern village approach / agricultural locality beside San Pedro de Cachora",
}
REASONS = {
    "dhaka-01": "The national museum publishes a Shahbagh, Dhaka address, identifying the containing city.",
    "dhaka-02": "The Bangladesh submission to UNESCO explicitly locates Lalbagh Fort in Dhaka City.",
    "dhaka-03": "Parliament gives its address as Sher-e-Bangla Nagar, Dhaka, so the district is subordinate to Dhaka.",
    "dhaka-04": "The architect-supplied mosque description places this Gulshan building in Dhaka.",
    "dhaka-05": "The zoo publishes Zoo Road, Mirpur, Dhaka as its address, making Mirpur a city subunit here.",
    "dhaka-06": "The school gives Sector 7, Uttara Model Town, Dhaka as its address, so Uttara is not the city answer.",
    "delhi-01": "Connaught Place is in New Delhi, which the owner explicitly groups under Delhi.",
    "delhi-02": "India Gate is in New Delhi, which the owner explicitly groups under Delhi.",
    "london-01": "Trafalgar Square lies in Westminster, which the owner explicitly groups under London.",
    "tokyo-02": "The metropolitan government building is in Shinjuku, which the owner explicitly groups under Tokyo.",
    "new-york-02": "The museum is in Brooklyn, a borough of New York under the owner's city rule.",
    "howrah-04": "The station is in Howrah Maidan west of the Hooghly, in the independent city of Howrah.",
    "noida-04": "Sector 16 is inside Noida on its Delhi-facing side and retains the independent Noida city answer.",
    "thane-04": "The temple operator explicitly gives Jambli Naka, Thane, rather than the neighbouring Mumbai municipality.",
    "navi-mumbai-04": "Vashi is a node within Navi Mumbai, whose municipal development plan distinguishes it from Mumbai.",
    "yokohama-04": "Tokyu gives the station address as Kikuna, Kohoku-ku, Yokohama, retaining the independent Yokohama answer.",
    "petaling-jaya-04": "Jaya One publishes a Section 13, Petaling Jaya address on the Kuala Lumpur-facing side of the city.",
    "bario-01": "Tourism sources describe the Bario village cluster while the airfield map names Pa' Ramapuh Atas, so either settlement interpretation is accepted.",
    "ogimachi-01": "Shirakawa village government explicitly places Wada House in the village of Ogimachi.",
    "new-norcia-01": "The Benedictine community's own directions map places this visitor precinct in New Norcia.",
    "terlingua-01": "The theatre operator explicitly locates the building in Terlingua Ghost Town, separate from Study Butte.",
    "purmamarca-01": "The municipal site and national heritage description identify the village surrounding Plaza 9 de Julio as Purmamarca.",
    "cachora-01": "A Peruvian government field-locality record labels these coordinates Cachora, beside the independently mapped village.",
}

rows = list(csv.DictReader((ROOT / "coordinates.csv").open()))
primary = {
    r["id"]: r["url"]
    for r in csv.DictReader((ROOT / "primary_sources.tsv").open(), delimiter="\t")
}
places = json.loads((ROOT / "sources" / "place-identifiers.json").read_text())
final = []
evidence = []
for r in rows:
    ident = places.get(r["expected_name"], {})
    qid = (ident.get("qid") or [""])[0]
    if r["expected_name"] in {"Monsanto", "Reine", "Ogimachi", "Cachora"}:
        qid = ""
    entity_path = ROOT / "sources" / (qid + "-wikidata.json")
    entity = json.loads(entity_path.read_text()) if qid and entity_path.exists() else {}
    gn = [
        c.get("mainsnak", {}).get("datavalue", {}).get("value", "")
        for c in entity.get("claims", {}).get("P1566", [])
        if c.get("rank") != "deprecated"
    ]
    # Omit mixed settlement/administrative IDs unless resolved on public pages.
    geonames = gn[0] if len(gn) == 1 else ""
    geonames = {
        "Istanbul": "745044",
        "Tianjin": "1792947",
        "Shanghai": "1796236",
        "Tokyo": "1850147",
        "London": "2643743",
        "Yokohama": "1848354",
    }.get(r["expected_name"], geonames)
    cache = ROOT / "sources" / ("nominatim-final-" + r["id"] + ".json")
    if not cache.exists():
        cache = ROOT / "sources" / ("nominatim-reverse-" + r["id"] + ".json")
    cross = json.loads(cache.read_text())
    v = cross["result"]
    cross_url = (
        "https://www.openstreetmap.org/" + v["osm_type"] + "/" + str(v["osm_id"])
    )
    coordinate = r["coordinate_source"]
    # Reuse the actual cached API URL, rather than an illustrative query URL.
    if "nominatim.openstreetmap.org" in coordinate:
        path = ROOT / "sources" / ("nominatim-search-" + r["id"] + ".json")
        if r["id"] == "terlingua-01":
            path = ROOT / "sources" / "nominatim-search-terlingua-final.json"
        coordinate = json.loads(path.read_text())["url"]
    urls = list(dict.fromkeys([primary[r["id"]], coordinate, cross_url]))
    if r["id"] == "terlingua-01":
        urls.insert(1, "https://www.thestarlighttheatre.com/")
    if r["id"] == "new-norcia-01":
        urls.insert(1, "https://mapcarta.com/N4188733589")
    if r["group"] in {"large-city", "neighbour"}:
        kind = "city"
        default_reason = f"The documented {r['page']} location is in {r['locality']}, an urban part of {r['expected_name']}."
    elif r["group"] == "town":
        kind = (
            "city"
            if r["expected_name"] in {"Evanston", "Swakopmund", "Takayama"}
            else "town"
        )
        default_reason = f"The landmark's documented address places it inside the separate municipality of {r['expected_name']}."
    else:
        kind = "village"
        default_reason = f"The settlement description and map identify this location with the remote village of {r['expected_name']}."
    row = {k: r.get(k, "") for k in FIELDS}
    row.update(
        latitude=f"{float(r['latitude']):.6f}",
        longitude=f"{float(r['longitude']):.6f}",
        accepted_names=ALIASES[r["expected_name"]],
        expected_kind=kind,
        expected_wikidata=qid,
        expected_geonames_id=geonames,
        what_is_here=WHAT.get(r["id"], r["page"] + "; " + r["locality"]),
        source_url="|".join(urls),
        source_checked="2026-10-02",
        reason=REASONS.get(r["id"], default_reason),
        confidence="medium" if r["id"] in MEDIUM else "high",
        ambiguous="yes" if r["id"] == "bario-01" else "no",
    )
    final.append(row)
    families = set()
    for url in urls:
        host = urlsplit(url).hostname or ""
        if any(
            s in host for s in ("openstreetmap", "mapcarta", "wikidata", "geonames")
        ):
            continue
        families.add(
            "wikipedia.org" if "wikipedia.org" in host else host.removeprefix("www.")
        )
    evidence.append(
        dict(
            id=r["id"],
            membership_source=primary[r["id"]],
            coordinate_source=coordinate,
            map_source=cross_url,
            map_cache=str(cache.relative_to(ROOT)),
            map_country=v["address"]["country_code"].upper(),
            map_feature=v.get("display_name", ""),
            non_osm_source_families=len(families),
            osm_only="no",
            review_note=r["note"],
        )
    )
for filename, records, fields in [
    ("points.csv", final, FIELDS),
    ("evidence.csv", evidence, list(evidence[0])),
]:
    with (ROOT / filename).open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
print("Exported", len(final), "points and evidence rows")

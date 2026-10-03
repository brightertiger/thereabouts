//! Stage published phone prefixes plus metadata calling-code fallbacks; geography uses links only.
use crate::{
    Result, arrow::Row, catalogue, error::ensure, forward, inserts::Inserts, source::Dataset,
};
use rusqlite::Connection;
use thereabouts_core::format::observation::Observation;
pub(crate) fn load(data: &Dataset, db: &Connection) -> Result<()> {
    forward::initialize(db)?;
    let mut inserts = Inserts::new(db, "INSERT INTO observations", 12);
    for kind in ["phone_prefixes", "phone_metadata"] {
        for table in data.tables(kind) {
            data.scan(table, |row| {
                let metadata = kind == "phone_metadata";
                let prefix = row.required(if metadata { "calling_code" } else { "prefix" })?;
                ensure(
                    thereabouts_core::format::trie::valid_prefix(prefix),
                    "Invalid phone prefix",
                )?;
                let countries = if metadata {
                    vec![row.required("territory")?.into()]
                } else {
                    row.texts("country_codes")?
                };
                ensure(!countries.is_empty(), "Phone prefix has no country")?;
                for code in countries {
                    // Territory 001 is a published non-geographic service; no country result exists.
                    if code == "001" {
                        continue;
                    }
                    ensure(
                        code.len() == 2 && code.bytes().all(|b| b.is_ascii_uppercase()),
                        "Invalid phone country",
                    )?;
                    let country = catalogue::reference(db, Some(&format!("country:{code}")))?;
                    let mut places = row.texts("place_ids")?;
                    if places.is_empty() {
                        places.extend(row.text("place_id")?.map(str::to_owned));
                    }
                    let mut refs = Vec::new();
                    for id in places {
                        let place = catalogue::record(db, &id)?;
                        if place.refs[0] != country {
                            continue;
                        }
                        let geography = crate::geography::geography(db, country, &id)?;
                        if !refs.contains(&geography) {
                            refs.push(geography);
                        }
                    }
                    if refs.is_empty() {
                        refs.push([country, 0, 0]);
                    }
                    for places in refs {
                        let record = record(row, places, prefix, metadata)?;
                        forward::insert(&mut inserts, prefix.into(), record)?;
                    }
                }
                Ok(())
            })?;
        }
    }
    inserts.flush()
}
fn record(row: Row<'_>, places: [u32; 3], prefix: &str, metadata: bool) -> Result<Observation> {
    let mut details = serde_json::Map::new();
    for field in [
        "language",
        "description",
        "calling_code",
        "leading_digits",
        "national_prefix",
        "international_prefix",
        "link_status",
        "link_method",
    ] {
        if let Some(v) = row.text(field)? {
            details.insert(field.into(), v.into());
        }
    }
    Ok(Observation {
        places,
        latitude: i32::MIN,
        longitude: i32::MIN,
        text: [
            Some(row.required("source")?.into()),
            Some(row.required("source_id")?.into()),
            row.text("description")?.map(str::to_owned),
            Some(prefix.into()),
            Some(if metadata { "calling_code" } else { "prefix" }.into()),
            Some(serde_json::to_string(&details)?),
        ],
    })
}

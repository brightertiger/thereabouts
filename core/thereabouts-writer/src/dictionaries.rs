//! SQLite dictionaries keep pack-level interning bounded during world exports.
use crate::{Result, blocks::Output, error::ensure};
use rusqlite::{Connection, OptionalExtension};
use std::path::Path;
use thereabouts_core::format::{columns, manifest::Manifest, table};
pub(crate) struct Dictionaries<'a> {
    pub(crate) db: &'a Connection,
}
impl<'a> Dictionaries<'a> {
    pub(crate) fn new(db: &'a Connection) -> Result<Self> {
        for name in [
            "strings",
            "evidence_strings",
            "geographies",
            "locations",
            "details",
        ] {
            db.execute_batch(&format!(
                "CREATE TABLE compact_{name}(id INTEGER PRIMARY KEY,value BLOB UNIQUE)"
            ))?;
            let empty = if name.ends_with("strings") {
                None
            } else {
                Some(vec![
                    0;
                    match name {
                        "geographies" => 3,
                        "locations" => 4,
                        _ => 0,
                    } * 8
                ])
            };
            db.execute(
                &format!("INSERT INTO compact_{name}(id,value) VALUES(0,?)"),
                [empty],
            )?;
        }
        Ok(Self { db })
    }
    fn intern(&self, name: &str, bytes: &[u8]) -> Result<u64> {
        let mut query = self
            .db
            .prepare_cached(&format!("SELECT id FROM compact_{name} WHERE value=?"))?;
        if let Some(id) = query.query_row([bytes], |r| r.get(0)).optional()? {
            return Ok(id);
        }
        self.db
            .prepare_cached(&format!("INSERT INTO compact_{name}(value) VALUES(?)"))?
            .execute([bytes])?;
        Ok(self.db.last_insert_rowid().cast_unsigned())
    }
    pub(crate) fn string(&self, value: Option<&str>, evidence: bool) -> Result<u64> {
        let Some(value) = value else {
            return Ok(0);
        };
        if evidence {
            let existing = self
                .db
                .prepare_cached("SELECT id FROM compact_strings WHERE value=?")?
                .query_row([value.as_bytes()], |r| r.get::<_, u64>(0))
                .optional()?;
            if let Some(id) = existing {
                return Ok(id * 2);
            }
        }
        let id = self.intern(
            if evidence {
                "evidence_strings"
            } else {
                "strings"
            },
            value.as_bytes(),
        )?;
        Ok(id * 2 + u64::from(evidence))
    }
    pub(crate) fn tuple(&self, name: &str, values: &[u64]) -> Result<u64> {
        let bytes = values
            .iter()
            .flat_map(|v| v.to_le_bytes())
            .collect::<Vec<_>>();
        self.intern(name, &bytes)
    }
    pub(crate) fn emit(&self, stage: &Path, manifest: &mut Manifest, details: usize) -> Result<()> {
        for role in [
            "strings",
            "evidence_strings",
            "geographies",
            "locations",
            "details",
        ]
        .into_iter()
        .filter(|role| details != 0 || role.ends_with("strings"))
        {
            let strings = role.ends_with("strings");
            let mut output = Output::new(
                stage,
                role,
                if strings {
                    table::STRING_KIND
                } else {
                    table::INTEGER_KIND
                },
            );
            let mut query = self
                .db
                .prepare(&format!("SELECT id,value FROM compact_{role} ORDER BY id"))?;
            let mut numeric = Vec::new();
            let mut text = Vec::new();
            let mut size = 4;
            for row in query.query_map([], |r| {
                Ok((r.get::<_, u64>(0)?, r.get::<_, Option<Vec<u8>>>(1)?))
            })? {
                let (id, bytes) = row?;
                let bytes = bytes.unwrap_or_default();
                if strings {
                    ensure(
                        bytes.len() + 8 <= columns::WRITER_BLOCK_BYTES,
                        "One string exceeds block limit",
                    )?;
                    if size + bytes.len() + 4 > columns::WRITER_BLOCK_BYTES
                        || text.len() == columns::BLOCK_ROWS
                    {
                        output.strings(manifest, &text)?;
                        text.clear();
                        size = 4;
                    }
                    size += bytes.len() + 4;
                    text.push(
                        String::from_utf8(bytes)
                            .map_err(|_| crate::Error::Input("Invalid staged UTF-8".into()))?,
                    );
                } else {
                    ensure(bytes.len().is_multiple_of(8), "Partial dictionary tuple")?;
                    let mut values = bytes
                        .as_chunks::<8>()
                        .0
                        .iter()
                        .map(|b| u64::from_le_bytes(*b))
                        .collect::<Vec<_>>();
                    if role == "details" && id == 0 {
                        values = vec![0; details];
                    }
                    numeric.push((u128::from(id), values));
                    if numeric.len() == columns::BLOCK_ROWS {
                        output.integers(manifest, &numeric)?;
                        numeric.clear();
                    }
                }
            }
            if strings {
                output.strings(manifest, &text)?;
            } else {
                output.integers(manifest, &numeric)?;
            }
            output.finish(manifest)?;
        }
        Ok(())
    }
}

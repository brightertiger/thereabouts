//! Admission checks happen before creating the exclusive stage or SQLite database.
use crate::{Error, Result, error::ensure, source::Dataset};
use std::{fs, path::Path};

/// Preserve at least five GiB in addition to the estimated build working space.
const FREE_SPACE_FLOOR: u64 = 5 * 1024 * 1024 * 1024;
/// Reserve one maximum-size output shard alongside the estimated disk index.
const SHARD_RESERVE: u64 = thereabouts_core::format::container::MAX_SHARD_BYTES as u64;
/// Compressed input is only an estimate: text keys, SQLite pages and output coexist.
/// Eight copies is deliberately conservative for the committed sample, not a world bound.
const INPUT_EXPANSION: u64 = 8;

pub(crate) fn preflight(data: &Dataset, stage: &Path, output: &Path, family: &str) -> Result<()> {
    fs::create_dir_all(stage)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        ensure(
            fs::metadata(stage)?.dev() == fs::metadata(output)?.dev(),
            "Staging and output directories must be on the same filesystem for atomic rename",
        )?;
    }
    sqlite_preflight(data, stage, family)
}
pub(crate) fn sqlite_preflight(data: &Dataset, directory: &Path, family: &str) -> Result<()> {
    fs::create_dir_all(directory)?;
    let mut bytes = 0_u64;
    let mut kinds = vec![
        crate::primary_table(family),
        "places",
        "canonical_cities",
        "place_to_city",
        "countries",
        "subdivisions",
    ];
    match family {
        "core" => kinds.extend(["timezone_cells", "zone_tables"]),
        "phone" => kinds.push("phone_metadata"),
        "plates" => kinds.extend(["plate_codes", "plate_policy", "plate_priors"]),
        _ => {}
    }
    for kind in kinds {
        for table in data.tables(kind) {
            let path = thereabouts_core::format::manifest::artifact_path(
                &data.root,
                crate::source::required(table, "path")?,
            )?;
            bytes = bytes
                .checked_add(fs::metadata(path)?.len())
                .ok_or_else(|| Error::Input("Dataset size overflows disk estimate".into()))?;
        }
    }
    let estimate = bytes
        .checked_mul(INPUT_EXPANSION)
        .and_then(|size| size.checked_add(SHARD_RESERVE))
        .ok_or_else(|| Error::Input("Dataset size overflows disk estimate".into()))?;
    admit(fs2::available_space(directory)?, estimate)
}
fn admit(available: u64, estimate: u64) -> Result<()> {
    let required = FREE_SPACE_FLOOR
        .checked_add(estimate)
        .ok_or_else(|| Error::Input("Disk estimate overflow".into()))?;
    ensure(
        available >= required,
        &format!(
            "Insufficient free space: {available} bytes available; need {required} (5 GiB floor plus {estimate} estimated build bytes)"
        ),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn admission_preserves_floor_in_addition_to_estimate() {
        assert!(admit(FREE_SPACE_FLOOR - 1, 0).is_err());
        assert!(admit(FREE_SPACE_FLOOR + 99, 100).is_err());
        assert!(admit(FREE_SPACE_FLOOR + 100, 100).is_ok());
        assert!(admit(u64::MAX, u64::MAX).is_err());
    }
}

//! Report physical data and evidence separately; fixed metadata is never multiplied by rows.
use crate::Result;
use std::{fs::File, io::Read, path::Path};
use thereabouts_core::format::{
    container::uint,
    manifest::{Manifest, Storage},
};
pub(crate) fn report(stage: &Path, manifest: &mut Manifest) -> Result<()> {
    let source_rows = if let Some(schema) = &manifest.forward_columns {
        schema.source_rows
    } else if let Some(schema) = &manifest.plate_columns {
        schema.source_rows
    } else {
        return Ok(());
    };
    let mut report = Storage {
        source_rows,
        ..Storage::default()
    };
    for file in &manifest.files {
        match file.kind.as_str() {
            "catalogue" => report.catalogue_bytes += file.size,
            "metadata" => report.metadata_bytes += file.size,
            "notice" => {}
            role => {
                report.data_artifact_bytes += file.size;
                let mut header = [0; 96];
                File::open(stage.join(&file.path))?.read_exact(&mut header)?;
                if matches!(uint(&header, 16, 4)?, 9 | 10) {
                    let bytes = uint(&header, 80, 8)?;
                    if matches!(
                        role,
                        "airport_evidence"
                            | "airport_assertions"
                            | "evidence"
                            | "evidence4"
                            | "evidence6"
                            | "details"
                            | "evidence_strings"
                            | "plate_format_evidence"
                            | "plate_code_evidence"
                    ) {
                        report.evidence_compressed_bytes += bytes;
                    } else {
                        report.query_compressed_bytes += bytes;
                    }
                }
            }
        }
    }
    manifest.storage = Some(report);
    Ok(())
}

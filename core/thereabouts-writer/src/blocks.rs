//! Streaming compressed table emission, bounded independently of source row count.
use crate::{Result, add, error::ensure};
use std::path::Path;
use thereabouts_core::format::{
    columns,
    container::{encode, put},
    manifest::Manifest,
    table,
};
/// Eight MiB shards bound compression buffers while amortizing file/directory overhead.
const SHARD_TARGET: usize = 8 * 1024 * 1024;
pub(crate) struct Output<'a> {
    stage: &'a Path,
    role: String,
    kind: u32,
    directory: Vec<u8>,
    payload: Vec<u8>,
    shard: usize,
    pub(crate) rows: usize,
    pub(crate) compressed_bytes: usize,
}
impl<'a> Output<'a> {
    pub(crate) fn new(stage: &'a Path, role: &str, kind: u32) -> Self {
        Self {
            stage,
            role: role.into(),
            kind,
            directory: vec![],
            payload: vec![],
            shard: 0,
            rows: 0,
            compressed_bytes: 0,
        }
    }
    pub(crate) fn integers(
        &mut self,
        manifest: &mut Manifest,
        rows: &[(u128, Vec<u64>)],
    ) -> Result<()> {
        if rows.is_empty() {
            return Ok(());
        }
        let data = rows.iter().map(|r| r.1.clone()).collect::<Vec<_>>();
        let raw = columns::encode(&data)?;
        if raw.len() > columns::WRITER_BLOCK_BYTES {
            ensure(rows.len() > 1, "One row exceeds block admission")?;
            let middle = rows.len() / 2;
            let (left, right) = rows.split_at(middle);
            self.integers(manifest, left)?;
            return self.integers(manifest, right);
        }
        self.block(manifest, &raw, rows.len(), rows.first().map_or(0, |r| r.0))
    }
    pub(crate) fn strings(&mut self, manifest: &mut Manifest, rows: &[String]) -> Result<()> {
        if rows.is_empty() {
            return Ok(());
        }
        self.block(
            manifest,
            &table::encode_strings(rows)?,
            rows.len(),
            self.rows as u128,
        )
    }
    fn block(&mut self, manifest: &mut Manifest, raw: &[u8], rows: usize, key: u128) -> Result<()> {
        let packed = columns::compress(raw)?;
        ensure(
            packed.len() <= columns::BLOCK_BYTES,
            "Oversized compressed block",
        )?;
        if self.payload.len() + packed.len() > SHARD_TARGET {
            self.flush(manifest)?;
        }
        put(&mut self.directory, self.rows as u64, 8);
        put(&mut self.directory, rows as u64, 4);
        put(&mut self.directory, raw.len() as u64, 4);
        put(&mut self.directory, self.payload.len() as u64, 8);
        put(&mut self.directory, packed.len() as u64, 4);
        put(&mut self.directory, 0, 4);
        put(
            &mut self.directory,
            u64::try_from(key & u128::from(u64::MAX))
                .map_err(|_| crate::Error::Input("Invalid low key word".into()))?,
            8,
        );
        put(
            &mut self.directory,
            u64::try_from(key >> 64)
                .map_err(|_| crate::Error::Input("Invalid high key word".into()))?,
            8,
        );
        self.payload.extend_from_slice(&packed);
        self.rows += rows;
        self.compressed_bytes += packed.len();
        Ok(())
    }
    fn flush(&mut self, manifest: &mut Manifest) -> Result<()> {
        let bytes = encode(
            self.kind,
            &[
                (&self.directory, table::DIRECTORY_WIDTH),
                (&self.payload, 1),
            ],
        )?;
        add(
            self.stage,
            manifest,
            &format!("{}-{:05}.bin", self.role, self.shard),
            &self.role,
            &bytes,
        )?;
        self.directory.clear();
        self.payload.clear();
        self.shard += 1;
        Ok(())
    }
    pub(crate) fn finish(mut self, manifest: &mut Manifest) -> Result<()> {
        if !self.directory.is_empty() || self.shard == 0 {
            self.flush(manifest)?;
        }
        Ok(())
    }
}

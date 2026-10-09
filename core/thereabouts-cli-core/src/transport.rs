//! Release transport policy, defined once and exported to Python, Node and the pipeline.

/// Placeholder until the owner publishes a release service.
pub const DEFAULT_RELEASE_URL: &str = "https://thereabouts-releases.invalid";
/// Largest compressed family archive a client downloads or the pipeline publishes.
pub const MAX_ARCHIVE_BYTES: u64 = 2 * 1024 * 1024 * 1024;
/// Largest decompressed archive stream a client expands; a world core is about 2.8 GB.
pub const MAX_UNPACKED_BYTES: u64 = 16 * 1024 * 1024 * 1024;
/// Release index format: compressed archives with their unpacked length.
pub const INDEX_FORMAT: u32 = 3;
/// Every family archive is a zstd-compressed POSIX ustar stream.
pub const ARCHIVE_SUFFIX: &str = ".tar.zst";

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn caps_fit_javascript_safe_integers() {
        // Node compares these as Numbers; both must stay below 2^53.
        assert!(MAX_ARCHIVE_BYTES < MAX_UNPACKED_BYTES);
        assert!(MAX_UNPACKED_BYTES < (1 << 53));
    }
}

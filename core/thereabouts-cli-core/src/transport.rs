//! Release transport policy, defined once and exported to Python, Node and the pipeline.

/// The owner's GitHub releases; `latest/download/` serves the newest release's assets.
pub const DEFAULT_RELEASE_URL: &str =
    "https://github.com/brightertiger/thereabouts/releases/latest/download/";
/// The only origin a release token is sent to, unless `GITHUB_API_VARIABLE` names another.
pub const GITHUB_API_URL: &str = "https://api.github.com";
/// Overrides the GitHub API origin (GitHub Enterprise or loopback tests); HTTPS or loopback.
pub const GITHUB_API_VARIABLE: &str = "THEREABOUTS_GITHUB_API_URL";
/// Environment variables a release token is read from, first set wins.
pub const TOKEN_VARIABLES: [&str; 2] = ["THEREABOUTS_RELEASE_TOKEN", "GITHUB_TOKEN"];
/// GitHub REST API version the clients speak.
pub const GITHUB_API_VERSION: &str = "2022-11-28";
/// Largest compressed family archive a client downloads or the pipeline publishes.
pub const MAX_ARCHIVE_BYTES: u64 = 2 * 1024 * 1024 * 1024;
/// Largest decompressed archive stream a client expands; a world core is about 2.8 GB.
pub const MAX_UNPACKED_BYTES: u64 = 16 * 1024 * 1024 * 1024;
/// Release index format: compressed archives with their unpacked length.
pub const INDEX_FORMAT: u32 = 3;
/// Every family archive is a zstd-compressed POSIX ustar stream.
pub const ARCHIVE_SUFFIX: &str = ".tar.zst";

// Node compares these as Numbers; both must stay exact below 2^53.
const _: () = assert!(MAX_ARCHIVE_BYTES < MAX_UNPACKED_BYTES && MAX_UNPACKED_BYTES < (1 << 53));

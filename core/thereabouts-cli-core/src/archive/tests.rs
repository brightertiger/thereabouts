use super::*;
use std::{collections::BTreeMap, io::Write};

/// Captures extraction in memory so refusals can prove nothing was written.
#[derive(Default)]
struct Memory {
    files: BTreeMap<String, Vec<u8>>,
    written: u64,
}
impl Output for Memory {
    fn directory(&mut self, _: &str) -> Result<()> {
        Ok(())
    }
    fn file(&mut self, path: &str, content: &mut dyn Read, _: u64) -> Result<()> {
        let mut bytes = Vec::new();
        let mut chunk = [0; 4096];
        loop {
            let count = content.read(&mut chunk)?;
            if count == 0 {
                break;
            }
            self.written += count as u64;
            bytes.extend_from_slice(&chunk[..count]);
        }
        self.files.insert(path.into(), bytes);
        Ok(())
    }
}
fn entry(name: &str, kind: u8, content: &[u8]) -> Vec<u8> {
    let mut block = [0; BLOCK];
    block[..name.len()].copy_from_slice(name.as_bytes());
    block[100..108].copy_from_slice(b"0000644\0");
    block[124..136].copy_from_slice(format!("{:011o}\0", content.len()).as_bytes());
    block[148..156].fill(b' ');
    block[156] = kind;
    block[257..263].copy_from_slice(b"ustar\0");
    let sum: u64 = block.iter().map(|b| u64::from(*b)).sum();
    block[148..156].copy_from_slice(format!("{sum:06o}\0 ").as_bytes());
    let mut bytes = block.to_vec();
    bytes.extend_from_slice(content);
    bytes.resize(bytes.len().next_multiple_of(BLOCK), 0);
    bytes
}
fn tar(entries: &[Vec<u8>]) -> Vec<u8> {
    let mut bytes = entries.concat();
    bytes.extend_from_slice(&[0; 2 * BLOCK]);
    bytes
}
fn zst(bytes: &[u8]) -> Vec<u8> {
    zstd::encode_all(bytes, 3).unwrap()
}
fn refused(archive: &[u8], declared: u64) -> (String, Memory) {
    let mut output = Memory::default();
    let error = extract(archive, &mut output, declared).unwrap_err();
    assert_eq!(error.exit_code(), 4, "{error}");
    (error.to_string(), output)
}

#[test]
fn round_trip_reports_exact_entries_and_length() {
    let plain = tar(&[
        entry("a.bin", b'0', b"alpha"),
        entry("b/c.bin", b'0', &[7; 600]),
    ]);
    let archive = zst(&plain);
    let mut output = Memory::default();
    let summary = extract(&archive[..], &mut output, plain.len() as u64).unwrap();
    assert_eq!(summary.unpacked_size, plain.len() as u64);
    assert_eq!(output.files["a.bin"], b"alpha");
    assert_eq!(output.files["b/c.bin"], vec![7; 600]);
    assert_eq!(
        summary.entries[0].sha256,
        format!("{:x}", Sha256::digest(b"alpha"))
    );
    assert_eq!(inspect(&archive[..]).unwrap(), summary);
    // The declared length is exact, not a ceiling.
    let (message, _) = refused(&archive, plain.len() as u64 + 1);
    assert!(message.contains("declared unpacked size"), "{message}");
}
#[test]
fn unsafe_reserved_and_duplicate_paths_are_refused_before_writing() {
    for name in [
        "../escape",
        "/absolute",
        "a//b",
        "a/./b",
        "a/..",
        RECEIPT,
        "a\\b",
        "c:d",
    ] {
        let plain = tar(&[entry(name, b'0', b"payload")]);
        let (message, output) = refused(&zst(&plain), plain.len() as u64);
        assert!(message.contains("Unsafe or reserved"), "{name}: {message}");
        assert_eq!(output.written, 0, "{name}");
    }
    let plain = tar(&[entry("a", b'0', b"1"), entry("a", b'0', b"2")]);
    assert!(
        refused(&zst(&plain), plain.len() as u64)
            .0
            .contains("Duplicate")
    );
}
#[test]
fn links_devices_and_fifos_are_refused() {
    for kind in *b"123467xg" {
        let plain = tar(&[entry("link", kind, b"")]);
        let (message, output) = refused(&zst(&plain), plain.len() as u64);
        assert!(message.contains("forbidden"), "{}: {message}", kind as char);
        assert_eq!(output.written, 0);
    }
}
#[test]
fn malformed_headers_streams_and_trailers_are_integrity_failures() {
    let plain = tar(&[entry("a", b'0', b"payload")]);
    let size = plain.len() as u64;
    let mut bad = plain.clone();
    bad[0] = b'b'; // checksum no longer matches
    assert!(refused(&zst(&bad), size).0.contains("ustar"));
    let mut magic = plain.clone();
    magic[257..263].copy_from_slice(b"gnutar");
    assert!(refused(&zst(&magic), size).0.contains("ustar"));
    let mut trailer = plain.clone();
    trailer.extend_from_slice(&[1; BLOCK]);
    assert!(
        refused(&zst(&trailer), trailer.len() as u64)
            .0
            .contains("trailer")
    );
    assert!(refused(&plain, size).0.contains("zstd"));
    let archive = zst(&plain);
    let truncated = &archive[..archive.len() - 6];
    assert!(
        refused(truncated, size)
            .0
            .to_lowercase()
            .contains("archive")
    );
    let mut appended = archive.clone();
    appended.extend_from_slice(&archive);
    assert!(refused(&appended, size).0.contains("Trailing data"));
    let short = tar(&[entry("a", b'0', b"payload")])[..BLOCK + 512].to_vec();
    assert!(
        refused(&zst(&short), short.len() as u64)
            .0
            .contains("Truncated")
    );
}
#[test]
fn expansion_stops_at_the_declared_size() {
    // A 1 GiB entry of zeros compresses to kilobytes: the classic bomb.
    let mut encoder = zstd::stream::write::Encoder::new(Vec::new(), 1).unwrap();
    let mut header = entry("bomb", b'0', b"")[..BLOCK].to_vec();
    let size = 1u64 << 30;
    header[124..136].copy_from_slice(format!("{size:011o}\0").as_bytes());
    header[148..156].fill(b' ');
    let sum: u64 = header.iter().map(|b| u64::from(*b)).sum();
    header[148..156].copy_from_slice(format!("{sum:06o}\0 ").as_bytes());
    encoder.write_all(&header).unwrap();
    let zeros = vec![0; 1 << 20];
    for _ in 0..1024 {
        encoder.write_all(&zeros).unwrap();
    }
    let bomb = encoder.finish().unwrap();
    assert!(bomb.len() < 1 << 20);
    let (message, output) = refused(&bomb, 1 << 20);
    assert!(message.contains("declared unpacked size"), "{message}");
    assert!(output.written <= 1 << 21, "wrote {}", output.written);
    let (message, output) = refused(&bomb, MAX_UNPACKED_BYTES + 1);
    assert!(message.contains("cap"), "{message}");
    assert_eq!(output.written, 0);
}
#[cfg(feature = "create")]
#[test]
fn created_archives_are_deterministic_and_match_the_pack() {
    let pack = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/packs/phone-synthetic");
    let temp = tempfile::tempdir().unwrap();
    let first = create(&pack, &temp.path().join("one.tar.zst")).unwrap();
    let second = create(&pack, &temp.path().join("two.tar.zst")).unwrap();
    assert_eq!(first, second);
    let bytes = std::fs::read(temp.path().join("one.tar.zst")).unwrap();
    assert_eq!(
        bytes,
        std::fs::read(temp.path().join("two.tar.zst")).unwrap()
    );
    assert_eq!(first.size, bytes.len() as u64);
    assert_eq!(first.sha256, format!("{:x}", Sha256::digest(&bytes)));
    let summary = inspect(&bytes[..]).unwrap();
    assert_eq!(summary.unpacked_size, first.unpacked_size);
    let manifest = thereabouts_core::format::manifest::read(&pack).unwrap();
    let mut expected: Vec<_> = manifest
        .files
        .iter()
        .map(|f| (f.path.clone(), f.size, f.sha256.clone()))
        .collect();
    let raw = std::fs::read(pack.join("manifest.json")).unwrap();
    expected.push((
        "manifest.json".into(),
        raw.len() as u64,
        format!("{:x}", Sha256::digest(&raw)),
    ));
    expected.sort();
    let actual: Vec<_> = summary
        .entries
        .iter()
        .map(|e| (e.path.clone(), e.size, e.sha256.clone()))
        .collect();
    assert_eq!(actual, expected);
    // Every header carries one mode, zero owner and zero time: only content changes bytes.
    let plain = zstd::decode_all(&bytes[..]).unwrap();
    let template = header("x", 0).unwrap();
    for (start, end) in [(100, 124), (136, 148), (156, 157), (257, 265)] {
        assert_eq!(&plain[start..end], &template[start..end]);
    }
}
#[cfg(feature = "create")]
#[test]
fn creation_refuses_a_pack_that_differs_from_its_manifest() {
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/packs/phone-synthetic");
    let temp = tempfile::tempdir().unwrap();
    let pack = temp.path().join("pack");
    std::fs::create_dir(&pack).unwrap();
    for item in std::fs::read_dir(&source).unwrap() {
        let item = item.unwrap();
        std::fs::copy(item.path(), pack.join(item.file_name())).unwrap();
    }
    let manifest = thereabouts_core::format::manifest::read(&pack).unwrap();
    let victim = pack.join(&manifest.files[0].path);
    let mut bytes = std::fs::read(&victim).unwrap();
    bytes[0] ^= 1;
    std::fs::write(&victim, bytes).unwrap();
    let error = create(&pack, &temp.path().join("out.tar.zst")).unwrap_err();
    assert!(
        error.to_string().contains("differs from its manifest"),
        "{error}"
    );
}

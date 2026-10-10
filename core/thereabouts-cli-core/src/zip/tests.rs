use super::*;
use std::collections::BTreeMap;

/// Captures extraction in memory so refusals can prove what was written.
#[derive(Default)]
struct Memory {
    files: BTreeMap<String, Vec<u8>>,
}
impl Output for Memory {
    fn directory(&mut self, _: &str) -> Result<()> {
        Ok(())
    }
    fn file(&mut self, path: &str, content: &mut dyn Read, _: u64) -> Result<()> {
        let mut bytes = Vec::new();
        content.read_to_end(&mut bytes)?;
        self.files.insert(path.into(), bytes);
        Ok(())
    }
}
/// Deviations from the layout the pipeline writes.
#[derive(Default)]
#[allow(clippy::struct_excessive_bools)]
struct Tweak {
    method: u16,
    flags: u16,
    extra: bool,
    external: Option<u32>,
    central_name: Option<&'static str>,
    central_offset: u32,
    central_size: u32,
    comment: bool,
    trailing: bool,
    bad_crc: bool,
}
fn put16(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_le_bytes());
}
fn put32(out: &mut Vec<u8>, value: u32) {
    out.extend_from_slice(&value.to_le_bytes());
}
#[allow(clippy::cast_possible_truncation)]
fn build(entries: &[(&str, &[u8])], tweak: &Tweak) -> Vec<u8> {
    let mut out = Vec::new();
    let mut central = Vec::new();
    for (name, data) in entries {
        let offset = out.len() as u32;
        let mut crc = Crc32::default();
        crc.update(data);
        let crc = crc.value() ^ u32::from(tweak.bad_crc);
        let size = data.len() as u32;
        put32(&mut out, LOCAL);
        for value in [20, tweak.flags, tweak.method, 0, 0x21] {
            put16(&mut out, value);
        }
        for value in [crc, size, size] {
            put32(&mut out, value);
        }
        put16(&mut out, name.len() as u16);
        put16(&mut out, if tweak.extra { 4 } else { 0 });
        out.extend_from_slice(name.as_bytes());
        if tweak.extra {
            out.extend_from_slice(&[0xfe, 0xca, 0, 0]);
        }
        out.extend_from_slice(data);
        let central_name = tweak.central_name.unwrap_or(name);
        put32(&mut central, CENTRAL);
        for value in [0x0314, 20, tweak.flags, tweak.method, 0, 0x21] {
            put16(&mut central, value);
        }
        for value in [crc, size + tweak.central_size, size] {
            put32(&mut central, value);
        }
        for value in [central_name.len() as u16, 0, 0, 0, 0] {
            put16(&mut central, value);
        }
        put32(&mut central, tweak.external.unwrap_or(0o100_644 << 16));
        put32(&mut central, offset + tweak.central_offset);
        central.extend_from_slice(central_name.as_bytes());
    }
    let start = out.len() as u32;
    out.extend_from_slice(&central);
    put32(&mut out, END);
    for value in [0, 0, entries.len() as u16, entries.len() as u16] {
        put16(&mut out, value);
    }
    put32(&mut out, central.len() as u32);
    put32(&mut out, start);
    put16(&mut out, u16::from(tweak.comment) * 2);
    if tweak.comment {
        out.extend_from_slice(b"hi");
    }
    if tweak.trailing {
        out.push(0);
    }
    out
}
fn sha(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}
const FILES: [(&str, &[u8]); 2] = [
    (
        "cells/group=81003ffffffffff/part-0.parquet",
        b"first table bytes",
    ),
    ("cells/part-1.parquet", b""),
];

#[test]
fn the_crc_matches_the_standard_check_value() {
    let mut crc = Crc32::default();
    crc.update(b"123456789");
    assert_eq!(crc.value(), 0xCBF4_3926);
}
#[test]
fn stored_entries_extract_with_digests_and_an_exact_length() {
    let zip = build(&FILES, &Tweak::default());
    let mut memory = Memory::default();
    let summary = extract(zip.as_slice(), &mut memory, 17).unwrap();
    assert_eq!(summary.unpacked_size, 17);
    let expected: Vec<Entry> = FILES
        .iter()
        .map(|(path, data)| Entry {
            path: (*path).into(),
            size: data.len() as u64,
            sha256: sha(data),
        })
        .collect();
    assert_eq!(summary.entries, expected);
    assert_eq!(inspect(zip.as_slice()).unwrap(), summary);
    assert_eq!(
        memory.files,
        FILES
            .iter()
            .map(|(p, d)| ((*p).to_owned(), d.to_vec()))
            .collect()
    );
    for declared in [16, 18] {
        assert!(extract(zip.as_slice(), &mut Memory::default(), declared).is_err());
    }
}
#[test]
fn bytes_beyond_the_declared_size_are_never_written() {
    let zip = build(&[("a/big.bin", &[7; 64])], &Tweak::default());
    let mut memory = Memory::default();
    let error = extract(zip.as_slice(), &mut memory, 63).unwrap_err();
    assert!(error.to_string().contains("beyond"), "{error}");
    assert!(memory.files.is_empty());
}
#[test]
fn unsafe_paths_are_refused_before_writing() {
    for name in [
        "../escape",
        "/absolute",
        "a\\b",
        "c:/x",
        "a//b",
        "./a",
        "a/./b",
        "dir/",
        ".archive.json",
    ] {
        let zip = build(&[(name, b"x")], &Tweak::default());
        let mut memory = Memory::default();
        assert!(extract(zip.as_slice(), &mut memory, 1).is_err(), "{name}");
        assert!(memory.files.is_empty(), "{name}");
    }
    let zip = build(&[("a/x", b"1"), ("a/x", b"2")], &Tweak::default());
    let error = inspect(zip.as_slice()).unwrap_err();
    assert!(error.to_string().contains("Duplicate"), "{error}");
}
#[test]
fn other_layouts_are_refused() {
    let tweaks = [
        Tweak {
            method: 8,
            ..Tweak::default()
        },
        Tweak {
            flags: 0x0008,
            ..Tweak::default()
        },
        Tweak {
            flags: 0x0001,
            ..Tweak::default()
        },
        Tweak {
            extra: true,
            ..Tweak::default()
        },
        Tweak {
            external: Some(0o120_777 << 16),
            ..Tweak::default()
        },
        Tweak {
            central_name: Some("cells/other"),
            ..Tweak::default()
        },
        Tweak {
            central_offset: 1,
            ..Tweak::default()
        },
        Tweak {
            central_size: 1,
            ..Tweak::default()
        },
        Tweak {
            comment: true,
            ..Tweak::default()
        },
        Tweak {
            trailing: true,
            ..Tweak::default()
        },
        Tweak {
            bad_crc: true,
            ..Tweak::default()
        },
    ];
    for (position, tweak) in tweaks.iter().enumerate() {
        let zip = build(&FILES, tweak);
        assert!(inspect(zip.as_slice()).is_err(), "tweak {position}");
    }
    let zip = build(&FILES, &Tweak::default());
    for length in [0, 4, 30, zip.len() - 22, zip.len() - 1] {
        let error = inspect(zip.get(..length).unwrap()).unwrap_err();
        assert_eq!(error.exit_code(), 4, "{length}: {error}");
    }
    assert!(inspect(build(&[], &Tweak::default()).as_slice()).is_err());
}

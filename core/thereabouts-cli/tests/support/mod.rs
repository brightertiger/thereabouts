//! Test hosts never inherit the user's store or release service.
#![allow(dead_code, clippy::unwrap_used)]
use std::{
    collections::BTreeMap,
    fs,
    io::{self, BufRead, Cursor},
    path::Path,
};
use thereabouts_cli::{io::Io, store};
use thereabouts_core::format::manifest;

#[derive(Default)]
pub struct Host {
    pub out: String,
    pub err: String,
    pub input: Cursor<Vec<u8>>,
    pub env: BTreeMap<String, String>,
    pub tty: bool,
}
impl Host {
    pub fn new(root: &Path) -> Self {
        Self {
            env: BTreeMap::from([
                (
                    "THEREABOUTS_DATA".into(),
                    root.to_string_lossy().into_owned(),
                ),
                ("NO_COLOR".into(), "1".into()),
            ]),
            ..Self::default()
        }
    }
    pub fn run(&mut self, args: &[&str]) -> i32 {
        self.out.clear();
        self.err.clear();
        let args = std::iter::once("thereabouts")
            .chain(args.iter().copied())
            .map(str::to_owned)
            .collect::<Vec<_>>();
        thereabouts_cli::run(&args, self)
    }
}
impl Io for Host {
    fn read_line(&mut self, line: &mut String) -> io::Result<usize> {
        self.input.read_line(line)
    }
    fn stdout(&mut self, value: &str) -> io::Result<()> {
        self.out.push_str(value);
        Ok(())
    }
    fn stderr(&mut self, value: &str) -> io::Result<()> {
        self.err.push_str(value);
        Ok(())
    }
    fn env(&self, key: &str) -> Option<String> {
        self.env.get(key).cloned()
    }
    fn stdin_tty(&self) -> bool {
        self.tty
    }
    fn stdout_tty(&self) -> bool {
        self.tty
    }
}
pub fn install(root: &Path, families: &[&str]) {
    let mut pin = store::Active::default();
    for family in families {
        let source = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(format!("../../tests/fixtures/packs/{family}-sample"));
        let info = manifest::read(&source).unwrap();
        pin.data_version = info.data_version;
        let relative = format!("packs/{family}/{}", pin.data_version);
        let target = root.join(&relative);
        fs::create_dir_all(&target).unwrap();
        for name in
            std::iter::once("manifest.json").chain(info.files.iter().map(|f| f.path.as_str()))
        {
            let dest = target.join(name);
            fs::create_dir_all(dest.parent().unwrap()).unwrap();
            fs::copy(source.join(name), dest).unwrap();
        }
        pin.packs.insert(
            (*family).into(),
            store::Pointer {
                path: relative,
                manifest_sha256: manifest::digest(&target.join("manifest.json")).unwrap(),
            },
        );
    }
    store::activate(root, &pin).unwrap();
}

pub fn release(root: &Path) {
    let source =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/phone-sample");
    let info = manifest::read(&source).unwrap();
    let mut archive = Vec::new();
    for name in std::iter::once("manifest.json").chain(info.files.iter().map(|f| f.path.as_str())) {
        let bytes = fs::read(source.join(name)).unwrap();
        let mut header = [0u8; 512];
        header
            .get_mut(..name.len())
            .unwrap()
            .copy_from_slice(name.as_bytes());
        header
            .get_mut(124..136)
            .unwrap()
            .copy_from_slice(format!("{:011o}\0", bytes.len()).as_bytes());
        header.get_mut(148..156).unwrap().fill(b' ');
        *header.get_mut(156).unwrap() = b'0';
        header
            .get_mut(257..263)
            .unwrap()
            .copy_from_slice(b"ustar\0");
        let sum: u64 = header.iter().map(|b| u64::from(*b)).sum();
        header
            .get_mut(148..156)
            .unwrap()
            .copy_from_slice(format!("{sum:06o}\0 ").as_bytes());
        archive.extend(header);
        archive.extend(bytes);
        archive.resize(archive.len().next_multiple_of(512), 0);
    }
    archive.resize(archive.len() + 1024, 0);
    fs::create_dir_all(root).unwrap();
    let file = root.join("phone.tar");
    fs::write(&file, &archive).unwrap();
    let index = serde_json::json!({"format":2,"datasets":{info.data_version:{"packs":{"phone":{
        "url":"phone.tar","bytes":archive.len(),"sha256":manifest::digest(&file).unwrap(),"format_minor":2
    }}}}});
    fs::write(root.join("index.json"), serde_json::to_vec(&index).unwrap()).unwrap();
}

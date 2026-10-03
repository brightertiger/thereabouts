//! Store transactions use only local synthetic fixtures.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fs,
    io::{self, Cursor, Read},
    path::{Path, PathBuf},
};
use thereabouts_cli::{
    index::{Dataset, Index, ReleasePack},
    install,
    io::Io,
    store,
    transfer::{Directory, Source},
};
use thereabouts_core::format::manifest;

#[derive(Default)]
struct Host {
    env: BTreeMap<String, String>,
}
impl Io for Host {
    fn read_line(&mut self, _: &mut String) -> io::Result<usize> {
        Ok(0)
    }
    fn stdout(&mut self, _: &str) -> io::Result<()> {
        Ok(())
    }
    fn stderr(&mut self, _: &str) -> io::Result<()> {
        Ok(())
    }
    fn env(&self, key: &str) -> Option<String> {
        self.env.get(key).cloned()
    }
    fn stdin_tty(&self) -> bool {
        false
    }
    fn stdout_tty(&self) -> bool {
        false
    }
}
fn fixture() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/phone-synthetic")
}
fn tar(root: &Path) -> Vec<u8> {
    let info = manifest::read(root).unwrap();
    let mut result = Vec::new();
    for path in std::iter::once("manifest.json").chain(info.files.iter().map(|f| f.path.as_str())) {
        let content = fs::read(root.join(path)).unwrap();
        let mut header = [0u8; 512];
        header[..path.len()].copy_from_slice(path.as_bytes());
        header[100..108].copy_from_slice(b"0000644\0");
        header[124..136].copy_from_slice(format!("{:011o}\0", content.len()).as_bytes());
        header[148..156].fill(b' ');
        header[156] = b'0';
        header[257..263].copy_from_slice(b"ustar\0");
        let sum: u64 = header.iter().map(|b| u64::from(*b)).sum();
        header[148..156].copy_from_slice(format!("{sum:06o}\0 ").as_bytes());
        result.extend_from_slice(&header);
        result.extend_from_slice(&content);
        result.resize(result.len().next_multiple_of(512), 0);
    }
    result.resize(result.len() + 1024, 0);
    result
}
fn source(root: &Path) -> (Directory, String) {
    fs::create_dir_all(root).unwrap();
    let archive = tar(&fixture());
    let file = root.join("phone.tar");
    fs::write(&file, &archive).unwrap();
    let version = manifest::read(&fixture()).unwrap().data_version;
    let pack = ReleasePack {
        url: "phone.tar".into(),
        bytes: archive.len() as u64,
        sha256: manifest::digest(&file).unwrap(),
        format_minor: 1,
    };
    let index = Index {
        format: 2,
        datasets: BTreeMap::from([(
            version.clone(),
            Dataset {
                packs: BTreeMap::from([("phone".into(), pack)]),
            },
        )]),
    };
    fs::write(root.join("index.json"), serde_json::to_vec(&index).unwrap()).unwrap();
    (Directory::new(root), version)
}
#[test]
fn platform_paths_and_precedence() {
    let mut host = Host {
        env: BTreeMap::from([
            ("HOME".into(), "/users/test".into()),
            ("LOCALAPPDATA".into(), "C:/Users/test/Local".into()),
        ]),
    };
    assert_eq!(
        store::platform_directory("macos", &host).unwrap(),
        Path::new("/users/test/Library/Application Support/Thereabouts")
    );
    assert_eq!(
        store::platform_directory("linux", &host).unwrap(),
        Path::new("/users/test/.local/share/thereabouts")
    );
    assert_eq!(
        store::platform_directory("windows", &host).unwrap(),
        Path::new("C:/Users/test/Local/Thereabouts")
    );
    host.env.insert("THEREABOUTS_DATA".into(), "~/packs".into());
    assert_eq!(
        store::directory(None, &host).unwrap(),
        Path::new("/users/test/packs")
    );
    assert_eq!(
        store::directory(Some(Path::new("/explicit")), &host).unwrap(),
        Path::new("/explicit")
    );
}
#[test]
fn install_verify_discover_remove_and_lock() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("store");
    let (source, version) = source(&temp.path().join("release"));
    let pin = install::install(&root, &source, &["phone".into()], None).unwrap();
    assert_eq!(pin.data_version, version);
    let installed = store::installed(&root, "phone").unwrap();
    assert_eq!(installed, root.join(format!("packs/phone/{version}")));
    assert_eq!(store::inventory(&root).unwrap().len(), 1);
    let lock = store::lock(&root).unwrap();
    assert!(store::lock(&root).is_err());
    assert!(store::remove(&root, "phone").is_err());
    drop(lock);
    assert!(install::precheck(&root, u64::MAX).is_err());
    store::remove(&root, "phone").unwrap();
    assert_eq!(
        store::installed(&root, "phone").unwrap_err().to_string(),
        "thereabouts data install phone"
    );
}
struct Interrupted {
    source: Directory,
    offsets: RefCell<Vec<u64>>,
}
impl Source for Interrupted {
    fn index(&self) -> thereabouts_cli::error::Result<Vec<u8>> {
        self.source.index()
    }
    fn open(
        &self,
        name: &str,
        offset: u64,
        total: u64,
    ) -> thereabouts_cli::error::Result<Box<dyn Read>> {
        self.offsets.borrow_mut().push(offset);
        let mut bytes = Vec::new();
        self.source
            .open(name, offset, total)?
            .read_to_end(&mut bytes)?;
        if self.offsets.borrow().len() == 1 {
            bytes.truncate(1000);
        }
        Ok(Box::new(Cursor::new(bytes)))
    }
}
#[test]
fn interrupted_download_resumes_and_does_not_activate() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("store");
    let (source, _) = source(&temp.path().join("release"));
    let source = Interrupted {
        source,
        offsets: RefCell::default(),
    };
    assert!(install::install(&root, &source, &["phone".into()], None).is_err());
    assert!(!root.join("active.json").exists());
    install::install(&root, &source, &["phone".into()], None).unwrap();
    assert_eq!(*source.offsets.borrow(), vec![0, 1000]);
}
#[test]
fn bad_checksum_leaves_previous_pin_and_clears_partial() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("store");
    let release = temp.path().join("release");
    let (source, _) = source(&release);
    let mut bytes = fs::read(release.join("phone.tar")).unwrap();
    bytes[1000] ^= 1;
    fs::write(release.join("phone.tar"), bytes).unwrap();
    assert!(
        install::install(&root, &source, &["phone".into()], None)
            .unwrap_err()
            .to_string()
            .contains("checksum")
    );
    assert!(!root.join("active.json").exists());
    assert_eq!(fs::read_dir(root.join(".downloads")).unwrap().count(), 0);
}
#[test]
fn all_families_verify_before_activation() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("store");
    let release = temp.path().join("release");
    let (source, version) = source(&release);
    let mut index = install::index(&source).unwrap();
    let dataset = index.datasets.get_mut(&version).unwrap();
    // An archive claiming another family must fail identity verification.
    dataset
        .packs
        .insert("postal".into(), dataset.packs["phone"].clone());
    fs::write(
        release.join("index.json"),
        serde_json::to_vec(&index).unwrap(),
    )
    .unwrap();
    assert!(install::install(&root, &source, &["phone".into(), "postal".into()], None).is_err());
    assert!(!root.join("active.json").exists());
    assert_eq!(store::installed(&root, "phone").unwrap_err().exit_code(), 3);
}

#[test]
fn archive_identity_is_immutable_and_failures_keep_the_active_pin() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("store");
    let release = temp.path().join("release");
    let (source, version) = source(&release);
    install::install(&root, &source, &["phone".into()], None).unwrap();
    let before = fs::read(root.join("active.json")).unwrap();
    let mut index = install::index(&source).unwrap();
    let pack = index
        .datasets
        .get_mut(&version)
        .unwrap()
        .packs
        .get_mut("phone")
        .unwrap();
    pack.sha256 = "0".repeat(64);
    fs::write(
        release.join("index.json"),
        serde_json::to_vec(&index).unwrap(),
    )
    .unwrap();
    assert!(
        install::install(&root, &source, &["phone".into()], None)
            .unwrap_err()
            .to_string()
            .contains("identity changed")
    );
    assert_eq!(fs::read(root.join("active.json")).unwrap(), before);
    assert!(store::installed(&root, "phone").is_ok());
}

#[test]
fn old_pointer_remains_readable_and_cannot_escape_its_identity() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let info = manifest::read(&fixture()).unwrap();
    let digest = manifest::digest(&fixture().join("manifest.json")).unwrap();
    let relative = format!("packs/phone/v-{}/{digest}", info.data_version);
    let target = root.join(&relative);
    fs::create_dir_all(&target).unwrap();
    for name in std::iter::once("manifest.json").chain(info.files.iter().map(|f| f.path.as_str())) {
        fs::copy(fixture().join(name), target.join(name)).unwrap();
    }
    let current = root.join("packs/phone/current.json");
    let mut pointer = store::Pointer {
        path: relative,
        manifest_sha256: digest,
    };
    fs::write(&current, serde_json::to_vec(&pointer).unwrap()).unwrap();
    assert_eq!(store::installed(root, "phone").unwrap(), target);
    pointer.path = "../escape".into();
    fs::write(&current, serde_json::to_vec(&pointer).unwrap()).unwrap();
    assert_eq!(store::installed(root, "phone").unwrap_err().exit_code(), 4);
}

#[test]
fn version_components_are_portable_and_cannot_traverse() {
    for value in [
        "", ".", "..", "../x", "x/y", "x\\y", "CON", "nul.txt", "LPT1", "x.",
    ] {
        assert!(store::component(value).is_err(), "{value}");
    }
    for value in ["2026.10", "synthetic-phone", "test_2"] {
        assert!(store::component(value).is_ok(), "{value}");
    }
}

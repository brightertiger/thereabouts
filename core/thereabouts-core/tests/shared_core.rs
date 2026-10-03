//! Shared ordinal namespaces are optional at query time and exact when attached.
#![allow(clippy::unwrap_used)]
use std::{path::PathBuf, sync::Arc};
use thereabouts_core::format::Pack;
#[test]
fn forward_without_core_and_with_pinned_core() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs");
    let pack = Pack::open(&root.join("postal-synthetic"), true).unwrap();
    assert!(!pack.manifest.files.iter().any(|f| f.kind == "catalogue"));
    let bare = pack.postal("00100", Some("AA"), false).unwrap();
    assert!(bare.city.is_none() && bare.timezone.is_none());
    let core = Arc::new(Pack::open(&root.join("core-synthetic"), true).unwrap());
    let pack = pack.with_core(core).unwrap();
    let rich = pack.postal("00100", Some("AA"), false).unwrap();
    assert_eq!(bare.country, rich.country);
    assert_eq!(
        bare.state.as_ref().map(|s| &s.name),
        rich.state.as_ref().map(|s| &s.name)
    );
    assert_eq!(bare.point, rich.point);
    assert!(rich.city.is_some());
    assert_eq!(rich.timezone.as_deref(), Some("Fixture/One"));
    let wrong = Arc::new(Pack::open(&root.join("core-names-synthetic"), true).unwrap());
    assert!(matches!(
        pack.with_core(wrong),
        Err(thereabouts_core::Error::Incompatible(_))
    ));
}

//! CPU sampling target: build with `cargo rustc --release --example geocode_profile -- -C strip=none`.
use std::{
    hint::black_box,
    path::Path,
    time::{Duration, Instant},
};
use thereabouts_core::{
    Result,
    format::Pack,
    geocode::Options,
    name_normalization::{Policy, normalize},
};
fn main() -> Result<()> {
    let root =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/core-names-sample");
    let pack = Pack::open(&root, false)?;
    let options = Options {
        country: Some("NL"),
        ..Options::default()
    };
    let policy = Policy::default();
    let start = Instant::now();
    for _ in 0..100_000 {
        black_box(normalize(black_box("Utrecht"), &policy));
    }
    println!(
        "normalization_ns_per_call={}",
        start.elapsed().as_nanos() / 100_000
    );
    let end = Instant::now() + Duration::from_secs(10);
    while Instant::now() < end {
        black_box(pack.geocode(black_box("Utrecht"), options)?);
        black_box(pack.geocode(black_box("Springfield"), Options::default())?);
        black_box(pack.geocode(black_box("Utrechx"), options)?);
    }
    Ok(())
}

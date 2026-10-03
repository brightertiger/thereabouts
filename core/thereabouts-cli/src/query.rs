//! CLI verbs delegate to the same lookup methods as the library bindings.
use crate::{
    args::Command,
    error::{Error, Result},
    store,
};
use std::path::{Path, PathBuf};
use thereabouts_core::{format::Pack, result::LookupResult};

pub(crate) fn family(command: &Command) -> Option<&'static str> {
    Some(match command {
        Command::Reverse { .. } | Command::H3 { .. } | Command::Geocode { .. } => "core",
        Command::Postal { .. } => "postal",
        Command::Airport { .. } => "airports",
        Command::Locode { .. } => "locode",
        Command::Ip { .. } => "ip",
        Command::Phone { .. } => "phone",
        Command::Plate { .. } => "plates",
        _ => return None,
    })
}
pub(crate) fn open(root: &Path, command: &Command) -> Result<(Pack, PathBuf)> {
    let family = family(command).ok_or_else(|| Error::Usage("Expected a lookup verb".into()))?;
    let path = store::installed(root, family)?;
    let mut pack = Pack::open(&path, false)
        .map_err(Error::from)
        .map_err(|e| e.at_pack(&path, family))?;
    if family != "core" {
        match store::installed(root, "core") {
            Ok(core_path) => {
                let core = Pack::open(&core_path, false)
                    .map_err(Error::from)
                    .map_err(|e| e.at_pack(&core_path, "core"))?;
                pack = pack
                    .with_core(std::sync::Arc::new(core))
                    .map_err(Error::from)
                    .map_err(|e| e.at_pack(&path, family))?;
            }
            Err(Error::Missing(_)) => {}
            Err(error) => return Err(error),
        }
    }
    Ok((pack, path))
}
pub(crate) fn run(pack: &Pack, command: &Command, evidence: bool) -> Result<LookupResult> {
    Ok(match command {
        Command::Reverse {
            lat: Some(lat),
            lon: Some(lon),
            ..
        } => pack.reverse(*lat, *lon, evidence)?,
        Command::H3 { cell } => pack.from_h3(cell, evidence)?,
        Command::Postal { code, country } => pack.postal(code, Some(country), evidence)?,
        Command::Airport {
            code,
            scheme,
            country,
        } => pack.airport(code, scheme.as_deref(), country.as_deref(), evidence)?,
        Command::Locode { code, country } => pack.locode(code, country.as_deref(), evidence)?,
        Command::Phone { number, country } => {
            pack.phone_in_country(number, country.as_deref(), evidence)?
        }
        Command::Ip { address } => pack.ip(address, evidence)?,
        Command::Plate {
            text,
            country,
            series,
        } => pack.plate(text, country.as_deref(), series.as_deref(), evidence)?,
        Command::Geocode {
            text,
            country,
            subdivision,
            limit,
            prefer,
        } => pack.geocode(
            text,
            thereabouts_core::geocode::Options {
                country: country.as_deref(),
                subdivision: subdivision.as_deref(),
                limit: usize::from(*limit),
                prefer: prefer.as_deref(),
                scope: "cities",
                evidence,
            },
        )?,
        _ => return Err(Error::Usage("Expected scalar lookup arguments".into())),
    })
}

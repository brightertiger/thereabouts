//! Coordinate JSON failures are public invalid-input results, never pack errors.
use thereabouts_core::{
    coords::{self, CoordError, PointResult},
    format::Pack,
};

pub(crate) fn reverse(
    pack: &Pack,
    request: &str,
    evidence: bool,
) -> thereabouts_core::Result<PointResult> {
    match serde_json::from_str(request) {
        Ok(value) => coords::reverse_value(pack, &value, evidence),
        Err(_) => Ok(coords::invalid_result(
            None,
            &CoordError::InvalidSyntax {
                frame: "json".into(),
            },
        )),
    }
}

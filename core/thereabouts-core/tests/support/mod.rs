//! Independent source coordinates in the original legacy bundle.
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]
use thereabouts_core::result::Point;
pub(crate) fn point(actual: Option<&Point>, candidate: &serde_json::Value) {
    let mut observations = candidate["observations"]
        .as_array()
        .unwrap()
        .iter()
        .collect::<Vec<_>>();
    observations.sort_by_key(|o| {
        (
            o["source"].as_str(),
            o["source_id"].as_str(),
            o["fields"]["name"]
                .as_str()
                .or(o["fields"]["place_name"].as_str()),
        )
    });
    let anchor = &observations[0]["fields"];
    if anchor["latitude"].is_null() {
        assert!(anchor["longitude"].is_null());
        assert!(actual.is_none());
    } else {
        let actual = actual.unwrap();
        assert!((actual.lat - anchor["latitude"].as_f64().unwrap()).abs() <= 0.000_000_51);
        assert!((actual.lon - anchor["longitude"].as_f64().unwrap()).abs() <= 0.000_000_51);
    }
}

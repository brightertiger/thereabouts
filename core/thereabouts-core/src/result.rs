//! The language-independent, flat public result. No precision is invented.
use serde::{Deserialize, Serialize};

/// Geographic degrees, rounded only when stored as a catalogue microdegree point.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Point {
    pub lat: f64,
    pub lon: f64,
}
/// Country metadata from the dataset, with nullable alpha-3.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Country {
    pub code: String,
    pub code3: Option<String>,
    pub name: String,
}
/// Published subdivision code and name.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct State {
    pub code: Option<String>,
    pub name: String,
}
/// Final canonical city or rural settlement; zero population becomes null.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct City {
    pub id: String,
    pub name: String,
    pub name_en: Option<String>,
    pub kind: String,
    pub population: Option<u32>,
    pub point: Option<Point>,
}
/// Audit details are omitted unless explicitly requested.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    pub stored_cell: Option<String>,
    pub city_method: Option<String>,
    pub land_method: Option<String>,
    pub reason: Option<String>,
    pub distance_greater_than_km: Option<f64>,
    pub distance_at_most_km: Option<f64>,
    pub source_ids: Option<serde_json::Value>,
}
/// One detached lookup answer, serialized identically by every binding.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LookupResult {
    pub status: String,
    pub kind: String,
    pub r#match: Option<String>,
    pub country: Option<Country>,
    pub state: Option<State>,
    pub city: Option<City>,
    pub timezone: Option<String>,
    pub point: Option<Point>,
    pub cell: Option<String>,
    pub distance_km: Option<f64>,
    pub candidates: Vec<Self>,
    pub selected: Option<Box<Self>>,
    pub rank_basis: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub evidence: Option<Evidence>,
}
impl LookupResult {
    /// Empty answer for an invalid input or an ordinary miss.
    #[must_use]
    pub fn empty(status: &str) -> Self {
        Self {
            status: status.into(),
            kind: "cell".into(),
            r#match: None,
            country: None,
            state: None,
            city: None,
            timezone: None,
            point: None,
            cell: None,
            distance_km: None,
            candidates: vec![],
            selected: None,
            rank_basis: None,
            evidence: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ambiguity_serializes_without_selection_or_invented_distance() {
        let mut result = LookupResult::empty("ambiguous");
        result.candidates.push(LookupResult::empty("matched"));
        let encoded = serde_json::to_value(&result).unwrap();
        assert!(encoded["selected"].is_null());
        assert!(encoded["distance_km"].is_null());
        assert_eq!(
            serde_json::from_value::<LookupResult>(encoded).unwrap(),
            result
        );
    }
}

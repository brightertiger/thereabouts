//! The language-independent, flat public result. No precision is invented.
use serde::{Deserialize, Serialize};

/// Lookup outcome; ordinary misses are not errors.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    /// Published geography or one resolved place.
    Matched,
    /// Several ranked places; flat fields remain null.
    Ambiguous,
    /// No stored answer for the query.
    NotFound,
    /// The query cannot be interpreted in this domain.
    InvalidInput,
}
impl Status {
    /// Stable JSON spelling, also used by column dictionaries.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Matched => "matched",
            Self::Ambiguous => "ambiguous",
            Self::NotFound => "not_found",
            Self::InvalidInput => "invalid_input",
        }
    }
}
/// The domain of the returned lookup answer.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    /// A canonical city or rural settlement.
    City,
    /// A spatial cell, including country-only reverse context.
    Cell,
    /// A country identified by a forward lookup.
    Country,
    /// An administrative subdivision.
    Region,
    /// A postal code with a published anchor.
    Postcode,
    /// An airport identified by a supported code.
    Airport,
    /// A port or other transport location.
    Port,
}
impl Kind {
    /// Stable JSON spelling, also used by column dictionaries.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::City => "city",
            Self::Cell => "cell",
            Self::Country => "country",
            Self::Region => "region",
            Self::Postcode => "postcode",
            Self::Airport => "airport",
            Self::Port => "port",
        }
    }
}
/// Spatial method published by the dataset.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Match {
    /// The dataset publishes polygon or area containment.
    Contained,
    /// The published nearest-distance band below the distant threshold.
    Nearest,
    /// The published nearest-distance band above the distant threshold.
    NearestDistant,
}
impl Match {
    /// Stable JSON spelling, also used by column dictionaries.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Contained => "contained",
            Self::Nearest => "nearest",
            Self::NearestDistant => "nearest_distant",
        }
    }
}
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
/// Published nearest-distance interval; no exact distance is inferred.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DistanceBand {
    pub greater_than_km: f64,
    pub at_most_km: f64,
}
/// Audit details are omitted unless explicitly requested.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    pub stored_cell: Option<String>,
    pub country_id: Option<String>,
    pub state_id: Option<String>,
    pub city_id: Option<String>,
    pub city_method: Option<String>,
    pub land_method: Option<String>,
    pub reason: Option<String>,
    pub timezones: Vec<String>,
    pub source_ids: Option<serde_json::Value>,
}
/// One detached lookup answer, serialized identically by every binding.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LookupResult {
    pub status: Status,
    pub kind: Kind,
    pub r#match: Option<Match>,
    pub country: Option<Country>,
    pub state: Option<State>,
    pub city: Option<City>,
    pub timezone: Option<String>,
    pub point: Option<Point>,
    pub cell: Option<String>,
    pub distance_band: Option<DistanceBand>,
    pub candidates: Vec<Self>,
    pub rank_basis: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub evidence: Option<Evidence>,
}
impl LookupResult {
    /// Empty answer for an invalid input or an ordinary miss.
    #[must_use]
    pub fn empty(status: Status) -> Self {
        Self {
            status,
            kind: Kind::Cell,
            r#match: None,
            country: None,
            state: None,
            city: None,
            timezone: None,
            point: None,
            cell: None,
            distance_band: None,
            candidates: vec![],
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
        let mut result = LookupResult::empty(crate::result::Status::Ambiguous);
        result
            .candidates
            .push(LookupResult::empty(crate::result::Status::Matched));
        let encoded = serde_json::to_value(&result).unwrap();
        assert!(encoded.get("selected").is_none());
        assert!(encoded["distance_band"].is_null());
        assert_eq!(
            serde_json::from_value::<LookupResult>(encoded).unwrap(),
            result
        );
    }
}

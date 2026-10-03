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
    /// The input requests detail finer than the dataset supports.
    UnsupportedGranularity,
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
            Self::UnsupportedGranularity => "unsupported_granularity",
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
    /// A postal code with a published anchor.
    Postal,
    /// An airport identified by a supported code.
    Airport,
    /// A port or other transport location.
    TradeLocation,
    /// A published IP address interval.
    IpRange,
    /// A published calling-code or telephone prefix.
    PhonePrefix,
    /// A vehicle registration format or series.
    Plate,
}
impl Kind {
    /// Stable JSON spelling, also used by column dictionaries.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::City => "city",
            Self::Cell => "cell",
            Self::Postal => "postal",
            Self::Airport => "airport",
            Self::TradeLocation => "trade_location",
            Self::IpRange => "ip_range",
            Self::PhonePrefix => "phone_prefix",
            Self::Plate => "plate",
        }
    }
}
/// Spatial method published by the dataset.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Match {
    /// An exact normalized identifier or primary name.
    Exact,
    /// A published English or alternate name.
    AlternateName,
    /// A fuzzy name-index match.
    Fuzzy,
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
            Self::Exact => "exact",
            Self::AlternateName => "alternate_name",
            Self::Fuzzy => "fuzzy",
            Self::Contained => "contained",
            Self::Nearest => "nearest",
            Self::NearestDistant => "nearest_distant",
        }
    }
}
/// Geographic degrees, rounded only when stored as a catalogue microdegree point.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Point {
    /// Latitude in geographic degrees.
    pub lat: f64,
    /// Longitude in geographic degrees.
    pub lon: f64,
}
/// Country metadata from the dataset, with nullable alpha-3.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Country {
    /// Published two-letter country code.
    pub code: String,
    /// Published alpha-3 code, or null when unavailable.
    pub code3: Option<String>,
    /// Country display name from the place catalogue.
    pub name: String,
}
/// Published subdivision code and name.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct State {
    /// Published subdivision code, falling back to the place code only if no row exists.
    pub code: Option<String>,
    /// Subdivision table name, falling back only when the row is absent.
    pub name: String,
}
/// Final canonical city or rural settlement; zero population becomes null.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct City {
    /// Stable canonical city or final rural-settlement identity.
    pub id: String,
    /// Published canonical display name; never reconstructed by the client.
    pub name: String,
    /// English name when the dataset supplies one.
    pub name_en: Option<String>,
    /// Published settlement class such as city, town or village.
    pub kind: String,
    /// Published population, with unknown zero represented as null.
    pub population: Option<u32>,
    /// Published catalogue anchor, independent of the query cell centre.
    pub point: Option<Point>,
}
/// Published nearest-distance interval; no exact distance is inferred.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DistanceBand {
    /// Exclusive lower policy bound in kilometres.
    pub greater_than_km: f64,
    /// Inclusive upper policy bound in kilometres.
    pub at_most_km: f64,
}
/// Audit details are omitted unless explicitly requested.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    /// Stored pack ancestor, possibly split by a timezone boundary.
    pub stored_cell: Option<String>,
    /// Country catalogue identity behind the spatial label.
    pub country_id: Option<String>,
    /// Subdivision catalogue identity behind the spatial label.
    pub state_id: Option<String>,
    /// Final city or settlement identity behind the spatial label.
    pub city_id: Option<String>,
    /// Original golden assignment method, when a city is assigned.
    pub city_method: Option<String>,
    /// Published land or offshore eligibility marker.
    pub land_method: Option<String>,
    /// Detailed matched or not-found reason without changing public status.
    pub reason: Option<String>,
    /// Unresolved zone survivors after country narrowing; empty for a unique zone.
    pub timezones: Vec<String>,
    /// Source identifiers published in the city catalogue evidence.
    pub source_ids: Option<serde_json::Value>,
}
/// One detached lookup answer, serialized identically by every binding.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LookupResult {
    /// Typed outcome; misses and invalid query values are ordinary results.
    pub status: Status,
    /// Domain of the answer; reverse uses cell.
    pub kind: Kind,
    /// Published spatial method, absent for misses and invalid inputs.
    pub r#match: Option<Match>,
    /// Flat country context for an unambiguous match.
    pub country: Option<Country>,
    /// Flat subdivision context, using indexed metadata.
    pub state: Option<State>,
    /// Final published canonical city or rural settlement.
    pub city: Option<City>,
    /// Single country-valid zone; unresolved overlap stays in evidence.
    pub timezone: Option<String>,
    /// Representative query-cell centre for reverse lookups.
    pub point: Option<Point>,
    /// Canonical query H3 cell; coarse inputs retain their own resolution.
    pub cell: Option<String>,
    /// Published nearest-policy interval, absent for contained results.
    pub distance_band: Option<DistanceBand>,
    /// Ranked forward candidates; reverse always leaves this empty.
    pub candidates: Vec<Self>,
    /// Forward ranking rule, absent for reverse lookups.
    pub rank_basis: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    /// Opt-in audit fields, omitted from JSON when not requested.
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

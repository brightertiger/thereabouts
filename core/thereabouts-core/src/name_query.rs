//! Reject identifiers and street-level requests before city-name retrieval.
use crate::result::{Kind, LookupResult, Status};
pub(crate) fn invalid(hint: &str) -> LookupResult {
    let mut r = LookupResult::empty(Status::InvalidInput);
    r.kind = Kind::City;
    r.hint = Some(hint.into());
    r
}
pub(crate) fn classify(value: &str, known_name: bool) -> Option<LookupResult> {
    let value = value.trim();
    let hint = if crate::ip::parse(value).is_some()
        || (value.matches('.').count() == 3
            && value.chars().all(|c| c.is_ascii_digit() || c == '.'))
    {
        Some("Use ip(address) for IP addresses.")
    } else if value.starts_with('+') {
        Some("Use phone(number) for international phone numbers.")
    } else if value.parse::<h3o::CellIndex>().is_ok() {
        Some("Use from_h3(cell) for H3 identifiers.")
    } else if !value.is_empty()
        && value
            .chars()
            .all(|c| c.is_ascii_digit() || c == '-' || c == ' ')
    {
        Some("Use postal(code, country=\"XX\") for postal codes.")
    } else {
        None
    };
    if let Some(hint) = hint {
        return Some(invalid(hint));
    }
    if known_name {
        return None;
    }
    let words = value.to_ascii_lowercase().replace([',', '.'], " ");
    let address = words.split_whitespace().any(|s| {
        matches!(
            s,
            "street" | "road" | "avenue" | "boulevard" | "rue" | "strasse" | "straße" | "lane"
        )
    }) || (value.chars().next().is_some_and(|c| c.is_ascii_digit())
        && value.contains(' ')
        && value.chars().any(char::is_alphabetic));
    if address {
        let mut r = invalid("Finds towns and cities by name. Street addresses are not supported.");
        r.status = Status::UnsupportedGranularity;
        return Some(r);
    }
    if (3..=4).contains(&value.len()) && value.bytes().all(|c| c.is_ascii_uppercase()) {
        return Some(invalid("Use airport(code) for airport identifiers."));
    }
    if crate::locode::valid(value) {
        return Some(invalid("Use locode(code) for trade-location identifiers."));
    }
    if value.chars().any(|c| c.is_ascii_digit())
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == ' ' || c == '-')
    {
        let letters = value.chars().filter(char::is_ascii_alphabetic).count();
        let hint = if value.len() >= 9 && letters >= 4 {
            "Use plate(value, country=\"XX\") for vehicle registrations."
        } else {
            "Use postal(code, country=\"XX\") for postal codes."
        };
        return Some(invalid(hint));
    }
    None
}

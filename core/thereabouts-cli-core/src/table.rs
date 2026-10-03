//! Bounded human summaries; details and evidence belong in JSON.
use serde_json::Value;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};
pub(crate) const SUMMARY: &[&str] = &[
    "status", "country", "state", "city", "timezone", "point", "match",
];
const MAX_WIDTH: usize = 28;

pub(crate) fn columns(value: &Value, batch: bool) -> Vec<String> {
    SUMMARY
        .iter()
        .filter(|key| {
            batch
                || **key == "status"
                || value.get(**key).is_some_and(|v| !v.is_null())
                || value
                    .get("candidates")
                    .and_then(Value::as_array)
                    .is_some_and(|rows| {
                        rows.iter()
                            .any(|r| r.get(**key).is_some_and(|v| !v.is_null()))
                    })
        })
        .map(|s| (*s).into())
        .collect()
}
fn width(key: &str) -> usize {
    match key.strip_prefix("thereabouts_").unwrap_or(key) {
        "status" => 23,
        "country" => 10,
        "match" => 15,
        _ => MAX_WIDTH,
    }
}
fn summary(key: &str, value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        Value::Object(_) => {
            if let Some((lat, lon)) = value
                .get("lat")
                .and_then(Value::as_f64)
                .zip(value.get("lon").and_then(Value::as_f64))
            {
                return format!("{lat:.5}, {lon:.5}");
            }
            let first = if key.ends_with("country") {
                "code"
            } else {
                "name"
            };
            value
                .get(first)
                .or_else(|| value.get("code"))
                .map_or_else(|| value.to_string(), |v| summary(key, v))
        }
        _ => value.to_string(),
    }
}
fn cell(value: &str, width: usize) -> String {
    let clean: String = value
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let mut text = String::new();
    if clean.width() > width {
        let mut used = 0;
        for c in clean.chars() {
            let next = c.width().unwrap_or(0);
            if used + next >= width {
                break;
            }
            text.push(c);
            used += next;
        }
        text.push('…');
    } else {
        text = clean;
    }
    format!("{text}{}", " ".repeat(width.saturating_sub(text.width())))
}
pub(crate) fn header(columns: &[String]) -> String {
    format!(
        "{}\n",
        columns
            .iter()
            .map(|k| cell(k, width(k)))
            .collect::<Vec<_>>()
            .join(" | ")
            .trim_end()
    )
}
pub(crate) fn row(columns: &[String], value: &Value, indent: bool) -> String {
    let cells = columns
        .iter()
        .map(|key| {
            cell(
                &summary(key, value.get(key).unwrap_or(&Value::Null)),
                width(key),
            )
        })
        .collect::<Vec<_>>();
    format!(
        "{}{}\n",
        if indent { "  " } else { "" },
        cells.join(" | ").trim_end()
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn text_is_bounded_and_terminal_controls_are_removed() {
        assert_eq!(cell("abcdefgh", 5), "abcd…");
        assert_eq!(cell("a\nb", 5), "a b  ");
        assert_eq!(cell("éééééé", 5), "éééé…");
        assert_eq!(cell("東京大阪", 5), "東京…");
    }
}

//! Bounded human summaries; details and evidence belong in JSON.
use crate::error::{Error, Result};
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
fn heading(key: &str) -> &str {
    key.strip_prefix("thereabouts_").unwrap_or(key)
}
/// One stream layout, chosen from its first row/candidates and the terminal budget.
pub(crate) struct Layout {
    widths: Vec<usize>,
    separator: &'static str,
}
impl Layout {
    pub fn new(columns: &[String], value: &Value, terminal: usize) -> Result<Self> {
        let candidates = value
            .get("candidates")
            .or_else(|| value.get("thereabouts_candidates"))
            .and_then(Value::as_array);
        let reserve = usize::from(candidates.is_some_and(|rows| !rows.is_empty())) * 2;
        let budget = terminal.saturating_sub(reserve);
        let minimum: Vec<_> = columns
            .iter()
            .map(|k| heading(k).width().clamp(1, MAX_WIDTH))
            .collect();
        let mut widths: Vec<_> = columns
            .iter()
            .zip(&minimum)
            .map(|(key, min)| {
                let current = summary(key, value.get(key).unwrap_or(&Value::Null)).width();
                let candidate = candidates
                    .into_iter()
                    .flatten()
                    .map(|row| summary(key, row.get(heading(key)).unwrap_or(&Value::Null)).width())
                    .max()
                    .unwrap_or(0);
                current.max(candidate).max(*min).min(MAX_WIDTH)
            })
            .collect();
        let gaps = columns.len().saturating_sub(1);
        let separator = if minimum.iter().sum::<usize>() + 3 * gaps > budget {
            "  "
        } else {
            " | "
        };
        let available = budget.saturating_sub(separator.len() * gaps);
        if minimum.iter().sum::<usize>() > available {
            return Err(Error::Usage(
                "Table columns do not fit the terminal; use --fields or --json".into(),
            ));
        }
        while widths.iter().sum::<usize>() > available {
            let widest = widths
                .iter_mut()
                .zip(&minimum)
                .filter(|(width, min)| **width > **min)
                .max_by_key(|(width, _)| **width);
            if let Some((width, _)) = widest {
                *width -= 1;
            } else {
                break;
            }
        }
        Ok(Self { widths, separator })
    }
    pub fn header(&self, columns: &[String]) -> String {
        format!(
            "{}\n",
            columns
                .iter()
                .zip(&self.widths)
                .map(|(key, width)| cell(heading(key), *width))
                .collect::<Vec<_>>()
                .join(self.separator)
                .trim_end()
        )
    }
    pub fn row(&self, columns: &[String], value: &Value, indent: bool) -> String {
        let cells = columns
            .iter()
            .zip(&self.widths)
            .map(|(key, width)| {
                cell(
                    &summary(key, value.get(key).unwrap_or(&Value::Null)),
                    *width,
                )
            })
            .collect::<Vec<_>>();
        format!(
            "{}{}\n",
            if indent { "  " } else { "" },
            cells.join(self.separator).trim_end()
        )
    }
}

#[cfg(test)]
#[allow(clippy::indexing_slicing)]
mod tests {
    use super::*;
    #[test]
    fn text_is_bounded_and_terminal_controls_are_removed() {
        assert_eq!(cell("abcdefgh", 5), "abcd…");
        assert_eq!(cell("a\nb", 5), "a b  ");
        assert_eq!(cell("éééééé", 5), "éééé…");
        assert_eq!(cell("東京大阪", 5), "東京…");
    }
    #[test]
    fn terminal_budget_preserves_headers_and_bounds_unicode_candidates() {
        let columns = SUMMARY.iter().map(|s| (*s).into()).collect::<Vec<_>>();
        let candidate = serde_json::json!({"status":"matched", "country":{"code":"JP"},
            "state":{"name":"東京大阪東京大阪東京大阪東京大阪"}, "city":{"name":"A very long city name used for width"},
            "timezone":"Asia/Tokyo", "point":{"lat":35.1,"lon":139.1}, "match":"nearest_distant"});
        let mut value = candidate.clone();
        value["candidates"] = serde_json::json!([candidate]);
        for budget in [80, 100, 160] {
            let layout = Layout::new(&columns, &value, budget).unwrap();
            for line in [
                layout.header(&columns),
                layout.row(&columns, &value, false),
                layout.row(&columns, &value["candidates"][0], true),
            ] {
                assert!(line.trim_end().width() <= budget, "{line}");
            }
            assert!(layout.header(&columns).contains("timezone"));
        }
        let small = Layout::new(&columns, &value, 80).unwrap();
        let wide = Layout::new(&columns, &value, 160).unwrap();
        assert!(small.widths.iter().sum::<usize>() < wide.widths.iter().sum::<usize>());
        assert!(Layout::new(&columns, &value, 20).is_err());
    }
}

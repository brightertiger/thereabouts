//! Bounded human summaries; details and evidence belong in JSON.
use crate::error::{Error, Result};
use serde_json::Value;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};
pub(crate) const SUMMARY: &[&str] = &[
    "status", "country", "state", "city", "timezone", "point", "match",
];

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
pub(crate) fn summary(key: &str, value: &Value) -> String {
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
/// Measure every row before allocating the terminal budget.
pub(crate) struct Layout {
    widths: Vec<usize>,
    minimum: Vec<usize>,
    indent: bool,
    separator: &'static str,
}
impl Layout {
    pub fn new(columns: &[String]) -> Self {
        let minimum: Vec<_> = columns.iter().map(|k| heading(k).width().max(1)).collect();
        Self {
            widths: minimum.clone(),
            minimum,
            indent: false,
            separator: " | ",
        }
    }
    pub fn observe(&mut self, columns: &[String], value: &Value) {
        let candidates = value
            .get("candidates")
            .or_else(|| value.get("thereabouts_candidates"))
            .and_then(Value::as_array);
        self.indent |= candidates.is_some_and(|rows| !rows.is_empty());
        for (key, width) in columns.iter().zip(&mut self.widths) {
            let current = summary(key, value.get(key).unwrap_or(&Value::Null)).width();
            let candidate = candidates
                .into_iter()
                .flatten()
                .map(|row| summary(key, row.get(heading(key)).unwrap_or(&Value::Null)).width())
                .max()
                .unwrap_or(0);
            *width = (*width).max(current).max(candidate);
        }
    }
    pub fn fit(&mut self, terminal: usize) -> Result<()> {
        let budget = terminal.saturating_sub(usize::from(self.indent) * 2);
        let gaps = self.widths.len().saturating_sub(1);
        self.separator = if self.minimum.iter().sum::<usize>() + 3 * gaps > budget {
            "  "
        } else {
            " | "
        };
        let available = budget.saturating_sub(self.separator.len() * gaps);
        if self.minimum.iter().sum::<usize>() > available {
            return Err(Error::Usage(
                "Table columns do not fit the terminal; use --fields or --json".into(),
            ));
        }
        // Water-fill from natural widths without work proportional to a huge cell.
        let (mut low, mut high) = (0, self.widths.iter().copied().max().unwrap_or(0));
        while low < high {
            let middle = low + (high - low).div_ceil(2);
            let used: usize = self
                .widths
                .iter()
                .zip(&self.minimum)
                .map(|(width, min)| (*width).min(middle).max(*min))
                .sum();
            if used <= available {
                low = middle;
            } else {
                high = middle - 1;
            }
        }
        let natural = self.widths.clone();
        for (width, min) in self.widths.iter_mut().zip(&self.minimum) {
            *width = (*width).min(low).max(*min);
        }
        let mut slack = available.saturating_sub(self.widths.iter().sum::<usize>());
        for (width, natural) in self.widths.iter_mut().zip(natural) {
            if slack > 0 && *width < natural {
                *width += 1;
                slack -= 1;
            }
        }
        Ok(())
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
    fn later_rows_receive_their_natural_width_on_a_wide_terminal() {
        let columns = vec!["lat".into(), "state".into()];
        let first = serde_json::json!({"lat":"0", "state":{"name":"X"}});
        let later = serde_json::json!({"lat":"1.3521", "state":{"name":"Wilayah Persekutuan Kuala Lumpur"}});
        let mut layout = Layout::new(&columns);
        layout.observe(&columns, &first);
        layout.observe(&columns, &later);
        layout.fit(200).unwrap();
        let row = layout.row(&columns, &later, false);
        assert!(row.contains("1.3521"));
        assert!(row.contains("Wilayah Persekutuan Kuala Lumpur"));
        assert!(!row.contains('…'));
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
            let mut layout = Layout::new(&columns);
            layout.observe(&columns, &value);
            layout.fit(budget).unwrap();
            for line in [
                layout.header(&columns),
                layout.row(&columns, &value, false),
                layout.row(&columns, &value["candidates"][0], true),
            ] {
                assert!(line.trim_end().width() <= budget, "{line}");
            }
            assert!(layout.header(&columns).contains("timezone"));
        }
        let mut small = Layout::new(&columns);
        small.observe(&columns, &value);
        let mut wide = Layout::new(&columns);
        wide.observe(&columns, &value);
        small.fit(80).unwrap();
        wide.fit(160).unwrap();
        assert!(small.widths.iter().sum::<usize>() < wide.widths.iter().sum::<usize>());
        assert!(Layout::new(&columns).fit(20).is_err());
    }
}

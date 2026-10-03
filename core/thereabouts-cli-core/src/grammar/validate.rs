//! Arity, types and command constraints shared by both hosts.
use super::{Arity, Description, Parsed};
use crate::error::Result;
use serde_json::Value;
pub(super) fn run(grammar: &Description, parsed: &Parsed) -> Result<()> {
    let options = &parsed.options;
    if ["format", "json", "csv"]
        .iter()
        .filter(|k| options.contains_key(**k))
        .count()
        > 1
    {
        return Err(grammar.error("output_conflict", &[]));
    }
    for (key, value) in options {
        if let Some(flag) = grammar.flag(&parsed.command, key)
            && let Some(value) = value.as_str()
        {
            if !flag.choices.is_empty()
                && !flag.choices.iter().any(|choice| {
                    if flag.ignore_case {
                        choice.eq_ignore_ascii_case(value)
                    } else {
                        choice == value
                    }
                })
            {
                return Err(grammar.error(&flag.error, &[]));
            }
            if flag.numeric == "float" && value.parse::<f64>().is_err() {
                return Err(grammar.error("number", &[("name", key)]));
            }
            if flag.numeric == "integer"
                && (!value.bytes().all(|c| c.is_ascii_digit())
                    || value.parse::<u16>().ok().is_none_or(|n| {
                        flag.minimum.is_some_and(|min| n < min)
                            || flag.maximum.is_some_and(|max| n > max)
                    }))
            {
                return Err(grammar.error(&flag.error, &[]));
            }
        }
    }
    if let Some(fields) = options.get("fields").and_then(Value::as_str) {
        if fields.is_empty() {
            return Ok(());
        }
        crate::render::fields(Some(fields))?;
    }
    let Some(command) = grammar.command(&parsed.command) else {
        return Ok(());
    };
    if command.name == "data" {
        return Err(grammar.error("data", &[]));
    }
    match command.arity {
        Arity::Reverse => {
            let count = parsed.values.len();
            let lat = options.contains_key("lat");
            let lon = options.contains_key("lon");
            if count > 1 || count == 1 && (lat || lon) {
                return Err(grammar.error("reverse_choice", &[]));
            }
            if count == 0
                && (!lat
                    || !lon
                    || options.contains_key("lat-col")
                    || options.contains_key("lon-col"))
            {
                return Err(grammar.error("reverse_required", &[]));
            }
        }
        Arity::Many if parsed.values.is_empty() => return Err(grammar.error("install", &[])),
        Arity::Many => (),
        Arity::One | Arity::None => {
            let wanted = usize::from(matches!(command.arity, Arity::One));
            if parsed.values.len() != wanted {
                return Err(grammar.error(
                    "positionals",
                    &[("command", &command.name), ("count", &wanted.to_string())],
                ));
            }
        }
    }
    for flag in &command.options {
        if let Some(message) = &flag.required
            && !options.contains_key(&flag.name)
        {
            return Err(grammar.error(message, &[]));
        }
    }
    Ok(())
}

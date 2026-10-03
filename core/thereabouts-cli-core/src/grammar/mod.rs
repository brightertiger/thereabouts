//! One portable grammar description drives both hosts' help and argument diagnostics.
mod parse;
mod validate;
use crate::error::{Error, Result};
pub use parse::{Parsed, parse};
use serde::Deserialize;
use std::{collections::BTreeMap, fmt::Write};

/// Embedded source consumed by native policy and exported verbatim to WASM hosts.
#[must_use]
pub const fn description() -> &'static str {
    include_str!("grammar.json")
}
#[derive(Deserialize)]
struct Flag {
    name: String,
    value: String,
    description: String,
    #[serde(default)]
    choices: Vec<String>,
    #[serde(default)]
    ignore_case: bool,
    #[serde(default)]
    numeric: String,
    minimum: Option<u16>,
    maximum: Option<u16>,
    #[serde(default)]
    error: String,
    required: Option<String>,
}
#[derive(Deserialize)]
struct Command {
    name: String,
    about: String,
    args: String,
    arity: Arity,
    options: Vec<Flag>,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Arity {
    None,
    One,
    Many,
    Reverse,
}
#[derive(Deserialize)]
struct Description {
    about: String,
    globals: Vec<Flag>,
    commands: Vec<Command>,
    errors: BTreeMap<String, String>,
}
impl Description {
    fn load() -> Result<Self> {
        Ok(serde_json::from_str(description())?)
    }
    fn command(&self, name: &str) -> Option<&Command> {
        self.commands.iter().find(|c| c.name == name)
    }
    fn flag(&self, command: &str, name: &str) -> Option<&Flag> {
        self.globals
            .iter()
            .chain(self.command(command).into_iter().flat_map(|c| &c.options))
            .find(|f| f.name == name)
    }
    fn error(&self, key: &str, args: &[(&str, &str)]) -> Error {
        let mut text = self
            .errors
            .get(key)
            .cloned()
            .unwrap_or_else(|| "Invalid command arguments".into());
        for (name, value) in args {
            text = text.replace(&format!("{{{name}}}"), value);
        }
        Error::Usage(text)
    }
}
/// Help is rendered here so native and Node print exactly the same wording and layout.
pub fn help(command: &str) -> Result<String> {
    let grammar = Description::load()?;
    let selected = grammar.command(command);
    let about = selected.map_or(grammar.about.as_str(), |c| c.about.as_str());
    let usage = selected.map_or_else(
        || "[OPTIONS] [COMMAND]".into(),
        |c| format!("{} {} [OPTIONS]", c.name, c.args),
    );
    let mut output = format!("{about}\n\nUsage: thereabouts {usage}\n");
    if command == "reverse" {
        output.push_str("       thereabouts reverse FILE|- [OPTIONS]\n");
    }
    if command.is_empty() || command == "data" {
        output.push_str("\nCommands:\n");
        for c in &grammar.commands {
            if command.is_empty() && !c.name.contains(' ')
                || command == "data" && c.name.starts_with("data ")
            {
                let _ = writeln!(
                    output,
                    "  {}  {}",
                    c.name.strip_prefix("data ").unwrap_or(&c.name),
                    c.about
                );
            }
        }
    }
    output.push_str("\nOptions:\n");
    for flag in grammar
        .globals
        .iter()
        .chain(selected.into_iter().flat_map(|c| &c.options))
    {
        let value = match flag.value.as_str() {
            "" => String::new(),
            "?" => " [FIELDS]".into(),
            value => format!(" {value}"),
        };
        let _ = writeln!(output, "  --{}{value}  {}", flag.name, flag.description);
    }
    output.push_str("  --help  Print command help.\n");
    if command != "data install" {
        output.push_str("  --version  Print client version.\n");
    }
    Ok(output)
}

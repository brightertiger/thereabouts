//! Lex argv once, without any filesystem, environment or clap dependency.
use super::{Description, validate};
use crate::error::Result;
use serde::Serialize;
use serde_json::{Map, Value};

/// Host-neutral parsed request; native clap receives its canonical spelling for typed dispatch.
#[derive(Default, Serialize)]
pub struct Parsed {
    /// Explicit command, including the data subcommand when present.
    pub command: String,
    /// Positional values, never guessed from their shape.
    pub values: Vec<String>,
    /// Flag values; switches are booleans and explicit values are strings.
    pub options: Map<String, Value>,
    /// Help has precedence once encountered in argv.
    pub help: bool,
    /// Client version, except the data-install dataset selector.
    pub version: bool,
    /// Canonical argv for native typed dispatch; not part of the JS request.
    #[serde(skip)]
    pub argv: Vec<String>,
}
impl Parsed {
    fn canonical(&self, grammar: &Description) -> Vec<String> {
        let mut args = vec!["thereabouts".into()];
        for global in [true, false] {
            if !global {
                args.extend(self.command.split_whitespace().map(str::to_owned));
            }
            for (key, value) in &self.options {
                if grammar.globals.iter().any(|f| f.name == *key) != global {
                    continue;
                }
                // Equals protects a value beginning with '-' from clap's flag lexer.
                args.push(
                    value
                        .as_str()
                        .map_or_else(|| format!("--{key}"), |v| format!("--{key}={v}")),
                );
            }
        }
        if !self.values.is_empty() {
            args.push("--".into());
            args.extend(self.values.clone());
        }
        args
    }
}
/// Parse arguments excluding the executable name using the embedded JSON description.
pub fn parse(argv: &[String]) -> Result<Parsed> {
    let grammar = Description::load()?;
    let mut output = Parsed::default();
    let mut tokens = argv.iter().peekable();
    let mut terminated = false;
    while let Some(token) = tokens.next() {
        if !terminated && token == "--" {
            terminated = true;
            continue;
        }
        if !terminated && ["--help", "-h"].contains(&token.as_str()) {
            output.help = true;
            return Ok(output);
        }
        if !terminated
            && ["--version", "-V"].contains(&token.as_str())
            && output.command != "data install"
        {
            output.version = true;
            return Ok(output);
        }
        if !terminated && let Some(flag) = token.strip_prefix("--") {
            let (name, given) = flag
                .split_once('=')
                .map_or((flag, None), |(k, v)| (k, Some(v)));
            let spec = grammar.flag(&output.command, name).ok_or_else(|| {
                grammar.error("unknown_option", &[("option", &format!("--{name}"))])
            })?;
            if output.options.contains_key(name) {
                return Err(grammar.error("repeated_option", &[("name", name)]));
            }
            let value = if spec.value.is_empty() {
                if given.is_some() {
                    return Err(grammar.error("no_value", &[("name", name)]));
                }
                Value::Bool(true)
            } else if spec.value == "?"
                && given.is_none()
                && tokens.peek().is_none_or(|t| t.starts_with('-'))
            {
                Value::String(String::new())
            } else {
                let value = given
                    .or_else(|| tokens.next().map(String::as_str))
                    .filter(|v| !v.starts_with('-') || spec.numeric == "float")
                    .ok_or_else(|| grammar.error("needs_value", &[("name", name)]))?;
                Value::String(value.into())
            };
            output.options.insert(name.into(), value);
        } else if !terminated && token.starts_with('-') && token != "-" {
            return Err(grammar.error("unknown_option", &[("option", token)]));
        } else if output.command.is_empty() {
            if grammar.command(token).is_none() || token.contains(' ') {
                return Err(grammar.error("unknown_command", &[("command", token)]));
            }
            output.command.clone_from(token);
        } else if output.command == "data" {
            let command = format!("data {token}");
            if grammar.command(&command).is_none() {
                return Err(grammar.error("unknown_data", &[("command", token)]));
            }
            output.command = command;
        } else {
            output.values.push(token.clone());
        }
    }
    validate::run(&grammar, &output)?;
    output.argv = output.canonical(&grammar);
    Ok(output)
}

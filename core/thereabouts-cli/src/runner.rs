//! Parse once, resolve data explicitly, and stream detached public results.
use crate::{
    args::{Cli, Command, Format},
    batch, data,
    error::{Error, Result},
    io::Io,
    query,
    render::{self, Renderer},
    store,
};
use clap::{CommandFactory, Parser};

/// Execute argv including its program name. Help and version never touch data.
pub fn run(argv: &[String], io: &mut dyn Io) -> i32 {
    let cli = match Cli::try_parse_from(argv) {
        Ok(cli) => cli,
        Err(error) => {
            let code = if error.use_stderr() { 2 } else { 0 };
            let printed = if code == 0 {
                io.stdout(&error.to_string())
            } else {
                io.stderr(&error.to_string())
            };
            return if printed.is_err() { 4 } else { code };
        }
    };
    match execute(&cli, io) {
        Ok(code) => code,
        Err(Error::Io(error)) if error.kind() == std::io::ErrorKind::BrokenPipe => 0,
        Err(Error::Missing(family)) => {
            let _ = io.stderr(&format!("{family} data is not installed. Install it with:\nthereabouts data install {family}\n"));
            3
        }
        Err(error) => {
            let _ = io.stderr(&format!("{error}\n"));
            error.exit_code()
        }
    }
}
fn execute(cli: &Cli, io: &mut dyn Io) -> Result<i32> {
    if cli.global.fields.as_deref() == Some("") {
        io.stdout(&format!("{}\n", render::FIELDS.join("\n")))?;
        return Ok(0);
    }
    let Some(command) = &cli.command else {
        io.stderr(&Cli::command().render_help().to_string())?;
        return Ok(2);
    };
    let fields = render::fields(cli.global.fields.as_deref())?;
    let format = cli.global.format.unwrap_or_else(|| {
        if cli.global.json {
            Format::Json
        } else if cli.global.csv {
            Format::Csv
        } else if io.stdout_tty() {
            Format::Table
        } else {
            Format::Ndjson
        }
    });
    let root = store::directory(cli.global.data_dir.as_deref(), io)?;
    let root = if root.is_absolute() {
        root
    } else {
        std::env::current_dir()?.join(root)
    };
    let mut renderer = Renderer::new(format, false);
    if let Some(fields) = &fields {
        renderer.columns(fields.clone());
    }
    let (value, exit) = match command {
        Command::Data { operation } => (data::run(operation, &root, cli.global.no_input, io)?, 0),
        Command::Info => (data::info(&root)?, 0),
        Command::Mcp => {
            // A native host may supply its own MCP bridge; Python owns the optional SDK.
            return io.mcp(&root);
        }
        command => {
            let (pack, path) = query::open(&root, command)?;
            let family = query::family(command).unwrap_or("core");
            if let Command::Reverse {
                file: Some(file),
                lat_col,
                lon_col,
                ..
            } = command
            {
                return batch::run(
                    file,
                    lat_col.as_deref(),
                    lon_col.as_deref(),
                    &pack,
                    &cli.global,
                    format,
                    io,
                )
                .map_err(|e| e.at_pack(&path, family));
            }
            let answer = query::run(&pack, command, cli.global.evidence)
                .map_err(|e| e.at_pack(&path, family))?;
            let exit = thereabouts_cli_core::exit(answer.status, cli.global.strict);
            (
                render::select(&serde_json::to_value(answer)?, fields.as_deref()),
                exit,
            )
        }
    };
    if matches!(format, Format::Table | Format::Csv)
        && let Some(packs) = value.get("packs").and_then(serde_json::Value::as_array)
    {
        for pack in packs {
            let row = if matches!(command, Command::Info) {
                serde_json::json!({
                    "family":pack["family"],"data_version":pack["data_version"],
                    "format_minor":pack.get("format_minor").cloned().unwrap_or(serde_json::json!(0)),
                    "client_version":env!("CARGO_PKG_VERSION"),
                    "attribution":pack["attribution"],
                })
            } else {
                pack.clone()
            };
            renderer.row(&row, io)?;
        }
        if packs.is_empty() && format == Format::Table {
            io.stdout("No installed packs\n")?;
        }
    } else {
        renderer.row(&value, io)?;
    }
    renderer.finish(io)?;
    Ok(exit)
}

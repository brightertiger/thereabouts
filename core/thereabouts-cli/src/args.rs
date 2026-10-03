//! One explicit command for each input domain.
use clap::{Args, Parser, Subcommand, ValueEnum};
use std::path::PathBuf;

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub(crate) enum Format {
    Table,
    Json,
    Ndjson,
    Csv,
}

#[derive(Debug, Args)]
#[allow(clippy::struct_excessive_bools)] // Independent user-facing switches, validated by clap.
pub(crate) struct Global {
    #[arg(long, global = true)]
    pub data_dir: Option<PathBuf>,
    #[arg(long, global=true, value_enum, conflicts_with_all=["json","csv"])]
    pub format: Option<Format>,
    #[arg(long, global = true, conflicts_with = "csv")]
    pub json: bool,
    #[arg(long, global = true)]
    pub csv: bool,
    /// Select comma-separated result paths; omit the value to list paths.
    #[arg(long, global=true, num_args=0..=1, default_missing_value="")]
    pub fields: Option<String>,
    #[arg(long, global = true)]
    pub evidence: bool,
    #[arg(long, global = true)]
    pub quiet: bool,
    #[arg(long, global = true)]
    pub no_input: bool,
    #[arg(long, global = true)]
    pub strict: bool,
}
#[derive(Debug, Parser)]
#[command(name="thereabouts", version, propagate_version=true, color=clap::ColorChoice::Never,
    disable_help_subcommand=true, about="Offline geographic context from explicitly installed data.")]
pub(crate) struct Cli {
    #[command(flatten)]
    pub global: Global,
    #[command(subcommand)]
    pub command: Option<Command>,
}
#[derive(Debug, Subcommand)]
pub(crate) enum Command {
    /// Find geographic context or read CSV/NDJSON points.
    Reverse {
        #[arg(conflicts_with_all=["lat","lon"])]
        file: Option<String>,
        #[arg(
            long,
            allow_hyphen_values = true,
            requires = "lon",
            required_unless_present = "file"
        )]
        lat: Option<f64>,
        #[arg(long, allow_hyphen_values = true, requires = "lat")]
        lon: Option<f64>,
        #[arg(long, requires = "file")]
        lat_col: Option<String>,
        #[arg(long, requires = "file")]
        lon_col: Option<String>,
    },
    /// Find the stored ancestor of an H3 cell.
    H3 { cell: String },
    /// Finds towns and cities by name. Street addresses are not supported.
    #[command(about = "Finds towns and cities by name. Street addresses are not supported.")]
    Geocode {
        text: String,
        #[arg(long)]
        country: Option<String>,
        #[arg(long)]
        subdivision: Option<String>,
        #[arg(long, default_value_t=5, value_parser=clap::value_parser!(u16).range(1..=100))]
        limit: u16,
        #[arg(long, value_parser=["population"])]
        prefer: Option<String>,
    },
    /// Find a postal code in its source country.
    Postal {
        code: String,
        #[arg(long)]
        country: String,
    },
    /// Find an airport by IATA/ICAO or an explicit scheme.
    Airport {
        code: String,
        #[arg(long, value_parser=["iata","icao","gps","local","ident"], ignore_case=true)]
        scheme: Option<String>,
        #[arg(long)]
        country: Option<String>,
    },
    /// Find a five-character country/location code.
    Locode {
        code: String,
        #[arg(long)]
        country: Option<String>,
    },
    /// Find published context for an IPv4 or IPv6 literal.
    Ip { address: String },
    /// Find an E.164 prefix; country narrows shared calling codes.
    Phone {
        number: String,
        #[arg(long)]
        country: Option<String>,
    },
    /// Find registration country and series context.
    Plate {
        text: String,
        #[arg(long)]
        country: Option<String>,
        #[arg(long)]
        series: Option<String>,
    },
    /// Explicitly manage installed data.
    Data {
        #[command(subcommand)]
        operation: Data,
    },
    /// Report active pack identities and capabilities.
    Info,
    /// Serve current lookup verbs through the optional Python MCP host.
    Mcp,
}
#[derive(Debug, Subcommand)]
pub(crate) enum Data {
    #[command(disable_version_flag = true)]
    Install {
        #[arg(required=true, num_args=1..)]
        packs: Vec<String>,
        #[arg(long = "version")]
        version: Option<String>,
        #[arg(long = "from")]
        source: Option<String>,
        #[arg(long)]
        yes: bool,
    },
    List {
        #[arg(long)]
        remote: bool,
    },
    Verify {
        #[arg(long)]
        full: bool,
    },
    Remove {
        pack: String,
        #[arg(long)]
        yes: bool,
    },
    Path,
    Update {
        #[arg(long, required = true)]
        check: bool,
    },
}

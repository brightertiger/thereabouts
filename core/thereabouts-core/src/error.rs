//! Stable failure codes; misses remain ordinary lookup results.
use thiserror::Error;

/// Failures that prevent interpreting a pack or completing an operation.
#[derive(Debug, Error)]
pub enum Error {
    #[error("thereabouts data install core")]
    /// No pack was discovered in the store; bindings present the install command.
    Missing,
    #[error("Pack not found: {0}")]
    /// The explicitly selected directory does not exist.
    PackNotFound(std::path::PathBuf),
    #[error("{0}")]
    /// The pack requires another format, family or required feature.
    Incompatible(String),
    #[error("{0}")]
    /// Wire structure, reference or checksum validation failed.
    Corrupt(String),
    #[error("Geocoder is closed")]
    /// A binding handle has been explicitly closed.
    Closed,
    #[error("{0}")]
    /// An internal codec caller supplied an invalid encoding value.
    Input(String),
    #[error("{0}")]
    /// The process ran out of file descriptors; this is not damage to the pack.
    ResourceLimit(String),
    #[error("Internal error: {0}; please report it")]
    /// A library invariant failed (for example a poisoned lock); not damage to the pack.
    Internal(String),
    #[error(transparent)]
    /// An inventoried pack file could not be read.
    Io(std::io::Error),
    #[error(transparent)]
    /// Pack JSON could not be parsed without losing its structure.
    Json(#[from] serde_json::Error),
}
impl Error {
    /// Machine-readable code, independent of the diagnostic text.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Missing => "data_not_installed",
            Self::PackNotFound(_) => "pack_not_found",
            Self::Incompatible(_) => "incompatible_data",
            Self::Closed => "closed_geocoder",
            Self::Input(_) => "invalid_input",
            Self::ResourceLimit(_) => "resource_limit",
            Self::Internal(_) => "internal_error",
            _ => "corrupt_pack",
        }
    }
    /// The row of [`KINDS`] for this failure.
    #[must_use]
    pub fn kind(&self) -> &'static Kind {
        kind(self.code())
    }
    /// Command-line exit status for this failure.
    #[must_use]
    pub fn exit_code(&self) -> i32 {
        self.kind().exit
    }
}
/// One failure kind as every host presents it.
#[derive(Debug, PartialEq, Eq)]
pub struct Kind {
    /// Stable machine-readable code.
    pub code: &'static str,
    /// Command-line exit status.
    pub exit: i32,
    /// Class raised by the Python (`thereabouts.errors`) and Node bindings.
    pub class: &'static str,
}
/// The single table from failure code to exit status and binding class. The Python
/// and WASM bindings map through it; their tests check every row has its class.
pub const KINDS: &[Kind] = &[
    Kind {
        code: "data_not_installed",
        exit: 3,
        class: "DataNotInstalledError",
    },
    Kind {
        code: "pack_not_found",
        exit: 4,
        class: "PackNotFoundError",
    },
    Kind {
        code: "incompatible_data",
        exit: 4,
        class: "IncompatibleDataError",
    },
    Kind {
        code: "corrupt_pack",
        exit: 4,
        class: "CorruptPackError",
    },
    Kind {
        code: "closed_geocoder",
        exit: 4,
        class: "ClosedGeocoderError",
    },
    Kind {
        code: "invalid_input",
        exit: 2,
        class: "InvalidInputError",
    },
    Kind {
        code: "resource_limit",
        exit: 6,
        class: "ResourceLimitError",
    },
    Kind {
        code: "internal_error",
        exit: 70,
        class: "InternalError",
    },
    Kind {
        code: "writer_input_error",
        exit: 2,
        class: "WriterInputError",
    },
    Kind {
        code: "writer_error",
        exit: 4,
        class: "WriterError",
    },
];
/// Look up a code; an unknown code is treated as pack corruption, as before.
#[must_use]
pub fn kind(code: &str) -> &'static Kind {
    KINDS
        .iter()
        .find(|k| k.code == code)
        .or_else(|| KINDS.iter().find(|k| k.code == "corrupt_pack"))
        .unwrap_or(&CORRUPT)
}
const CORRUPT: Kind = Kind {
    code: "corrupt_pack",
    exit: 4,
    class: "CorruptPackError",
};
/// A poisoned lock means another thread panicked: a bug, never pack damage.
pub fn poisoned<T>(what: &str) -> impl FnOnce(T) -> Error + '_ {
    move |_| Error::Internal(format!("poisoned {what}"))
}
impl From<std::io::Error> for Error {
    fn from(error: std::io::Error) -> Self {
        if is_file_limit(&error) {
            Self::ResourceLimit(file_limit(&error))
        } else {
            Self::Io(error)
        }
    }
}
/// `EMFILE`/`ENFILE` (`ERROR_TOO_MANY_OPEN_FILES` on Windows): the descriptor table is full.
#[must_use]
pub fn is_file_limit(error: &std::io::Error) -> bool {
    #[cfg(windows)]
    const CODES: [i32; 1] = [4];
    #[cfg(not(windows))]
    const CODES: [i32; 2] = [23, 24];
    error
        .raw_os_error()
        .is_some_and(|code| CODES.contains(&code))
}
/// One diagnostic for every host: name the limit, never suggest reinstalling data.
#[must_use]
pub fn file_limit(detail: &impl std::fmt::Display) -> String {
    format!("Too many open files ({detail}); raise the process open-file limit (ulimit -n)")
}
/// Core operations use one error domain across language bindings.
pub type Result<T> = std::result::Result<T, Error>;
/// Reject invalid bytes with a stable integrity error.
pub fn ensure(valid: bool, message: &str) -> Result<()> {
    if valid {
        Ok(())
    } else {
        Err(Error::Corrupt(message.into()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stable_missing_data_message() {
        assert_eq!(Error::Missing.to_string(), "thereabouts data install core");
        assert_eq!(Error::Missing.code(), "data_not_installed");
        assert_eq!(Error::Closed.code(), "closed_geocoder");
    }
    #[test]
    #[cfg(not(windows))]
    fn descriptor_exhaustion_is_a_resource_limit_not_corruption() {
        for code in [23, 24] {
            let error = Error::from(std::io::Error::from_raw_os_error(code));
            assert_eq!(error.code(), "resource_limit");
            assert!(error.to_string().contains("ulimit -n"));
        }
        let missing = Error::from(std::io::Error::from(std::io::ErrorKind::NotFound));
        assert_eq!(missing.code(), "corrupt_pack");
    }
    #[test]
    fn every_error_has_one_table_row() {
        let errors = [
            Error::Missing,
            Error::PackNotFound("x".into()),
            Error::Incompatible(String::new()),
            Error::Corrupt(String::new()),
            Error::Closed,
            Error::Input(String::new()),
            Error::ResourceLimit(String::new()),
            Error::Internal(String::new()),
            Error::Io(std::io::Error::other("x")),
        ];
        for error in errors {
            assert_eq!(error.kind().code, error.code());
        }
        assert_eq!(kind("invalid_input").class, "InvalidInputError");
        assert_eq!(kind("invalid_input").exit, 2);
        assert_eq!(kind("internal_error").exit, 70);
        assert_eq!(kind("unknown").code, "corrupt_pack");
        let codes = KINDS
            .iter()
            .map(|k| k.code)
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(codes.len(), KINDS.len());
    }
    #[test]
    fn poisoned_locks_are_internal_errors() {
        let lock = std::sync::Arc::new(std::sync::Mutex::new(()));
        let held = std::sync::Arc::clone(&lock);
        let _ = std::thread::spawn(move || {
            let _guard = held.lock();
            panic!("poison the lock");
        })
        .join();
        let error = lock
            .lock()
            .map(|_| ())
            .map_err(poisoned("test lock"))
            .unwrap_err();
        assert_eq!(error.code(), "internal_error");
        assert_eq!(error.exit_code(), 70);
        assert!(error.to_string().contains("please report it"), "{error}");
    }
}

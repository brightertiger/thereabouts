//! Bounded multi-row SQLite inserts inside the caller's existing transaction.
use crate::{Result, error::ensure};
use rusqlite::{Connection, params_from_iter, types::Value};

/// At most 768 bindings for our three-column rows, below SQLite's old 999 limit.
const INSERT_ROWS: usize = 256;
// Flush text payloads at 1/16 of the SQLite cache rather than buffering 256 huge rows.
const INSERT_BYTES: usize = 1024 * 1024;
pub(crate) struct Inserts<'a> {
    db: &'a Connection,
    prefix: &'static str,
    columns: usize,
    values: Vec<Value>,
    bytes: usize,
}
impl<'a> Inserts<'a> {
    pub(crate) fn new(db: &'a Connection, prefix: &'static str, columns: usize) -> Self {
        Self {
            db,
            prefix,
            columns,
            values: Vec::with_capacity(INSERT_ROWS * columns),
            bytes: 0,
        }
    }
    pub(crate) fn push<const N: usize>(&mut self, row: [Value; N]) -> Result<()> {
        ensure(N == self.columns, "Insert arity mismatch")?;
        let bytes = row
            .iter()
            .map(|v| {
                size_of::<Value>()
                    + match v {
                        Value::Text(text) => text.len(),
                        Value::Blob(bytes) => bytes.len(),
                        _ => 0,
                    }
            })
            .sum::<usize>();
        ensure(
            bytes <= crate::MEMORY_BUDGET_BYTES / 4,
            "SQL row exceeds admission budget",
        )?;
        if self.bytes + bytes > INSERT_BYTES {
            self.flush()?;
        }
        self.bytes += bytes;
        self.values.extend(row);
        if self.values.len() >= INSERT_ROWS * self.columns || self.bytes >= INSERT_BYTES {
            self.flush()?;
        }
        Ok(())
    }
    pub(crate) fn flush(&mut self) -> Result<()> {
        if self.values.is_empty() {
            return Ok(());
        }
        let placeholders = format!("({})", vec!["?"; self.columns].join(","));
        let sql = format!(
            "{} VALUES {}",
            self.prefix,
            vec![placeholders; self.values.len() / self.columns].join(",")
        );
        self.db
            .prepare_cached(&sql)?
            .execute(params_from_iter(&self.values))?;
        self.values.clear();
        self.bytes = 0;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn batch_boundaries_preserve_rows_and_nulls_in_one_transaction() {
        let db = Connection::open_in_memory().unwrap();
        db.execute_batch("CREATE TABLE sample(id INTEGER PRIMARY KEY,value TEXT); BEGIN")
            .unwrap();
        let mut inserts = Inserts::new(&db, "INSERT INTO sample", 2);
        for i in 0..513 {
            inserts
                .push([
                    Value::Integer(i),
                    if i % 2 == 0 {
                        Value::Null
                    } else {
                        Value::Text("東京".into())
                    },
                ])
                .unwrap();
        }
        inserts.flush().unwrap();
        db.execute_batch("COMMIT").unwrap();
        let counts: (u32, u32) = db
            .query_row("SELECT count(*),count(value) FROM sample", [], |row| {
                Ok((row.get(0)?, row.get(1)?))
            })
            .unwrap();
        assert_eq!(counts, (513, 256));
    }
}

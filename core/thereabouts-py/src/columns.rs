//! Fixed-width output buffers are filled while detached, one result at a time.
use numpy::{PyArray1, PyReadonlyArray1};
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use std::{collections::HashMap, sync::Arc};
use thereabouts_core::{Error, Result, format::Pack, result::LookupResult};

type TextColumn = (&'static str, fn(&LookupResult) -> Option<&str>);
type FloatColumn = (&'static str, fn(&LookupResult) -> Option<f64>);
const TEXT_COLUMNS: [TextColumn; 15] = [
    ("status", |r| Some(r.status.as_str())),
    ("kind", |r| Some(r.kind.as_str())),
    ("match", |r| {
        r.r#match.map(thereabouts_core::result::Match::as_str)
    }),
    ("country_code", |r| {
        r.country.as_ref().map(|v| v.code.as_str())
    }),
    ("country_code3", |r| r.country.as_ref()?.code3.as_deref()),
    ("country_name", |r| {
        r.country.as_ref().map(|v| v.name.as_str())
    }),
    ("state_code", |r| r.state.as_ref()?.code.as_deref()),
    ("state_name", |r| r.state.as_ref().map(|v| v.name.as_str())),
    ("city_id", |r| r.city.as_ref().map(|v| v.id.as_str())),
    ("city_name", |r| r.city.as_ref().map(|v| v.name.as_str())),
    ("city_name_en", |r| r.city.as_ref()?.name_en.as_deref()),
    ("city_kind", |r| r.city.as_ref().map(|v| v.kind.as_str())),
    ("timezone", |r| r.timezone.as_deref()),
    ("cell", |r| r.cell.as_deref()),
    ("rank_basis", |r| r.rank_basis.as_deref()),
];

const FLOAT_COLUMNS: [FloatColumn; 6] = [
    ("point_lat", |r| r.point.as_ref().map(|p| p.lat)),
    ("point_lon", |r| r.point.as_ref().map(|p| p.lon)),
    ("city_point_lat", |r| {
        r.city.as_ref()?.point.as_ref().map(|p| p.lat)
    }),
    ("city_point_lon", |r| {
        r.city.as_ref()?.point.as_ref().map(|p| p.lon)
    }),
    ("distance_band_greater_than_km", |r| {
        r.distance_band.as_ref().map(|b| b.greater_than_km)
    }),
    ("distance_band_at_most_km", |r| {
        r.distance_band.as_ref().map(|b| b.at_most_km)
    }),
];

struct Dictionary {
    codes: Vec<i32>,
    categories: Vec<String>,
    index: HashMap<String, i32>,
}
impl Dictionary {
    fn new(rows: usize) -> Self {
        Self {
            codes: Vec::with_capacity(rows),
            categories: vec![],
            index: HashMap::new(),
        }
    }
    fn push(&mut self, value: Option<&str>) -> Result<()> {
        let code = if let Some(value) = value {
            if let Some(code) = self.index.get(value) {
                *code
            } else {
                let code = i32::try_from(self.categories.len())
                    .map_err(|_| Error::Input("Too many string categories".into()))?;
                self.index.insert(value.into(), code);
                self.categories.push(value.into());
                code
            }
        } else {
            -1
        };
        self.codes.push(code);
        Ok(())
    }
}
struct Nullable<T> {
    values: Vec<T>,
    valid: Vec<bool>,
}
impl<T> Nullable<T> {
    fn new(rows: usize) -> Self {
        Self {
            values: Vec::with_capacity(rows),
            valid: Vec::with_capacity(rows),
        }
    }
    fn push(&mut self, value: Option<T>, null: T) {
        self.valid.push(value.is_some());
        self.values.push(value.unwrap_or(null));
    }
}
struct Columns {
    text: Vec<Dictionary>,
    floats: Vec<Nullable<f64>>,
    population: Nullable<u32>,
}
impl Columns {
    fn fill(pack: &Pack, lat: Vec<f64>, lon: Vec<f64>) -> Result<Self> {
        let count = lat.len();
        let mut columns = Self {
            text: TEXT_COLUMNS
                .iter()
                .map(|_| Dictionary::new(count))
                .collect(),
            floats: FLOAT_COLUMNS.iter().map(|_| Nullable::new(count)).collect(),
            population: Nullable::new(count),
        };
        for (lat, lon) in lat.into_iter().zip(lon) {
            let row = pack.reverse(lat, lon, false)?;
            for (column, (_, get)) in columns.text.iter_mut().zip(TEXT_COLUMNS) {
                column.push(get(&row))?;
            }
            for (column, (_, get)) in columns.floats.iter_mut().zip(FLOAT_COLUMNS) {
                column.push(get(&row), f64::NAN);
            }
            columns
                .population
                .push(row.city.as_ref().and_then(|city| city.population), 0);
        }
        Ok(columns)
    }
}
pub fn reverse<'py>(
    py: Python<'py>,
    pack: &Arc<Pack>,
    lat: &PyReadonlyArray1<'py, f64>,
    lon: &PyReadonlyArray1<'py, f64>,
) -> PyResult<Bound<'py, PyDict>> {
    // Own strided inputs before detaching: concurrent Python mutation cannot race a borrow.
    let lat: Vec<_> = lat.as_array().iter().copied().collect();
    let lon: Vec<_> = lon.as_array().iter().copied().collect();
    if lat.len() != lon.len() {
        return Err(PyValueError::new_err("lat and lon must have equal lengths"));
    }
    let columns = py
        .detach(|| Columns::fill(pack, lat, lon))
        .map_err(|e| crate::error(py, &e))?;
    let dict = PyDict::new(py);
    for ((name, _), column) in TEXT_COLUMNS.into_iter().zip(columns.text) {
        dict.set_item(name, PyArray1::from_vec(py, column.codes))?;
        let categories: Vec<Py<PyAny>> = column
            .categories
            .into_iter()
            .map(|s| Ok(s.into_pyobject(py)?.into_any().unbind()))
            .collect::<PyResult<_>>()?;
        dict.set_item(
            format!("{name}_categories"),
            PyArray1::from_vec(py, categories),
        )?;
    }
    for ((name, _), column) in FLOAT_COLUMNS.into_iter().zip(columns.floats) {
        dict.set_item(name, PyArray1::from_vec(py, column.values))?;
        dict.set_item(
            format!("{name}_valid"),
            PyArray1::from_vec(py, column.valid),
        )?;
    }
    dict.set_item(
        "city_population",
        PyArray1::from_vec(py, columns.population.values),
    )?;
    dict.set_item(
        "city_population_valid",
        PyArray1::from_vec(py, columns.population.valid),
    )?;
    Ok(dict)
}

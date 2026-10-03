//! Native batch execution owns input copies before releasing the GIL.
use numpy::{PyArray1, PyReadonlyArray1};
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use std::sync::Arc;
use thereabouts_core::{format::Pack, result::LookupResult};

type TextColumn = (&'static str, fn(&LookupResult) -> Option<&str>);
type FloatColumn = (&'static str, fn(&LookupResult) -> Option<f64>);
const TEXT_COLUMNS: [TextColumn; 15] = [
    ("status", |r| Some(&r.status)),
    ("kind", |r| Some(&r.kind)),
    ("match", |r| r.r#match.as_deref()),
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

pub fn reverse<'py>(
    py: Python<'py>,
    pack: &Arc<Pack>,
    lat: &PyReadonlyArray1<'py, f64>,
    lon: &PyReadonlyArray1<'py, f64>,
) -> PyResult<Bound<'py, PyDict>> {
    // Copies also support strided arrays and prevent concurrent NumPy mutation
    // while detached from Python from creating an unsafe borrowed-buffer race.
    let lat: Vec<_> = lat.as_array().iter().copied().collect();
    let lon: Vec<_> = lon.as_array().iter().copied().collect();
    if lat.len() != lon.len() {
        return Err(PyValueError::new_err("lat and lon must have equal lengths"));
    }
    let rows: Vec<_> = py
        .detach(|| {
            lat.into_iter()
                .zip(lon)
                .map(|(a, b)| pack.reverse(a, b, false))
                .collect::<thereabouts_core::Result<Vec<_>>>()
        })
        .map_err(|e| crate::error(py, &e))?;
    let dict = PyDict::new(py);
    for (name, get) in TEXT_COLUMNS {
        let values: Vec<Py<PyAny>> = rows
            .iter()
            .map(|r| {
                get(r).map_or_else(
                    || Ok(py.None()),
                    |s| Ok(s.into_pyobject(py)?.into_any().unbind()),
                )
            })
            .collect::<PyResult<_>>()?;
        dict.set_item(name, PyArray1::from_vec(py, values))?;
    }
    let floats: [FloatColumn; 5] = [
        ("point_lat", |r| r.point.as_ref().map(|p| p.lat)),
        ("point_lon", |r| r.point.as_ref().map(|p| p.lon)),
        ("city_point_lat", |r| {
            r.city.as_ref()?.point.as_ref().map(|p| p.lat)
        }),
        ("city_point_lon", |r| {
            r.city.as_ref()?.point.as_ref().map(|p| p.lon)
        }),
        ("distance_km", |r| r.distance_km),
    ];
    for (name, get) in floats {
        dict.set_item(
            name,
            PyArray1::from_vec(
                py,
                rows.iter().map(|r| get(r).unwrap_or(f64::NAN)).collect(),
            ),
        )?;
        dict.set_item(
            format!("{name}_valid"),
            PyArray1::from_vec(py, rows.iter().map(|r| get(r).is_some()).collect()),
        )?;
    }
    dict.set_item(
        "city_population",
        PyArray1::from_vec(
            py,
            rows.iter()
                .map(|r| r.city.as_ref().and_then(|c| c.population).unwrap_or(0))
                .collect(),
        ),
    )?;
    dict.set_item(
        "city_population_valid",
        PyArray1::from_vec(
            py,
            rows.iter()
                .map(|r| r.city.as_ref().and_then(|c| c.population).is_some())
                .collect(),
        ),
    )?;
    let candidates: Vec<_> = rows
        .iter()
        .map(|r| {
            crate::value_to_python(
                py,
                &serde_json::to_value(&r.candidates)
                    .map_err(|e| PyValueError::new_err(e.to_string()))?,
            )
        })
        .collect::<PyResult<_>>()?;
    dict.set_item("candidates", PyArray1::from_vec(py, candidates))?;
    Ok(dict)
}

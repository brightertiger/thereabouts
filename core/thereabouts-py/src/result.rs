//! Scalar dictionaries are constructed directly from the typed result.
use pyo3::{
    prelude::*,
    types::{PyDict, PyList},
};
use thereabouts_core::result::{City, Country, Evidence, LookupResult, Point, State};

fn point<'py>(py: Python<'py>, value: &Point) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("lat", value.lat)?;
    dict.set_item("lon", value.lon)?;
    Ok(dict)
}
fn country<'py>(py: Python<'py>, value: &Country) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("code", &value.code)?;
    dict.set_item("code3", &value.code3)?;
    dict.set_item("name", &value.name)?;
    Ok(dict)
}
fn state<'py>(py: Python<'py>, value: &State) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("code", &value.code)?;
    dict.set_item("name", &value.name)?;
    Ok(dict)
}
fn city<'py>(py: Python<'py>, value: &City) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("id", &value.id)?;
    dict.set_item("name", &value.name)?;
    dict.set_item("name_en", &value.name_en)?;
    dict.set_item("kind", &value.kind)?;
    dict.set_item("population", value.population)?;
    dict.set_item(
        "point",
        value.point.as_ref().map(|v| point(py, v)).transpose()?,
    )?;
    Ok(dict)
}
fn evidence<'py>(py: Python<'py>, value: &Evidence) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("stored_cell", &value.stored_cell)?;
    dict.set_item("country_id", &value.country_id)?;
    dict.set_item("state_id", &value.state_id)?;
    dict.set_item("city_id", &value.city_id)?;
    dict.set_item("city_method", &value.city_method)?;
    dict.set_item("land_method", &value.land_method)?;
    dict.set_item("reason", &value.reason)?;
    dict.set_item("timezones", &value.timezones)?;
    dict.set_item(
        "source_ids",
        value
            .source_ids
            .as_ref()
            .map(|v| crate::value_to_python(py, v))
            .transpose()?,
    )?;
    Ok(dict)
}
pub(crate) fn encode(py: Python<'_>, value: &LookupResult) -> PyResult<Py<PyAny>> {
    let dict = PyDict::new(py);
    dict.set_item("status", value.status.as_str())?;
    dict.set_item("kind", value.kind.as_str())?;
    dict.set_item(
        "match",
        value.r#match.map(thereabouts_core::result::Match::as_str),
    )?;
    dict.set_item(
        "country",
        value.country.as_ref().map(|v| country(py, v)).transpose()?,
    )?;
    dict.set_item(
        "state",
        value.state.as_ref().map(|v| state(py, v)).transpose()?,
    )?;
    dict.set_item(
        "city",
        value.city.as_ref().map(|v| city(py, v)).transpose()?,
    )?;
    dict.set_item(
        "point",
        value.point.as_ref().map(|v| point(py, v)).transpose()?,
    )?;
    dict.set_item("timezone", &value.timezone)?;
    dict.set_item("cell", &value.cell)?;
    let band = value
        .distance_band
        .as_ref()
        .map(|band| -> PyResult<_> {
            let dict = PyDict::new(py);
            dict.set_item("greater_than_km", band.greater_than_km)?;
            dict.set_item("at_most_km", band.at_most_km)?;
            Ok(dict)
        })
        .transpose()?;
    dict.set_item("distance_band", band)?;
    let candidates = PyList::empty(py);
    for candidate in &value.candidates {
        candidates.append(encode(py, candidate)?)?;
    }
    dict.set_item("candidates", candidates)?;
    dict.set_item("rank_basis", &value.rank_basis)?;
    if let Some(hint) = &value.hint {
        dict.set_item("hint", hint)?;
    }
    if let Some(value) = &value.evidence {
        dict.set_item("evidence", evidence(py, value)?)?;
    }
    Ok(dict.into_any().unbind())
}

/// Keep legacy omission rules and append only the new serialized query object.
pub(crate) fn encode_point(
    py: Python<'_>,
    value: &thereabouts_core::coords::PointResult,
) -> PyResult<Py<PyAny>> {
    let result = encode(py, &value.result)?;
    result
        .bind(py)
        .downcast::<PyDict>()?
        .set_item("query", encode_query(py, &value.query)?)?;
    Ok(result)
}

pub(crate) fn encode_query(
    py: Python<'_>,
    value: &thereabouts_core::coords::QueryMetadata,
) -> PyResult<Py<PyAny>> {
    let value = serde_json::to_value(value)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    crate::value_to_python(py, &value)
}

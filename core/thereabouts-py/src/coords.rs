//! Coordinate marshalling only; parsing, normalization and domain checks live in core.
use numpy::{PyReadonlyArray1, PyUntypedArray};
use pyo3::{
    exceptions::{PyTypeError, PyValueError},
    prelude::*,
    types::PyDict,
};
use std::{collections::HashMap, sync::Arc};
use thereabouts_core::{
    coords::{self, CoordError, Ecef, Frame, Geodetic, Origin, Point, Uncertainty},
    format::Pack,
};

pub(crate) fn reverse(
    py: Python<'_>,
    pack: &Pack,
    request: &str,
    evidence: bool,
) -> PyResult<Py<PyAny>> {
    let result = match serde_json::from_str(request) {
        Ok(value) => {
            coords::reverse_value(pack, &value, evidence).map_err(|e| crate::error(py, &e))?
        }
        Err(_) => coords::invalid_result(
            None,
            &CoordError::InvalidSyntax {
                frame: "json".into(),
            },
        ),
    };
    crate::result::encode_point(py, &result)
}

struct Inputs {
    values: HashMap<String, Vec<f64>>,
    count: usize,
}
impl Inputs {
    fn copy(py: Python<'_>, columns: &Bound<'_, PyDict>, frame: &str) -> PyResult<Self> {
        let required: &[&str] = match frame {
            "geodetic" | "latlon" | "lla" | "llh" => &["lat", "lon"],
            "ecef" => &["x", "y", "z"],
            "enu" => &["e", "n", "u"],
            "ned" => &["n", "e", "d"],
            _ => {
                return Err(PyValueError::new_err(
                    "Numeric columns support geodetic/ECEF/ENU/NED; use reverse_points for other frames, datums or heterogeneous origins",
                ));
            }
        };
        let geodetic = matches!(frame, "geodetic" | "latlon" | "lla" | "llh");
        let numpy = py.import("numpy")?;
        let mut values = HashMap::new();
        let mut count = None;
        for (name, value) in columns.iter() {
            let name: String = name.extract()?;
            if !(required.contains(&name.as_str())
                || ["accuracy_m", "hdop", "vdop"].contains(&name.as_str())
                || (geodetic && name == "height"))
            {
                return Err(PyValueError::new_err(format!(
                    "Unsupported {frame} column {name}; use reverse_points for other datums or components"
                )));
            }
            let _ = value.downcast::<PyUntypedArray>()?;
            if value.getattr("ndim")?.extract::<usize>()? != 1 {
                return Err(PyValueError::new_err(
                    "Coordinate columns must be one-dimensional",
                ));
            }
            let kind: String = value.getattr("dtype")?.getattr("kind")?.extract()?;
            if !["i", "u", "f"].contains(&kind.as_str()) {
                return Err(PyTypeError::new_err(
                    "Coordinate columns must have numeric, non-boolean dtypes",
                ));
            }
            let array = numpy.call_method1("asarray", (&value, numpy.getattr("float64")?))?;
            let array: PyReadonlyArray1<'_, f64> = array.extract()?;
            // Copy even contiguous arrays before detaching: no Python-owned borrow escapes.
            let owned: Vec<f64> = array.as_array().iter().copied().collect();
            if count.is_some_and(|n| n != owned.len()) {
                return Err(PyValueError::new_err(
                    "Coordinate columns must have equal lengths",
                ));
            }
            count = Some(owned.len());
            values.insert(name, owned);
        }
        for name in required {
            if !values.contains_key(*name) {
                return Err(PyValueError::new_err(format!(
                    "Missing required column {name}"
                )));
            }
        }
        Ok(Self {
            values,
            count: count.unwrap_or(0),
        })
    }
    fn get(&self, name: &str, index: usize) -> Option<f64> {
        self.values.get(name)?.get(index).copied()
    }
    fn point(&self, frame: &str, origin: Option<&Origin>, index: usize) -> Point {
        // Required lengths/keys were checked before detach; core validates all numeric values.
        let get = |name| self.get(name, index).unwrap_or(f64::NAN);
        let frame = match (frame, origin) {
            ("ecef", _) => Frame::Ecef(Ecef {
                x: get("x"),
                y: get("y"),
                z: get("z"),
            }),
            ("enu", Some(origin)) => Frame::Enu {
                e: get("e"),
                n: get("n"),
                u: get("u"),
                origin: origin.clone(),
            },
            ("ned", Some(origin)) => Frame::Ned {
                n: get("n"),
                e: get("e"),
                d: get("d"),
                origin: origin.clone(),
            },
            _ => Frame::Geodetic(Geodetic {
                lat: get("lat"),
                lon: get("lon"),
                height: self.get("height", index),
                height_datum: self.get("height", index).map(|_| "ellipsoid".into()),
                geoid_separation: None,
            }),
        };
        Point {
            frame,
            uncertainty: Uncertainty {
                accuracy_m: self.get("accuracy_m", index),
                hdop: self.get("hdop", index),
                vdop: self.get("vdop", index),
            },
        }
    }
}

fn origin(request: Option<&str>) -> Result<Origin, CoordError> {
    let value = request
        .map(serde_json::from_str::<serde_json::Value>)
        .transpose()
        .map_err(|_| CoordError::InvalidSyntax {
            frame: "json".into(),
        })?;
    // Use the one shared wire parser, including its origin restrictions.
    let point = coords::parse_point(&serde_json::json!({
        "frame": "enu", "e": 0, "n": 0, "u": 0, "origin": value
    }))?;
    match point.frame {
        Frame::Enu { origin, .. } => Ok(origin),
        _ => unreachable!("shared parser returns the explicitly requested ENU frame"),
    }
}

pub(crate) fn columns<'py>(
    py: Python<'py>,
    pack: &Arc<Pack>,
    columns: &Bound<'py, PyDict>,
    frame: &str,
    origin_json: Option<&str>,
) -> PyResult<Bound<'py, PyDict>> {
    let inputs = Inputs::copy(py, columns, frame)?;
    let local = matches!(frame, "enu" | "ned");
    if !local && origin_json.is_some() {
        return Err(PyValueError::new_err(
            "origin is only accepted with ENU/NED columns",
        ));
    }
    let origin = if local {
        origin(origin_json).map(Some)
    } else {
        Ok(None)
    };
    crate::columns::points(py, inputs.count, |index| {
        let mut result = match &origin {
            Ok(origin) => {
                coords::reverse_point(pack, &inputs.point(frame, origin.as_ref(), index), false)?
            }
            Err(error) => coords::invalid_result(Some(frame), error),
        };
        result.query.declared_frame = Some(frame.into());
        Ok(result)
    })
}

//! Native coordinate acceptance: independent fixtures, seeded properties and legacy parity.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::float_cmp,
    clippy::unreadable_literal,
    clippy::many_single_char_names,
    clippy::similar_names
)]
use serde_json::{Value, json};
use thereabouts_core::coords::*;
fn geodetic(lat: f64, lon: f64, height: Option<f64>) -> Geodetic {
    Geodetic {
        lat,
        lon,
        height,
        height_datum: height.map(|_| "ellipsoid".into()),
        geoid_separation: None,
    }
}
fn normalized(v: &Value) -> NormalizedPoint {
    normalize(&parse_point(v).unwrap_or_else(|e| panic!("{v}: {e}"))).unwrap()
}
fn point(frame: Frame) -> Point {
    Point {
        frame,
        uncertainty: Uncertainty::default(),
    }
}
fn close(a: f64, b: f64, tolerance: f64) {
    assert!(
        (a - b).abs() <= tolerance,
        "{a:.16} != {b:.16}, delta={} tolerance={tolerance}",
        (a - b).abs()
    );
}
fn longitude(a: f64, b: f64, t: f64) {
    close((a - b + 180.0).rem_euclid(360.0) - 180.0, 0.0, t);
}
fn check_subset(actual: &Value, expected: &Value, path: &str, tolerances: &Value, id: &str) {
    match expected {
        Value::Object(fields) => {
            for (key, value) in fields {
                let p = if path.is_empty() {
                    key.clone()
                } else {
                    format!("{path}.{key}")
                };
                check_subset(&actual[key], value, &p, tolerances, id);
            }
        }
        Value::Array(values) => {
            assert_eq!(
                actual.as_array().unwrap().len(),
                values.len(),
                "{id} {path}"
            );
            for (a, e) in actual.as_array().unwrap().iter().zip(values) {
                check_subset(a, e, &format!("{path}.*"), tolerances, id);
            }
        }
        Value::Number(n) => {
            let a = actual.as_f64().unwrap();
            let e = n.as_f64().unwrap();
            let t = tolerances[path].as_f64().unwrap_or(0.0);
            let delta = if path.rsplit('.').next() == Some("lon") {
                (a - e + 180.0).rem_euclid(360.0) - 180.0
            } else {
                a - e
            };
            assert!(
                delta.abs() <= t,
                "{id} {path}: {a:.16} != {e:.16}, delta={delta}, tolerance={t}"
            );
        }
        _ => assert_eq!(actual, expected, "{id} {path}"),
    }
}
#[test]
fn shared_independent_vectors() {
    let vectors: Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/coordinates/vectors.json"
    ))
    .unwrap();
    for c in vectors["cases"].as_array().unwrap() {
        let id = c["id"].as_str().unwrap();
        if let Some(code) = c["expected"]["error"].as_str() {
            assert_eq!(parse_point(&c["input"]).unwrap_err().code(), code, "{id}");
            continue;
        }
        let parsed = parse_point(&c["input"]).unwrap_or_else(|e| panic!("{id}: {e}"));
        let p = normalize(&parsed).unwrap();
        let mut actual = serde_json::to_value(&p).unwrap();
        actual["normalized"] = actual["point"].clone();
        check_subset(&actual, &c["expected"], "", &c["tolerance"], id);
        let roundtrip = serde_json::to_value(&parsed).unwrap();
        assert_eq!(
            parse_point(&roundtrip).unwrap(),
            parsed,
            "serialization {id}: {roundtrip}"
        );
        if let Some(e) = c.get("forward_ecef") {
            let actual = geodetic_to_ecef(&p.point).unwrap();
            for (field, value) in [("x", actual.x), ("y", actual.y), ("z", actual.z)] {
                close(
                    value,
                    e[field].as_f64().unwrap(),
                    e["tolerance_m"].as_f64().unwrap(),
                );
            }
        }
        if let Some(e) = c.get("forward_utm") {
            let actual = geodetic_to_utm(
                &p.point,
                Some(u8::try_from(e["zone"].as_u64().unwrap()).unwrap()),
            )
            .unwrap();
            close(actual.easting, e["easting"].as_f64().unwrap(), 0.001);
            close(actual.northing, e["northing"].as_f64().unwrap(), 0.001);
        }
    }
}
// A deterministic local PRNG avoids dependency/runtime entropy and fixes all seeds.
struct Rng(u64);
impl Rng {
    fn sample(&mut self, lo: f64, hi: f64) -> f64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        let bits = u32::try_from(self.0 >> 32).unwrap();
        lo + (hi - lo) * f64::from(bits) / f64::from(u32::MAX)
    }
}
#[test]
fn seeded_ecef_residual_height_and_angles() {
    let mut rng = Rng(0x5eed_c0de);
    for i in 0..4000 {
        let h = if i % 3 == 0 {
            rng.sample(-10_000.0, 1000.0)
        } else {
            rng.sample(0.0, 100_000_000.0)
        };
        let p = geodetic(
            rng.sample(-89.9999, 89.9999),
            rng.sample(-180.0, 180.0),
            Some(h),
        );
        let xyz = geodetic_to_ecef(&p).unwrap();
        let q = ecef_to_geodetic(&xyz).unwrap();
        let check = geodetic_to_ecef(&q).unwrap();
        assert!(
            (xyz.x - check.x)
                .hypot(xyz.y - check.y)
                .hypot(xyz.z - check.z)
                < 0.001
        );
        close(q.height.unwrap(), h, 0.001);
        close(q.lat, p.lat, 1e-8);
        longitude(q.lon, p.lon, 1e-8);
    }
    for lat in [-90.0, -89.999999999, 0.0, 89.999999999, 90.0] {
        for lon in [-180.0, 0.0, 180.0] {
            for h in [
                -10_000.0,
                0.0,
                400_000.0,
                20_200_000.0,
                35_786_000.0,
                100_000_000.0,
            ] {
                let xyz = geodetic_to_ecef(&geodetic(lat, lon, Some(h))).unwrap();
                let p = ecef_to_geodetic(&xyz).unwrap();
                close(p.lat, lat, 1e-8);
                close(p.height.unwrap(), h, 0.001);
                if lat.abs() == 90.0 {
                    assert_eq!(p.lon, 0.0);
                } else {
                    longitude(p.lon, lon, 1e-8);
                }
            }
        }
    }
}
#[test]
fn analytic_cartesian_basis_and_local_roundtrips() {
    let origin = Origin::Geodetic(geodetic(0.0, 0.0, Some(0.0)));
    assert_eq!(
        enu_to_ecef(10.0, 20.0, 30.0, &origin).unwrap(),
        Ecef {
            x: 6378167.0,
            y: 10.0,
            z: 20.0
        }
    );
    let mut rng = Rng(0xabc123);
    for _ in 0..1000 {
        let origin = Origin::Geodetic(geodetic(
            rng.sample(-90.0, 90.0),
            rng.sample(-180.0, 180.0),
            Some(rng.sample(-10000.0, 1000000.0)),
        ));
        let e = rng.sample(-1e7, 1e7);
        let n = rng.sample(-1e7, 1e7);
        let u = rng.sample(-1e7, 1e7);
        let xyz = enu_to_ecef(e, n, u, &origin).unwrap();
        let back = ecef_to_enu(&xyz, &origin).unwrap();
        for (a, b) in back.into_iter().zip([e, n, u]) {
            close(a, b, 1e-7);
        }
        let enu = normalize(&point(Frame::Enu {
            e,
            n,
            u,
            origin: origin.clone(),
        }))
        .unwrap();
        let ned = normalize(&point(Frame::Ned {
            n,
            e,
            d: -u,
            origin,
        }))
        .unwrap();
        assert_eq!(enu.point, ned.point);
    }
}
#[test]
fn origin_height_and_pole_policy() {
    let p = normalized(&json!({"frame":"enu","e":0,"n":0,"u":0,"origin":{"lat":0,"lon":0}}));
    assert_eq!(
        p.conversion,
        [
            "origin_height_assumed_zero",
            "origin_geodetic_to_ecef_wgs84",
            "enu_to_ecef_wgs84",
            "ecef_to_geodetic_wgs84"
        ]
    );
    assert_eq!(p.point.height, Some(0.0));
    let p = geodetic(12.0, 40.0, None);
    assert_eq!(
        geodetic_to_ecef(&p).unwrap_err(),
        CoordError::MissingEllipsoidalHeight
    );
    for lat in [-90.0, 90.0] {
        let a = enu_to_ecef(
            10.0,
            0.0,
            0.0,
            &Origin::Geodetic(geodetic(lat, 0.0, Some(0.0))),
        )
        .unwrap();
        let b = enu_to_ecef(
            10.0,
            0.0,
            0.0,
            &Origin::Geodetic(geodetic(lat, 90.0, Some(0.0))),
        )
        .unwrap();
        close(a.y, 10.0, 1e-10);
        close(b.x, -10.0, 1e-10);
        let origin = Origin::Ecef(Ecef {
            x: 0.0,
            y: 0.0,
            z: lat.signum() * 6356752.314245179,
        });
        assert_eq!(
            enu_to_ecef(0.0, 0.0, 0.0, &origin).unwrap_err(),
            CoordError::UndefinedPosition
        );
    }
    for xyz in [
        Ecef {
            x: 0.0,
            y: 0.0,
            z: 0.0,
        },
        Ecef {
            x: 1.0,
            y: 1.0,
            z: 1.0,
        },
    ] {
        assert_eq!(
            ecef_to_geodetic(&xyz).unwrap_err(),
            CoordError::UndefinedPosition
        );
    }
    for datum in ["unknown", "msl"] {
        let bad = json!({"frame":"enu","e":0,"n":0,"u":0,"origin":{"lat":0,"lon":0,"height":4,"height_datum":datum}});
        assert_eq!(
            parse_point(&bad).unwrap_err(),
            CoordError::MissingEllipsoidalHeight
        );
    }
}
#[test]
fn seeded_utm_and_zone_selection() {
    let mut rng = Rng(0x1234abcd);
    for zone in 1..=60 {
        for _ in 0..20 {
            let p = geodetic(
                rng.sample(-79.99, 83.99),
                f64::from(zone) * 6.0 - 183.0 + rng.sample(-3.0, 3.0),
                None,
            );
            let utm = geodetic_to_utm(&p, Some(zone)).unwrap();
            let q = utm_to_geodetic(&utm).unwrap();
            close(q.lat, p.lat, 1e-8);
            longitude(q.lon, p.lon, 1e-8);
            let back = geodetic_to_utm(&q, Some(zone)).unwrap();
            close(back.easting, utm.easting, 0.001);
            close(back.northing, utm.northing, 0.001);
        }
    }
    for (lat, lon, zone) in [
        (60.0, 6.0, 32),
        (78.0, 8.0, 31),
        (78.0, 10.0, 33),
        (78.0, 22.0, 35),
        (78.0, 34.0, 37),
        (0.0, -180.0, 1),
        (0.0, 180.0, 60),
    ] {
        assert_eq!(
            geodetic_to_utm(&geodetic(lat, lon, None), None)
                .unwrap()
                .zone,
            zone
        );
    }
    for lat in [-80.0, 84.0] {
        let utm = geodetic_to_utm(&geodetic(lat, 3.0, None), Some(31)).unwrap();
        close(utm_to_geodetic(&utm).unwrap().lat, lat, 1e-10);
    }
    for lat in [-80.0000001, 84.0000001] {
        assert!(geodetic_to_utm(&geodetic(lat, 3.0, None), None).is_err());
    }
    let explicit = geodetic_to_utm(&geodetic(60.0, 6.0, None), Some(31)).unwrap();
    assert_eq!(explicit.zone, 31);
}
#[test]
fn mgrs_intersection_precisions_and_invalid_squares() {
    // 31TDP spans the T/U boundary: its centre is in U, but its square intersects T.
    let p = normalized(&json!({"frame":"mgrs","value":"31TDP"}));
    assert!(p.point.lat > 48.0);
    assert_eq!(p.cell_extent.unwrap().grid_size_m, Some(100000.0));
    for code in [
        "31UDQ4825111932",
        "31udq 48251 11932",
        "ZAH0000000000",
        "BAN0000000000",
        "YZH",
        "AZN",
    ] {
        assert!(
            parse_point(&json!({"frame":"mgrs","value":code})).is_ok(),
            "{code}"
        );
    }
    for code in [
        "00UDQ",
        "61UDQ",
        "32XNA",
        "34XDA",
        "36XWA",
        "31UIQ",
        "31UDO",
        "31UAA",
        "31UDQ1",
        "31UDQ123456789012",
        "YAH",
        "ZRH",
        "AAA",
        "ZGA",
    ] {
        assert!(
            parse_point(&json!({"frame":"mgrs","value":code})).is_err(),
            "{code}"
        );
    }
}
#[test]
fn angular_cells_footprints_and_olc_recovery() {
    let p = normalized(&json!({"frame":"geohash","value":"u4pruydqqvj"}));
    let e = p.cell_extent.unwrap();
    assert_eq!(e.boundary.len(), 4);
    assert_eq!(e.half_lat_deg, Some(0.0000006705522537231445));
    assert_eq!(e.half_lon_deg, e.half_lat_deg);
    assert!(e.radius_m > 0.0);
    assert_eq!(p.uncertainty, Uncertainty::default());
    let full = normalized(&json!({"frame":"pluscode","value":"849VCWC8+Q9"}));
    let short = normalized(
        &json!({"frame":"pluscode","value":"CWC8+Q9","reference":{"lat":37.42,"lon":-122.08}}),
    );
    assert_eq!(full.point, short.point);
    assert_eq!(
        short.conversion,
        ["pluscode_recover_short", "pluscode_cell_center"]
    );
    for code in [
        "+",
        "849VCWC8+Q",
        "849V0WC8+",
        "849VCWC8+Q9WWWWWW",
        "849VCWC8Q9",
        "849VCWC8++Q9",
        "849V0000+Q9",
        "ZZZZZZZZ+ZZ",
    ] {
        assert!(
            parse_point(&json!({"frame":"pluscode","value":code})).is_err(),
            "{code}"
        );
    }
    for code in ["849VCW00+", "849VCWC8+", "849VCWC8+Q9W2345"] {
        // Six significant characters is a valid padded coarse code.
        assert!(
            parse_point(&json!({"frame":"pluscode","value":code})).is_ok(),
            "{code}"
        );
    }
}
#[test]
fn cell_identifiers_are_explicit_lossless_and_bounded() {
    for id in ["1", "3", "5", "7", "9", "b", "89c25"] {
        let parsed = normalized(&json!({"frame":"s2","cell":id}));
        let raw = u64::from_str_radix(id, 16).unwrap() << (4 * (16 - id.len()));
        let direct = normalize(&point(Frame::S2(CellId::Integer(raw)))).unwrap();
        assert_eq!(parsed, direct);
    }
    for id in [
        "",
        "0",
        "2",
        "c",
        "d",
        "ffffffffffffffff",
        "10000000000000000",
        "0x1",
    ] {
        assert!(
            parse_point(&json!({"frame":"s2","cell":id})).is_err(),
            "{id}"
        );
    }
    for id in ["881fb46625fffff", "801ffffffffffff", "8009fffffffffff"] {
        let parsed = normalized(&json!({"frame":"h3","cell":id}));
        let raw = u64::from_str_radix(id, 16).unwrap();
        assert_eq!(
            parsed,
            normalize(&point(Frame::H3(CellId::Integer(raw)))).unwrap()
        );
    }
}
fn nmea(body: &str) -> String {
    format!("${body}*{:02X}", body.bytes().fold(0_u8, |a, b| a ^ b))
}
#[test]
fn nmea_fix_units_checksum_and_uncertainty() {
    let body = "GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,";
    let value = nmea(body);
    assert!(value.ends_with("*47"));
    let p = normalized(
        &json!({"frame":"nmea","value":format!("{value}\r\n"),"uncertainty":{"hdop":0.9,"accuracy_m":10,"vdop":2}}),
    );
    close(p.point.height.unwrap(), 592.3, 1e-9);
    assert_eq!(p.source_height.as_ref().unwrap().datum, "msl");
    assert_eq!(p.uncertainty.accuracy_m, Some(10.0));
    assert_eq!(p.conversion, ["nmea_checksum_parse", "msl_plus_separation"]);
    assert!(matches!(
        parse_point(&json!({"frame":"nmea","value":value,"uncertainty":{"hdop":1}})),
        Err(CoordError::ConflictingFields { .. })
    ));
    let absent = nmea(&body.replace("46.9,M", " ,M").replace(' ', ""));
    let p = normalized(&json!({"frame":"nmea","value":absent}));
    assert_eq!(p.point.height, None);
    assert_eq!(p.point.height_datum, None);
    assert_eq!(p.source_height.unwrap().value_m, 545.4);
    for invalid in [
        value.replace("*47", "*00"),
        value.replace("*47", ""),
        format!("{value}0"),
        format!("{value}\n"),
    ] {
        assert_eq!(
            parse_point(&json!({"frame":"nmea","value":invalid})).unwrap_err(),
            CoordError::InvalidChecksum
        );
    }
    for talker in ["GP", "GN"] {
        for sentence in [
            format!("{talker}GGA,123519,4807.038,N,01131.000,E,0,08,0.9,545.4,M,46.9,M,,"),
            format!("{talker}RMC,123519,V,4807.038,N,01131.000,E,0,0,230394,,"),
            format!("{talker}GLL,4807.038,N,01131.000,E,123519,V"),
        ] {
            assert_eq!(
                parse_point(&json!({"frame":"nmea","value":nmea(&sentence)})).unwrap_err(),
                CoordError::NoFix
            );
        }
    }
    for invalid in [
        body.replace("545.4,M", "545.4,F"),
        body.replace("46.9,M", "46.9,F"),
        body.replace("4807.038", "4860.000"),
        body.replace("123519", "246000"),
        body.replace("0.9", "-0.9"),
    ] {
        assert!(parse_point(&json!({"frame":"nmea","value":nmea(&invalid)})).is_err());
    }
}
#[test]
fn strict_types_keys_recursion_and_typed_validation() {
    for v in [
        Value::Null,
        json!(false),
        json!([1, 2]),
        json!({"lat":true,"lon":0}),
        json!({"lat":"1","lon":0}),
        json!({"lat":null,"lon":0}),
        json!({"lat":0,"lon":0,"height":true}),
        json!({"lat":0,"lon":0,"uncertainty":{"hdop":"1"}}),
        json!({"lat":0,"lon":0,"uncertainty":{"covariance":0}}),
        json!({"lat":0,"lon":0,"origin":null}),
        json!({"frame":"enu","e":0,"n":0,"u":0,"origin":{"frame":"enu","e":0,"n":0,"u":0,"origin":{"lat":0,"lon":0}}}),
    ] {
        assert!(parse_point(&v).is_err(), "{v}");
    }
    for v in [
        json!({"lat":0,"lon":0,"height":null,"uncertainty":null}),
        json!({"lat":0,"lon":0,"height_datum":null,"geoid_separation":null}),
    ] {
        assert!(parse_point(&v).is_ok());
    }
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        for frame in [
            Frame::Geodetic(geodetic(value, 0.0, None)),
            Frame::Ecef(Ecef {
                x: value,
                y: 1.0,
                z: 1.0,
            }),
            Frame::GeoJson(vec![0.0, value]),
            Frame::Utm(Utm {
                zone: 31,
                hemisphere: Some(Hemisphere::North),
                band: None,
                easting: value,
                northing: 0.0,
            }),
        ] {
            assert!(matches!(
                normalize(&point(frame)),
                Err(CoordError::NonFinite { .. })
            ));
        }
        for u in [
            Uncertainty {
                accuracy_m: Some(value),
                ..Uncertainty::default()
            },
            Uncertainty {
                hdop: Some(value),
                ..Uncertainty::default()
            },
            Uncertainty {
                vdop: Some(value),
                ..Uncertainty::default()
            },
        ] {
            assert!(
                normalize(&Point {
                    frame: Frame::Geodetic(geodetic(0.0, 0.0, None)),
                    uncertainty: u
                })
                .is_err()
            );
        }
    }
    assert!(
        normalize(&point(Frame::Pluscode {
            value: "849VCWC8+Q9".into(),
            reference: Some(geodetic(91.0, 0.0, None))
        }))
        .is_err()
    );
    assert!(normalize(&point(Frame::Geodetic(geodetic(91.0, 0.0, None)))).is_err());
}
#[test]
fn text_axis_order_dimensionality_and_signs() {
    for v in [
        json!({"frame":"geojson","coordinates":[2,48]}),
        json!({"frame":"wkt","value":"point (2 48)"}),
    ] {
        let p = normalized(&v);
        assert_eq!(p.point.lat, 48.0);
        assert_eq!(p.point.lon, 2.0);
    }
    for v in [
        json!({"frame":"geojson","coordinates":[48,2]}),
        json!({"frame":"wkt","value":"POINT (48 2)"}),
    ] {
        let p = normalized(&v);
        assert_eq!(p.point.lat, 2.0);
        assert_eq!(p.point.lon, 48.0);
    }
    for code in [
        "POINT EMPTY",
        "POINT M (1 2 3)",
        "POINT ZM (1 2 3 4)",
        "LINESTRING(1 2,3 4)",
        "POINT(1,2)",
        "POINT(1 2) more",
        "POINT Z(1 2)",
        "POINT(1 2 3)",
        "POINT(NaN 2)",
    ] {
        assert!(
            parse_point(&json!({"frame":"wkt","value":code})).is_err(),
            "{code}"
        );
    }
    for v in [
        json!({"frame":"geojson","type":"Feature","coordinates":[1,2]}),
        json!({"frame":"geojson","coordinates":[1,2],"crs":{}}),
        json!({"frame":"geojson","coordinates":[1]}),
        json!({"frame":"geojson","coordinates":[1,2,3,4]}),
    ] {
        assert!(parse_point(&v).is_err());
    }
    for s in [
        "-48°N 2°E",
        "48°N 2°N",
        "48°N 2°E extra",
        "48 60 N, 2 E",
        "48 0 60 N, 2 E",
        "48°51°N 2°E",
        "48 N 2 E",
        "91°N 2°E",
    ] {
        assert!(
            parse_point(&json!({"frame":"dms","value":s})).is_err(),
            "{s}"
        );
    }
    let p = normalized(&json!({"frame":"dms","value":"-48°S -2°W"}));
    assert_eq!(p.point.lat, -48.0);
    assert_eq!(p.point.lon, -2.0);
}
#[test]
fn error_messages_and_invalid_metadata_are_stable() {
    for (e, message) in [
        (
            CoordError::UnsupportedFrame {
                frame: "crs:EPSG:4326".into(),
            },
            "Thereabouts does not transform arbitrary CRSs; use GeoReconcile crs: support or pyproj, then pass WGS84 geodetic coordinates",
        ),
        (
            CoordError::UnsupportedFrame {
                frame: "llv".into(),
            },
            "Choose frame enu or ned and supply an origin; llv does not define axis order",
        ),
        (
            CoordError::MissingOrigin,
            "Frame enu/ned requires an explicit geodetic or ECEF origin",
        ),
        (
            CoordError::MissingReference,
            "Short plus codes require a geodetic reference; use a full plus code otherwise",
        ),
        (
            CoordError::MissingEllipsoidalHeight,
            "ECEF conversion requires ellipsoidal height or a supplied geoid separation; no geoid model is applied",
        ),
        (
            CoordError::UndefinedPosition,
            "ECEF position or local-frame orientation is undefined; provide a valid position and a geodetic pole origin",
        ),
        (
            CoordError::NonFinite { field: "x".into() },
            "Coordinate field x must be finite",
        ),
        (
            CoordError::OutOfRange {
                field: "lat".into(),
            },
            "Coordinate field lat is outside the supported range",
        ),
        (
            CoordError::InvalidChecksum,
            "NMEA checksum is missing or invalid",
        ),
        (
            CoordError::NoFix,
            "NMEA sentence does not contain an active position fix",
        ),
        (
            CoordError::UnsupportedCellResolution {
                frame: "h3".into(),
                resolution: 9,
            },
            "H3 reverse queries support resolutions 0 through 8; use an explicit parent cell",
        ),
    ] {
        assert_eq!(e.to_string(), message);
        let r = invalid_result(Some("lla"), &e);
        assert_eq!(
            r.result.status,
            thereabouts_core::result::Status::InvalidInput
        );
        assert_eq!(r.query.error.unwrap().message, message);
        assert!(r.query.normalized.is_none());
        assert_eq!(r.query.conversion, Vec::<String>::new());
        assert_eq!(r.query.uncertainty, Uncertainty::default());
    }
}
fn pack() -> thereabouts_core::format::Pack {
    thereabouts_core::format::Pack::open(
        &std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/packs/core-synthetic"),
        true,
    )
    .unwrap()
}
#[test]
fn adapters_preserve_legacy_json_and_h3_resolution() {
    let pack = pack();
    for evidence in [false, true] {
        for (lat, lon) in [
            (48.8566, 2.3522),
            (0.125, 12.375),
            (-33.8688, 151.2093),
            (90.0, 0.0),
            (0.0, 180.0),
        ] {
            let legacy = pack.reverse(lat, lon, evidence).unwrap();
            let new = reverse_value(&pack, &json!({"frame":"lla","lat":lat,"lon":lon}), evidence)
                .unwrap();
            assert_eq!(new.result, legacy);
            assert_eq!(new.query.declared_frame.as_deref(), Some("lla"));
            assert_eq!(new.query.input_frame, "geodetic");
            let mut serialized = serde_json::to_value(new).unwrap();
            serialized.as_object_mut().unwrap().remove("query");
            assert_eq!(serialized, serde_json::to_value(legacy).unwrap());
        }
        for cell in ["881fb46625fffff", "801ffffffffffff", "8009fffffffffff"] {
            let old = pack.from_h3(cell, evidence).unwrap();
            let new = reverse_value(&pack, &json!({"frame":"h3","cell":cell}), evidence).unwrap();
            assert_eq!(new.result, old);
            assert_eq!(new.result.cell.as_deref(), Some(cell));
            assert!(new.query.cell_extent.is_some());
        }
    }
    let result = reverse_point(
        &pack,
        &point(Frame::Geodetic(geodetic(f64::NAN, 0.0, None))),
        false,
    )
    .unwrap();
    assert_eq!(
        result.result.status,
        thereabouts_core::result::Status::InvalidInput
    );
    assert_eq!(result.query.declared_frame, None);
    let result = reverse_value(&pack, &json!({"frame":"llv","x":0}), false).unwrap();
    let encoded = serde_json::to_value(result).unwrap();
    assert_eq!(encoded["status"], "invalid_input");
    assert!(encoded.get("evidence").is_none());
    assert!(encoded["query"]["normalized"].is_null());
    assert_eq!(
        encoded["query"]["uncertainty"],
        json!({"accuracy_m":null,"hdop":null,"vdop":null})
    );
}
#[test]
fn adapters_preserve_pack_errors_and_invalids_do_not_read() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/packs/postal-synthetic");
    let wrong = thereabouts_core::format::Pack::open(&root, true).unwrap();
    assert!(reverse_value(&wrong, &json!({"lat":0,"lon":0}), false).is_err());
    assert_eq!(
        reverse_value(&wrong, &json!({"lat":999,"lon":0}), false)
            .unwrap()
            .result
            .status,
        thereabouts_core::result::Status::InvalidInput
    );
    assert!(
        normalize(&point(Frame::Ecef(Ecef {
            x: 6378137.0,
            y: 0.0,
            z: 0.0
        })))
        .is_ok()
    );
}
#[test]
fn bounded_10k_conversion_benchmark() {
    let start = std::time::Instant::now();
    let mut max_residual = 0.0_f64;
    for i in 0..10_000 {
        let p = geodetic(
            -79.0 + f64::from(i % 159),
            -179.0 + f64::from(i % 358),
            Some(f64::from(i) * 10000.0),
        );
        let xyz = geodetic_to_ecef(&p).unwrap();
        let q = ecef_to_geodetic(&xyz).unwrap();
        let check = geodetic_to_ecef(&q).unwrap();
        max_residual = max_residual.max(
            (xyz.x - check.x)
                .hypot(xyz.y - check.y)
                .hypot(xyz.z - check.z),
        );
        std::hint::black_box(q);
    }
    assert!(max_residual < 0.001);
    eprintln!(
        "10k ECEF forward/inverse/forward: {:?}, maximum residual {max_residual} m",
        start.elapsed()
    );
}

#[test]
fn exact_geohash_sizes_all_lengths_and_extreme_bounds() {
    for length in 1_usize..=12 {
        let longitude_bits = i32::try_from((length * 5).div_ceil(2)).unwrap();
        let latitude_bits = i32::try_from(length * 5 / 2).unwrap();
        for symbol in ['0', 'b', 'z', 'p'] {
            let value = symbol.to_string().repeat(length);
            let p = normalized(&json!({"frame":"geohash","value":value}));
            let e = p.cell_extent.unwrap();
            assert_eq!(e.half_lat_deg, Some(90.0 / 2_f64.powi(latitude_bits)));
            assert_eq!(e.half_lon_deg, Some(180.0 / 2_f64.powi(longitude_bits)));
            for v in e.boundary {
                assert!((-90.0..=90.0).contains(&v.lat));
                assert!((-180.0..=180.0).contains(&v.lon));
            }
        }
    }
}
#[test]
fn local_ecef_origins_and_geocentre_origins() {
    let g = geodetic(48.8566, 2.3522, Some(35.0));
    let ecef = geodetic_to_ecef(&g).unwrap();
    let a = enu_to_ecef(123.0, -456.0, 789.0, &Origin::Geodetic(g)).unwrap();
    let b = enu_to_ecef(123.0, -456.0, 789.0, &Origin::Ecef(ecef)).unwrap();
    close(a.x, b.x, 1e-8);
    close(a.y, b.y, 1e-8);
    close(a.z, b.z, 1e-8);
    assert_eq!(
        enu_to_ecef(
            10000000.0,
            0.0,
            0.0,
            &Origin::Geodetic(geodetic(0.0, 0.0, Some(-6378137.0)))
        )
        .unwrap_err(),
        CoordError::UndefinedPosition
    );
}
#[test]
fn s2_all_faces_levels_and_h3_supported_resolutions() {
    for face in 0_u64..6 {
        for level in 0..=30 {
            let shift = 60 - level * 2;
            let sentinel = 1_u64 << shift;
            for path in [0_u64, 0x0123_4567_89ab_cdef, 0x1fff_ffff_ffff_ffff] {
                let id =
                    (face << 61) | (path & 0x1fff_ffff_ffff_ffff & !(sentinel * 2 - 1)) | sentinel;
                let p = normalize(&point(Frame::S2(CellId::Integer(id)))).unwrap();
                assert!(p.point.lat.is_finite());
                assert!(p.point.lon.is_finite());
                let e = p.cell_extent.unwrap();
                assert_eq!(e.boundary.len(), 4);
                assert!(e.radius_m > 0.0 && e.radius_m.is_finite());
            }
        }
    }
    let pack = pack();
    for resolution in 0_u8..=15 {
        let cell = h3o::LatLng::new(48.8566, 2.3522)
            .unwrap()
            .to_cell(h3o::Resolution::try_from(resolution).unwrap());
        let result = reverse_point(
            &pack,
            &point(Frame::H3(CellId::Integer(u64::from(cell)))),
            false,
        )
        .unwrap();
        if resolution <= 8 {
            assert_eq!(
                result.result,
                pack.from_h3(&cell.to_string(), false).unwrap()
            );
        } else {
            assert_eq!(
                result.query.error.unwrap().code,
                "unsupported_cell_resolution"
            );
        }
    }
}
#[test]
fn all_utm_bands_hemispheres_and_admission_bounds() {
    for (i, band) in "CDEFGHJKLMNPQRSTUVWX".chars().enumerate() {
        let lat = -80.0 + f64::from(u8::try_from(i).unwrap()) * 8.0 + 0.5;
        let mut utm = geodetic_to_utm(&geodetic(lat, 3.0, None), Some(31)).unwrap();
        assert_eq!(utm.band, Some(band));
        utm.hemisphere = None;
        close(utm_to_geodetic(&utm).unwrap().lat, lat, 1e-9);
    }
    for (key, value) in [
        ("zone", json!(0)),
        ("zone", json!(61)),
        ("hemisphere", json!("Q")),
        ("band", json!("I")),
        ("easting", json!(99999.99)),
        ("easting", json!(900000.01)),
        ("northing", json!(-0.01)),
        ("northing", json!(10000000.01)),
    ] {
        let mut v = json!({"frame":"utm","zone":31,"hemisphere":"N","easting":500000,"northing":0});
        v[key] = value;
        assert!(parse_point(&v).is_err(), "{v}");
    }
}

#[test]
fn olc_poles_dateline_and_nearest_short_recovery() {
    for (full, short, lat, lon) in [
        ("22222222+22", "2222+22", -90.0, -180.0),
        ("CVXXXXXX+XX", "XXXX+XX", 90.0, 180.0),
        ("6VGX2X2X+2X", "2X2X+2X", 0.0, -180.0),
    ] {
        let a = normalized(&json!({"frame":"pluscode","value":full}));
        // Recover using the decoded centre first, then exercise explicit pole/dateline references.
        let b = normalized(
            &json!({"frame":"pluscode","value":short,"reference":{"lat":a.point.lat,"lon":a.point.lon}}),
        );
        close(a.point.lat, b.point.lat, 1e-10);
        longitude(a.point.lon, b.point.lon, 1e-10);
        let edge = normalized(
            &json!({"frame":"pluscode","value":short,"reference":{"lat":lat,"lon":lon}}),
        );
        assert!((-90.0..=90.0).contains(&edge.point.lat));
        assert!((-180.0..180.0).contains(&edge.point.lon));
    }
    for prefix in [
        "SRID=4326;POINT(1 2)",
        "GEOGCS[\"WGS 84\"]",
        "PROJCRS[\"custom\"]",
        "crs:EPSG:4326",
    ] {
        let error = parse_point(&json!({"frame":"wkt","value":prefix})).unwrap_err();
        assert_eq!(error.code(), "unsupported_frame");
        assert!(
            error
                .to_string()
                .contains("GeoReconcile crs: support or pyproj")
        );
    }
}
#[test]
fn numeric_and_parser_bounds_never_panic() {
    let mut rng = Rng(42);
    for frame in ["dms", "wkt", "nmea", "pluscode", "mgrs", "geohash"] {
        for length in [0, 1, 2, 3, 15, 64, 128, 256, 1024, 1025] {
            let s: String = (0..length)
                .map(|_| {
                    rng.0 = rng.0.wrapping_mul(6364136223846793005).wrapping_add(1);
                    char::from(u8::try_from((rng.0 >> 56) % 95 + 32).unwrap())
                })
                .collect();
            let _ = parse_point(&json!({"frame":frame,"value":s}));
        }
    }
    assert!(parse_point(&json!({"frame":"geojson","coordinates":[1,2,3,4,5,6]})).is_err());
    assert!(parse_point(&json!({"frame":"nmea","value":"é"})).is_err());
    assert!(parse_point(&json!({"frame":"s2","cell":"ü"})).is_err());
}

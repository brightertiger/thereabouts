//! Reverse means reading published labels, never selecting a new nearest city.
use crate::{
    format::{Pack, address, spatial::Label},
    result::{City, Country, Evidence, LookupResult, Point, State},
};
use h3o::{CellIndex, LatLng, Resolution};

const METHODS: [&str; 8] = [
    "",
    "city_polygon",
    "policy_polygon",
    "urban_allocation",
    "town_radius",
    "rural_polygon",
    "rural_nearest",
    "rural_nearest_distant",
];
impl Pack {
    /// Index a valid coordinate once at resolution eight, then walk logical ancestors.
    pub fn reverse(&self, lat: f64, lon: f64, evidence: bool) -> crate::Result<LookupResult> {
        if !lat.is_finite()
            || !lon.is_finite()
            || !(-90.0..=90.0).contains(&lat)
            || !(-180.0..=180.0).contains(&lon)
        {
            return Ok(LookupResult::empty("invalid_input"));
        }
        let Ok(point) = LatLng::new(lat, lon) else {
            return Ok(LookupResult::empty("invalid_input"));
        };
        self.lookup(point.to_cell(Resolution::Eight), evidence)
    }
    /// Accept canonical H3 cells at any resolution through eight.
    pub fn from_h3(&self, text: &str, evidence: bool) -> crate::Result<LookupResult> {
        if text.len() != 15 || !text.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Ok(LookupResult::empty("invalid_input"));
        }
        let Ok(cell) = text.parse::<CellIndex>() else {
            return Ok(LookupResult::empty("invalid_input"));
        };
        if cell.resolution() > Resolution::Eight {
            return Ok(LookupResult::empty("invalid_input"));
        }
        self.lookup(cell, evidence)
    }
    fn lookup(&self, cell: CellIndex, evidence: bool) -> crate::Result<LookupResult> {
        let mut answer = LookupResult::empty("not_found");
        let centre = LatLng::from(cell);
        answer.point = Some(Point {
            lat: centre.lat(),
            lon: centre.lng(),
        });
        // The public cell is always r8. Coarse queries do not choose a descendant label.
        answer.cell = cell.center_child(Resolution::Eight).map(|c| c.to_string());
        let mut reason = "outside_coverage";
        let found = if cell.resolution() < Resolution::Three {
            reason = "no_stored_ancestor";
            None
        } else {
            self.block(address::address(cell).0)?.and_then(|block| {
                reason = if cell.resolution() == Resolution::Eight {
                    "no_land"
                } else {
                    "no_stored_ancestor"
                };
                block.lookup(cell)
            })
        };
        if let Some((key, label)) = found {
            let stored = address::cell_at(address::address(cell).0, key).ok();
            answer = self.project(answer, label)?;
            reason = if answer.status == "matched" {
                "matched"
            } else {
                "unassigned"
            };
            if evidence {
                let method = label.0[3] & 7;
                answer.evidence = Some(Evidence {
                    stored_cell: stored.map(|c| c.to_string()),
                    city_method: METHODS
                        .get(method as usize)
                        .filter(|m| !m.is_empty())
                        .map(|m| (*m).into()),
                    land_method: Some(
                        if label.0[3] & 32 == 0 {
                            "land"
                        } else {
                            "offshore"
                        }
                        .into(),
                    ),
                    reason: Some(reason.into()),
                    distance_greater_than_km: (method == 7)
                        .then(|| f64::from(self.manifest.distant_over_m) / 1000.0),
                    distance_at_most_km: (method >= 6).then(|| {
                        f64::from(if method == 7 {
                            self.manifest.cutoff_m
                        } else {
                            self.manifest.distant_over_m
                        }) / 1000.0
                    }),
                    source_ids: self
                        .place(label.0[2])?
                        .and_then(|p| serde_json::from_str::<serde_json::Value>(p.field(11)).ok())
                        .and_then(|v| v.get("source_ids").cloned()),
                });
            }
            let zones = self
                .metadata
                .timezone_sets
                .get(label.0[4] as usize)
                .ok_or_else(|| crate::Error::Corrupt("Dangling timezone set".into()))?;
            if zones.len() > 1 {
                answer.candidates = zones
                    .iter()
                    .map(|zone| {
                        let mut candidate = answer.clone();
                        candidate.timezone = Some(zone.clone());
                        candidate
                    })
                    .collect();
                answer.status = "ambiguous".into();
                answer.timezone = None;
                answer.rank_basis = Some("timezone_name".into());
            }
        } else if evidence {
            answer.evidence = Some(Evidence {
                stored_cell: None,
                city_method: None,
                land_method: None,
                reason: Some(reason.into()),
                distance_greater_than_km: None,
                distance_at_most_km: None,
                source_ids: None,
            });
        }
        Ok(answer)
    }
    fn project(&self, mut answer: LookupResult, label: Label) -> crate::Result<LookupResult> {
        let [country, state, city, flags, tz] = label.0;
        if let Some(place) = self.place(country)? {
            let code = place.field(6);
            let meta = self
                .metadata
                .countries
                .iter()
                .find(|r| r["country_code"].as_str() == Some(code));
            answer.country = Some(Country {
                code: code.into(),
                code3: meta
                    .and_then(|r| r["alpha3"].as_str())
                    .filter(|s| !s.is_empty())
                    .map(str::to_owned),
                name: place.field(1).into(),
            });
        }
        answer.state = self.place(state)?.map(|p| State {
            code: p.text[7].clone().filter(|s| !s.is_empty()),
            name: p.field(1).into(),
        });
        answer.city = self.place(city)?.map(|p| City {
            id: p.field(0).into(),
            name: p.field(1).into(),
            name_en: p.text[2].clone().filter(|s| !s.is_empty()),
            kind: p.field(5).into(),
            population: (p.population != 0).then_some(p.population),
            point: p.point(),
        });
        let zones = self
            .metadata
            .timezone_sets
            .get(tz as usize)
            .ok_or_else(|| crate::Error::Corrupt("Dangling timezone set".into()))?;
        if zones.len() == 1 {
            answer.timezone = zones.first().cloned();
        }
        if country != 0 || state != 0 || city != 0 {
            answer.status = "matched".into();
            answer.r#match = Some(
                match flags & 7 {
                    6 => "nearest",
                    7 => "nearest_distant",
                    _ => "contained",
                }
                .into(),
            );
        }
        Ok(answer)
    }
}
#[cfg(test)]
mod tests {
    use crate::result::LookupResult;
    #[test]
    fn omitted_evidence_and_null_distance() {
        let json = serde_json::to_value(LookupResult::empty("not_found")).unwrap();
        assert!(json.get("evidence").is_none());
        assert!(json["distance_km"].is_null());
    }
}

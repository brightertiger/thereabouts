//! Reverse means reading published labels, never selecting a new nearest city.
use crate::{
    format::{Pack, address, spatial::Label},
    result::{City, Country, DistanceBand, Evidence, LookupResult, Point, State},
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
            return Ok(invalid_coordinates());
        }
        let Ok(point) = LatLng::new(lat, lon) else {
            return Ok(invalid_coordinates());
        };
        self.lookup(point.to_cell(Resolution::Eight), evidence)
    }
    /// Accept canonical H3 cells at any resolution through eight.
    pub fn from_h3(&self, text: &str, evidence: bool) -> crate::Result<LookupResult> {
        if text.len() != 15 || !text.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Ok(LookupResult::empty(crate::result::Status::InvalidInput));
        }
        let Ok(cell) = text.parse::<CellIndex>() else {
            return Ok(LookupResult::empty(crate::result::Status::InvalidInput));
        };
        if cell.resolution() > Resolution::Eight {
            return Ok(LookupResult::empty(crate::result::Status::InvalidInput));
        }
        self.lookup(cell, evidence)
    }
    fn lookup(&self, cell: CellIndex, evidence: bool) -> crate::Result<LookupResult> {
        self.require_family("core")?;
        let mut answer = LookupResult::empty(crate::result::Status::NotFound);
        let centre = LatLng::from(cell);
        answer.point = Some(Point {
            lat: centre.lat(),
            lon: centre.lng(),
        });
        // Preserve the query cell; a coarse query never invents a resolution-eight descendant.
        answer.cell = Some(cell.to_string());
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
            reason = if answer.status == crate::result::Status::Matched {
                "matched"
            } else {
                "unassigned"
            };
            if evidence {
                let method = label.0[3] & 7;
                answer.evidence = Some(Evidence {
                    stored_cell: stored.map(|c| c.to_string()),
                    country_id: self.place(label.0[0], false)?.map(|p| p.field(0).into()),
                    state_id: self.place(label.0[1], false)?.map(|p| p.field(0).into()),
                    city_id: self.place(label.0[2], false)?.map(|p| p.field(0).into()),
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
                    timezones: vec![],
                    source_ids: self
                        .place(label.0[2], true)?
                        .and_then(|p| serde_json::from_str::<serde_json::Value>(p.field(11)).ok())
                        .and_then(|v| v.get("source_ids").cloned()),
                });
            }
            let zones = self.metadata.narrow_timezones(
                &self.metadata_index,
                label.0[4],
                answer.country.as_ref().map(|c| c.code.as_str()),
            )?;
            answer.timezone = (zones.len() == 1).then(|| zones.first().cloned()).flatten();
            if zones.len() != 1
                && let Some(audit) = &mut answer.evidence
            {
                audit.timezones = zones;
            }
        } else if evidence {
            answer.evidence = Some(Evidence {
                stored_cell: None,
                country_id: None,
                state_id: None,
                city_id: None,
                city_method: None,
                land_method: None,
                reason: Some(reason.into()),
                timezones: vec![],
                source_ids: None,
            });
        }
        Ok(answer)
    }
    pub(crate) fn project(
        &self,
        mut answer: LookupResult,
        label: Label,
    ) -> crate::Result<LookupResult> {
        let [country, state, city, flags, _] = label.0;
        if let Some(place) = self.place(country, false)? {
            let code = place.field(6);
            let meta = self
                .metadata_index
                .countries
                .get(code)
                .and_then(|index| self.metadata.countries.get(*index));
            answer.country = Some(Country {
                code: code.into(),
                code3: meta
                    .and_then(|r| r["alpha3"].as_str())
                    .filter(|s| !s.is_empty())
                    .map(str::to_owned),
                name: place.field(1).into(),
            });
        }
        answer.state = self
            .place(state, false)?
            .map(|place| -> crate::Result<State> {
                let meta = self
                    .metadata_index
                    .subdivisions
                    .get(place.field(7))
                    .and_then(|index| self.metadata.subdivisions.get(*index));
                if let Some(row) = meta {
                    Ok(State {
                        code: row
                            .get("code")
                            .and_then(serde_json::Value::as_str)
                            .map(str::to_owned),
                        name: row
                            .get("name")
                            .and_then(serde_json::Value::as_str)
                            .ok_or_else(|| {
                                crate::Error::Corrupt("Missing subdivision name".into())
                            })?
                            .into(),
                    })
                } else {
                    Ok(State {
                        code: place.text[7].clone().filter(|s| !s.is_empty()),
                        name: place.field(1).into(),
                    })
                }
            })
            .transpose()?;
        answer.city = self.place(city, false)?.map(|p| City {
            id: p.field(0).into(),
            name: p.field(1).into(),
            name_en: p.text[2].clone().filter(|s| !s.is_empty()),
            kind: p.field(5).into(),
            population: (p.population != 0).then_some(p.population),
            point: p.point(),
        });
        if country != 0 || state != 0 || city != 0 {
            answer.status = crate::result::Status::Matched;
            answer.distance_band = match flags & 7 {
                6 => Some(DistanceBand {
                    greater_than_km: 0.0,
                    at_most_km: f64::from(self.manifest.distant_over_m) / 1000.0,
                }),
                7 => Some(DistanceBand {
                    greater_than_km: f64::from(self.manifest.distant_over_m) / 1000.0,
                    at_most_km: f64::from(self.manifest.cutoff_m) / 1000.0,
                }),
                _ => None,
            };
            answer.r#match = Some(match flags & 7 {
                6 => crate::result::Match::Nearest,
                7 => crate::result::Match::NearestDistant,
                _ => crate::result::Match::Contained,
            });
        }
        Ok(answer)
    }
}
fn invalid_coordinates() -> LookupResult {
    let mut result = LookupResult::empty(crate::result::Status::InvalidInput);
    result.hint = Some("Use finite latitude in [-90, 90] and longitude in [-180, 180]".into());
    result
}
#[cfg(test)]
mod tests {
    use crate::result::LookupResult;
    #[test]
    fn omitted_evidence_and_null_distance() {
        let json =
            serde_json::to_value(LookupResult::empty(crate::result::Status::NotFound)).unwrap();
        assert!(json.get("evidence").is_none());
        assert!(json["distance_band"].is_null());
    }
}

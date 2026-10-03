//! Literal IPv4/IPv6 lookup against published inclusive intervals.
use crate::{
    Result,
    format::{Pack, intervals::Address},
    result::{Kind, LookupResult, Status},
};
use std::net::IpAddr;
/// Parse an address literal; ports, zones and CIDRs are not addresses.
#[must_use]
pub fn parse(value: &str) -> Option<Address> {
    match value
        .trim_matches(|c: char| c.is_ascii_whitespace())
        .parse::<IpAddr>()
        .ok()?
    {
        IpAddr::V4(v) => Some((4, u128::from(u32::from(v)))),
        IpAddr::V6(v) => Some((6, u128::from(v))),
    }
}
impl Pack {
    /// Resolve one inclusive interval, preserving source point and contextual geography.
    pub fn ip(&self, value: &str, evidence: bool) -> Result<LookupResult> {
        self.require_family("ip")?;
        let Some(address) = parse(value) else {
            let mut result = LookupResult::empty(Status::InvalidInput);
            result.kind = Kind::IpRange;
            result.hint = Some(
                "Use ip(address) with an IPv4 or IPv6 literal, without a port or CIDR.".into(),
            );
            return Ok(result);
        };
        self.forward_result(
            self.interval_observations(address, evidence)?,
            Kind::IpRange,
            evidence,
        )
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn address_families_remain_distinct() {
        assert_eq!(super::parse("1.2.3.4"), Some((4, 0x0102_0304)));
        assert_eq!(super::parse("::1"), Some((6, 1)));
        assert!(super::parse("::ffff:1.2.3.4").is_some_and(|v| v.0 == 6));
        for bad in [
            "1.2.3.4:80",
            "1.2.3.4/24",
            "01.2.3.4",
            "fe80::1%eth0",
            "256.1.2.3",
            "",
        ] {
            assert!(super::parse(bad).is_none());
        }
    }
}

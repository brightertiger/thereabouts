//! Prepared Myers edit distance: reuse query masks across trigram candidates.
use std::collections::BTreeMap;
pub(crate) struct Distance {
    ascii: [u128; 128],
    other: BTreeMap<char, u128>,
    length: usize,
}
impl Distance {
    pub(crate) fn new(query: &str) -> Self {
        let mut result = Self {
            ascii: [0; 128],
            other: BTreeMap::new(),
            length: query.chars().count(),
        };
        for (i, c) in query.chars().take(128).enumerate() {
            let mask = 1_u128 << i;
            if let Some(entry) = result.ascii.get_mut(c as usize) {
                *entry |= mask;
            } else {
                *result.other.entry(c).or_default() |= mask;
            }
        }
        result
    }
    pub(crate) fn close(&self, candidate: &str) -> bool {
        let length = candidate.chars().count();
        let threshold = (self.length / 4).clamp(1, 3);
        if self.length > 128 || self.length.abs_diff(length) > threshold {
            return false;
        }
        if self.length == 0 {
            return length <= threshold;
        }
        let high = 1_u128 << (self.length - 1);
        let mut positive = u128::MAX;
        let mut negative = 0;
        let mut score = self.length;
        for c in candidate.chars() {
            let equal = self
                .ascii
                .get(c as usize)
                .copied()
                .unwrap_or_else(|| self.other.get(&c).copied().unwrap_or(0));
            let vertical = equal | negative;
            let horizontal = ((equal & positive).wrapping_add(positive) ^ positive) | equal;
            let mut plus = negative | !(horizontal | positive);
            let mut minus = positive & horizontal;
            score += usize::from(plus & high != 0);
            score -= usize::from(minus & high != 0);
            plus = (plus << 1) | 1;
            minus <<= 1;
            positive = minus | !(vertical | plus);
            negative = plus & vertical;
        }
        score <= threshold
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    proptest! {
        #[test]
        fn bit_distance_agrees_with_dynamic_programming(a in "[a-z東京é]{0,128}",b in "[a-z東京é]{0,128}") {
            prop_assert_eq!(Distance::new(&a).close(&b),crate::name_normalization::close(&a,&b));
        }
    }
    #[test]
    fn upper_bit_and_unicode_substitution() {
        let a = "東".repeat(128);
        let b = format!("{}京", "東".repeat(127));
        assert!(Distance::new(&a).close(&b));
        assert!(!Distance::new(&a).close(&"京".repeat(128)));
    }
}

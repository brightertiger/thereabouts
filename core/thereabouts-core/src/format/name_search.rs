//! Derived length/first-trigram buckets keep fuzzy work independent of world key count.
use std::collections::{BTreeMap, BTreeSet};

/// Across all shards: at most 2,048 distinct keys and 16,384 posting visits.
/// Measured on the million-key common-trigram workload; exact/prefix are exhaustive.
pub(crate) const FUZZY_KEYS: usize = 2048;
/// Bound catalogue projection as well as string comparison, across every shard.
pub(crate) const FUZZY_ROWS: usize = 256;
const POSTINGS_PER_KEY: usize = 8;

/// Split a pack-wide allowance deterministically, including when shards outnumber it.
pub(crate) fn share(budget: usize, shards: usize, ordinal: usize) -> usize {
    budget / shards + usize::from(ordinal < budget % shards)
}

#[derive(Debug)]
pub(super) struct Buckets {
    lengths: Vec<usize>,
    first: BTreeMap<(usize, String), Vec<usize>>,
}
fn first_trigram(key: &str) -> String {
    std::iter::once('^')
        .chain(key.chars())
        .chain(['$'])
        .take(3)
        .collect()
}
impl Buckets {
    pub(super) fn new(keys: &[String]) -> Self {
        let lengths = keys.iter().map(|k| k.chars().count()).collect::<Vec<_>>();
        let mut first = BTreeMap::<_, Vec<_>>::new();
        for (id, (key, length)) in keys.iter().zip(&lengths).enumerate() {
            first
                .entry((*length, first_trigram(key)))
                .or_default()
                .push(id);
        }
        Self { lengths, first }
    }
    /// Rare postings precede common ones; matching first trigrams get three
    /// quarters of the allowance. The remainder permits errors at the start.
    /// Small indexes remain exhaustive within the edit-distance length bounds.
    pub(super) fn candidates(
        &self,
        key: &str,
        mut postings: Vec<&[usize]>,
        budget: usize,
    ) -> Vec<usize> {
        let length = key.chars().count();
        let edits = (length / 4).clamp(1, 3);
        let eligible = |id: usize| {
            self.lengths
                .get(id)
                .is_some_and(|n| n.abs_diff(length) <= edits)
        };
        if self.lengths.len() <= budget {
            return (0..self.lengths.len()).filter(|id| eligible(*id)).collect();
        }
        let first = first_trigram(key);
        let buckets = (length.saturating_sub(edits)..=length + edits)
            .filter_map(|n| self.first.get(&(n, first.clone())))
            .collect::<Vec<_>>();
        postings.sort_by_key(|p| (p.len(), p.first().copied()));
        let mut primary = BTreeSet::new();
        let mut fallback = BTreeSet::new();
        for id in postings
            .into_iter()
            .flatten()
            .take(budget * POSTINGS_PER_KEY)
        {
            if !eligible(*id) {
                continue;
            }
            let set = if buckets.iter().any(|b| b.binary_search(id).is_ok()) {
                &mut primary
            } else {
                &mut fallback
            };
            if set.len() < budget {
                set.insert(*id);
            }
        }
        let preferred = budget * 3 / 4;
        let mut selected = primary
            .iter()
            .take(preferred)
            .copied()
            .collect::<BTreeSet<_>>();
        selected.extend(fallback.iter().take(budget - selected.len()).copied());
        for id in primary {
            if selected.len() == budget {
                break;
            }
            selected.insert(id);
        }
        selected.into_iter().collect()
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn budgets_are_pack_wide_and_first_character_errors_have_a_reserve() {
        for shards in [1, 34, 4096] {
            assert_eq!(
                (0..shards)
                    .map(|i| share(FUZZY_KEYS, shards, i))
                    .sum::<usize>(),
                FUZZY_KEYS
            );
            assert_eq!(
                (0..shards)
                    .map(|i| share(FUZZY_ROWS, shards, i))
                    .sum::<usize>(),
                FUZZY_ROWS
            );
        }
        let keys = (0..10_000)
            .map(|i| format!("synthetic {i:05} town"))
            .collect::<Vec<_>>();
        let buckets = Buckets::new(&keys);
        let postings = (0..keys.len()).collect::<Vec<_>>();
        let found = buckets.candidates("xynthetic 00000 town", vec![&postings], 32);
        assert_eq!(found.len(), 32);
        assert!(found.contains(&0));
        assert_eq!(
            buckets.candidates("synthetic 00000 town", vec![&postings], 0),
            [] as [usize; 0]
        );
    }
}

//! Byte-budgeted LRU ownership; readers may finish using an evicted Arc.
use std::{collections::HashMap, hash::Hash, sync::Arc};

#[derive(Debug)]
pub(crate) struct Cache<K, V> {
    entries: HashMap<K, (Arc<V>, usize, u64)>,
    bytes: usize,
    budget: usize,
    clock: u64,
}
impl<K: Copy + Eq + Hash, V> Cache<K, V> {
    pub(crate) fn new(budget: usize) -> Self {
        Self {
            entries: HashMap::new(),
            bytes: 0,
            budget,
            clock: 0,
        }
    }
    pub(crate) fn get(&mut self, key: K) -> Option<Arc<V>> {
        self.clock = self.clock.wrapping_add(1);
        self.entries.get_mut(&key).map(|(value, _, time)| {
            *time = self.clock;
            Arc::clone(value)
        })
    }
    pub(crate) fn insert(&mut self, key: K, value: V, bytes: usize) -> Arc<V> {
        let value = Arc::new(value);
        if bytes > self.budget {
            return value;
        }
        while self.bytes + bytes > self.budget {
            let oldest = self
                .entries
                .iter()
                .min_by_key(|(_, (_, _, time))| time)
                .map(|(k, _)| *k);
            if let Some(key) = oldest {
                if let Some((_, size, _)) = self.entries.remove(&key) {
                    self.bytes -= size;
                }
            } else {
                break;
            }
        }
        self.clock = self.clock.wrapping_add(1);
        if let Some((_, size, _)) = self
            .entries
            .insert(key, (Arc::clone(&value), bytes, self.clock))
        {
            self.bytes -= size;
        }
        self.bytes += bytes;
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn least_recently_used_and_oversized_values_do_not_escape_budget() {
        let mut cache = Cache::new(8);
        cache.insert(1, 11, 4);
        cache.insert(2, 22, 4);
        assert_eq!(*cache.get(1).unwrap(), 11);
        cache.insert(3, 33, 4);
        assert!(cache.get(2).is_none());
        assert_eq!(*cache.insert(4, 44, 9), 44);
        assert!(cache.get(4).is_none());
        assert_eq!(cache.bytes, 8);
    }
}

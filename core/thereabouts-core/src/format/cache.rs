//! Byte-budgeted O(1) LRU. Linked keys avoid unsafe intrusive pointers and eviction scans.
use std::{collections::HashMap, hash::Hash, sync::Arc};
#[derive(Debug)]
struct Entry<K, V> {
    value: Arc<V>,
    bytes: usize,
    previous: Option<K>,
    next: Option<K>,
}
#[derive(Debug)]
pub(crate) struct Cache<K, V> {
    entries: HashMap<K, Entry<K, V>>,
    bytes: usize,
    budget: usize,
    oldest: Option<K>,
    newest: Option<K>,
}
impl<K: Copy + Eq + Hash, V> Cache<K, V> {
    pub(crate) fn new(budget: usize) -> Self {
        Self {
            entries: HashMap::new(),
            bytes: 0,
            budget,
            oldest: None,
            newest: None,
        }
    }
    fn take(&mut self, key: K) -> Option<Entry<K, V>> {
        let entry = self.entries.remove(&key)?;
        if let Some(previous) = entry.previous {
            if let Some(node) = self.entries.get_mut(&previous) {
                node.next = entry.next;
            }
        } else {
            self.oldest = entry.next;
        }
        if let Some(next) = entry.next {
            if let Some(node) = self.entries.get_mut(&next) {
                node.previous = entry.previous;
            }
        } else {
            self.newest = entry.previous;
        }
        Some(entry)
    }
    fn append(&mut self, key: K, mut entry: Entry<K, V>) {
        entry.previous = self.newest;
        entry.next = None;
        if let Some(newest) = self.newest {
            if let Some(node) = self.entries.get_mut(&newest) {
                node.next = Some(key);
            }
        } else {
            self.oldest = Some(key);
        }
        self.newest = Some(key);
        self.entries.insert(key, entry);
    }
    pub(crate) fn get(&mut self, key: K) -> Option<Arc<V>> {
        let entry = self.take(key)?;
        let value = Arc::clone(&entry.value);
        self.append(key, entry);
        Some(value)
    }
    pub(crate) fn insert(&mut self, key: K, value: V, bytes: usize) -> Arc<V> {
        // Concurrent misses may decode the same immutable value; retain the first.
        if let Some(value) = self.get(key) {
            return value;
        }
        let value = Arc::new(value);
        if bytes > self.budget {
            return value;
        }
        while self.bytes + bytes > self.budget {
            if let Some(entry) = self.oldest.and_then(|key| self.take(key)) {
                self.bytes -= entry.bytes;
            } else {
                break;
            }
        }
        self.append(
            key,
            Entry {
                value: Arc::clone(&value),
                bytes,
                previous: None,
                next: None,
            },
        );
        self.bytes += bytes;
        value
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lru_order_and_duplicate_misses_preserve_budget() {
        let mut cache = Cache::new(8);
        cache.insert(1, 11, 4);
        cache.insert(2, 22, 4);
        assert_eq!(*cache.get(1).unwrap(), 11);
        cache.insert(3, 33, 4);
        assert!(cache.get(2).is_none());
        assert_eq!(*cache.insert(3, 333, 4), 33);
        assert_eq!(*cache.insert(4, 44, 9), 44);
        assert!(cache.get(4).is_none());
        cache.insert(5, 55, 8);
        assert_eq!(cache.bytes, 8);
        assert_eq!(cache.entries.len(), 1);
        assert_eq!(cache.oldest, Some(5));
        assert_eq!(cache.newest, Some(5));
    }
}

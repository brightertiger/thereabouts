//! Preserve top-level JSON field order without changing pack serialization policy.
use serde::{Deserialize, Deserializer, Serialize, Serializer, de, ser::SerializeMap};
use serde_json::{Map, Value};
use std::fmt;

pub(crate) struct Object {
    pub values: Map<String, Value>,
    pub keys: Vec<String>,
}
impl<'de> Deserialize<'de> for Object {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> de::Visitor<'de> for Visitor {
            type Value = Object;
            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a JSON object")
            }
            fn visit_map<M: de::MapAccess<'de>>(self, mut map: M) -> Result<Object, M::Error> {
                let mut object = Object {
                    values: Map::new(),
                    keys: Vec::new(),
                };
                while let Some((key, value)) = map.next_entry::<String, Value>()? {
                    if !object.values.contains_key(&key) {
                        object.keys.push(key.clone());
                    }
                    object.values.insert(key, value);
                }
                Ok(object)
            }
        }
        deserializer.deserialize_map(Visitor)
    }
}

pub(crate) struct Ordered<'a> {
    pub value: &'a Value,
    pub keys: &'a [String],
}
impl Serialize for Ordered<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let Some(object) = self.value.as_object() else {
            return self.value.serialize(serializer);
        };
        let mut map = serializer.serialize_map(Some(object.len()))?;
        for (index, key) in self.keys.iter().enumerate() {
            if !self.keys.iter().take(index).any(|previous| previous == key)
                && let Some(value) = object.get(key)
            {
                map.serialize_entry(key, value)?;
            }
        }
        for (key, value) in object {
            if !self.keys.contains(key) {
                map.serialize_entry(key, value)?;
            }
        }
        map.end()
    }
}

//! Admission of portable FST byte maps, shared by names and forward keys.
use super::container::uint;
use crate::{Error, Result, error::ensure};
use fst::Streamer;
pub(crate) fn read(bytes: Vec<u8>, ordinal: bool) -> Result<fst::Map<Vec<u8>>> {
    ensure(
        uint(&bytes, 0, 8)? == 3 && uint(&bytes, 8, 8)? == 0,
        "Unsupported name FST encoding",
    )?;
    let map = fst::Map::new(bytes).map_err(|e| Error::Corrupt(format!("Invalid FST: {e}")))?;
    map.as_fst()
        .verify()
        .map_err(|e| Error::Corrupt(format!("Invalid FST: {e}")))?;
    // Names are bounded at four million spellings; postal keys can reach the
    // published five-million-row source. Both also obey the 64 MiB artifact cap.
    ensure(
        map.len() <= if ordinal { 4_000_000 } else { 16_000_000 },
        "Oversized FST",
    )?;
    let fst = map.as_fst();
    let mut seen = std::collections::BTreeSet::new();
    let mut pending = vec![fst.root().addr()];
    while let Some(address) = pending.pop() {
        if !seen.insert(address) {
            continue;
        }
        let node = fst.node(address);
        let mut previous = None;
        let mut inputs = [None; 256];
        for (i, transition) in node.transitions().enumerate() {
            ensure(
                transition.addr < address && previous.is_none_or(|p| p < transition.inp),
                "Name FST is not an ordered acyclic backward graph",
            )?;
            previous = Some(transition.inp);
            if let Some(input) = inputs.get_mut(usize::from(transition.inp)) {
                *input = Some(i);
            }
            pending.push(transition.addr);
        }
        if node.len() > 32 {
            for input in 0..=u8::MAX {
                ensure(
                    inputs.get(usize::from(input)).copied().flatten() == node.find_input(input),
                    "Invalid name FST input table",
                )?;
            }
        }
    }
    let mut stream = map.stream();
    let mut count = 0;
    while let Some((_, value)) = stream.next() {
        ensure(
            (!ordinal || value == count) && count < map.len() as u64,
            "Invalid FST ordinal",
        )?;
        count += 1;
    }
    ensure(count == map.len() as u64, "Invalid FST key count")?;
    Ok(map)
}

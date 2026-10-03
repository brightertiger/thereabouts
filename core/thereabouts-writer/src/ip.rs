//! Typed IP endpoints are checked against their textual spelling before interval staging.
use crate::{Error, Result, error::ensure, forward, packed_staging::Packed, source::Dataset};
use rusqlite::Connection;
use thereabouts_core::format::intervals::Bounds;
pub(crate) fn load(data: &Dataset, db: &Connection) -> Result<()> {
    let mut inserts = Packed::new(db, "ip")?;
    for table in data.tables("ip_ranges") {
        data.scan(table,|row| {
            let version=row.unsigned("ip_version")?.and_then(|n|u8::try_from(n).ok()).ok_or_else(||Error::Input("Missing IP version".into()))?;
            let endpoint=|binary,text|->Result<u128>{
                let bytes=row.binary(binary)?.and_then(|v|v.try_into().ok()).ok_or_else(||Error::Input("IP endpoints must be 16 packed bytes".into()))?;
                let number=u128::from_be_bytes(bytes);
                ensure(thereabouts_core::ip::parse(row.required(text)?)==Some((version,number)),"IP textual and packed endpoints disagree")?;
                Ok(number)
            };
            let bounds=Bounds{version,first:endpoint("ip_start_packed","ip_start")?,last:endpoint("ip_end_packed","ip_end")?};
            thereabouts_core::format::intervals::follows(None,bounds)?;
            let code=format!("{}–{}",row.required("ip_start")?,row.required("ip_end")?);
            let details=serde_json::json!({"region":row.text("region")?,"city":row.text("city")?,"country_code":row.text("country_code")?}).to_string();
            let record=forward::association(db,row,"city",&code,Some(if version==4 {"ipv4"} else {"ipv6"}),Some(details))?;
            let mut key = vec![bounds.version];
            key.extend(bounds.first.to_be_bytes());
            key.extend(bounds.last.to_be_bytes());
            inserts.push(rusqlite::types::Value::Blob(key), &record)
        })?;
    }
    inserts.finish()
}

//! NDJSON wire types for the sidecar protocol -- one JSON object per
//! stdout/stdin line, UTF-8. Parsing an incoming line into anything other
//! than one of the four known frame shapes IS the protocol-corruption
//! signal `sidecar.rs`'s reader loop acts on (Round 7 §6: "framing trust
//! ends at the first corrupt byte sequence, permanently").

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PROTOCOL_NAME: &str = "fileagent-desktop";
pub const PROTOCOL_VERSION: u32 = 1;

#[derive(Debug, Deserialize)]
pub struct HandshakeFrame {
    pub protocol: String,
    pub protocol_version: u32,
}

#[derive(Debug, Deserialize, Clone)]
pub struct StartedFrame {
    pub id: String,
    pub event: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct ProgressFrame {
    pub id: String,
    pub event: String,
    #[serde(default)]
    pub data: Value,
}

#[derive(Debug, Deserialize, Clone)]
pub struct TerminalErrorPayload {
    pub kind: String,
    pub code: String,
    pub message: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct TerminalFrame {
    pub id: String,
    pub ok: bool,
    #[serde(default)]
    pub result: Option<Value>,
    #[serde(default)]
    pub error: Option<TerminalErrorPayload>,
}

#[derive(Debug, Clone)]
pub enum IncomingFrame {
    Started(StartedFrame),
    Progress(ProgressFrame),
    Terminal(TerminalFrame),
}

/// Parses one NDJSON line into a known frame shape. `Err(())` covers
/// every way a line can fail to be trustworthy protocol evidence:
/// invalid JSON, a JSON value that isn't an object, or an object that
/// matches none of the three known post-handshake frame shapes. The
/// caller (sidecar.rs) treats any `Err` as protocol corruption -- never
/// as "skip this line and keep reading."
#[allow(clippy::result_unit_err)]
pub fn parse_incoming_line(line: &str) -> Result<IncomingFrame, ()> {
    let value: Value = serde_json::from_str(line).map_err(|_| ())?;
    if !value.is_object() {
        return Err(());
    }
    if value.get("ok").is_some() {
        let terminal: TerminalFrame = serde_json::from_value(value).map_err(|_| ())?;
        return Ok(IncomingFrame::Terminal(terminal));
    }
    if let Some(event) = value.get("event").and_then(|e| e.as_str()) {
        return match event {
            "started" => {
                let started: StartedFrame = serde_json::from_value(value).map_err(|_| ())?;
                Ok(IncomingFrame::Started(started))
            }
            "progress" => {
                let progress: ProgressFrame = serde_json::from_value(value).map_err(|_| ())?;
                Ok(IncomingFrame::Progress(progress))
            }
            _ => Err(()),
        };
    }
    Err(())
}

#[allow(clippy::result_unit_err)]
pub fn parse_handshake_line(line: &str) -> Result<HandshakeFrame, ()> {
    serde_json::from_str(line).map_err(|_| ())
}

#[derive(Debug, Serialize)]
pub struct OutgoingRequest<'a> {
    pub id: &'a str,
    pub command: &'a str,
    pub params: Value,
}

pub fn serialize_request(id: &str, command: &str, params: Value) -> String {
    let request = OutgoingRequest {
        id,
        command,
        params,
    };
    serde_json::to_string(&request).expect("request frame is always serializable")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_started_frame() {
        let frame = parse_incoming_line(r#"{"id":"1","event":"started"}"#).unwrap();
        matches!(frame, IncomingFrame::Started(_));
    }

    #[test]
    fn parses_terminal_success_frame() {
        let frame = parse_incoming_line(r#"{"id":"1","ok":true,"result":{"a":1}}"#).unwrap();
        match frame {
            IncomingFrame::Terminal(t) => {
                assert!(t.ok);
                assert_eq!(t.result, Some(serde_json::json!({"a": 1})));
            }
            _ => panic!("expected terminal frame"),
        }
    }

    #[test]
    fn rejects_truncated_json() {
        assert!(parse_incoming_line(r#"{"id":"1","ok":tr"#).is_err());
    }

    #[test]
    fn rejects_well_formed_json_with_unrecognized_shape() {
        assert!(parse_incoming_line(r#"{"unexpected":"shape"}"#).is_err());
    }

    #[test]
    fn rejects_non_object_json() {
        assert!(parse_incoming_line("42").is_err());
        assert!(parse_incoming_line("[1,2,3]").is_err());
    }
}

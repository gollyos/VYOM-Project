use futures_util::{SinkExt, StreamExt};
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, State};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::{connect_async, tungstenite::Message};

const DEFAULT_MODEL: &str = "gemini-3.1-flash-live-preview";
const DEFAULT_VOICE: &str = "Aoede";
const LIVE_ENDPOINT: &str = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent";

#[derive(Default)]
pub struct VoiceBridge {
    sender: Mutex<Option<mpsc::UnboundedSender<VoiceCommand>>>,
}

enum VoiceCommand {
    Audio(String),
    AudioStreamEnd,
    /// Text the BRAIN produced, to be spoken by the live session. This is
    /// how a real tool result reaches the user's ears: the voice model
    /// never answers actionable requests itself.
    Speak(String),
    Disconnect,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VoiceProviderInfo {
    provider: String,
    model: String,
    configured: bool,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct VoiceEvent {
    kind: String,
    text: Option<String>,
    data: Option<String>,
    sample_rate: Option<u32>,
    code: Option<String>,
    message: Option<String>,
    recoverable: Option<bool>,
    model: Option<String>,
}

impl VoiceEvent {
    fn simple(kind: &str) -> Self {
        Self {
            kind: kind.into(),
            text: None,
            data: None,
            sample_rate: None,
            code: None,
            message: None,
            recoverable: None,
            model: None,
        }
    }

    fn transcript(kind: &str, text: String) -> Self {
        Self {
            text: Some(text),
            ..Self::simple(kind)
        }
    }

    fn audio(data: String, sample_rate: u32) -> Self {
        Self {
            data: Some(data),
            sample_rate: Some(sample_rate),
            ..Self::simple("audio")
        }
    }

    fn error(code: &str, message: &str, recoverable: bool) -> Self {
        Self {
            code: Some(code.into()),
            message: Some(message.into()),
            recoverable: Some(recoverable),
            ..Self::simple("error")
        }
    }
}

fn provider_model() -> String {
    std::env::var("VYOM_GEMINI_LIVE_MODEL").unwrap_or_else(|_| DEFAULT_MODEL.into())
}

fn provider_voice() -> String {
    std::env::var("VYOM_GEMINI_VOICE").unwrap_or_else(|_| DEFAULT_VOICE.into())
}

fn api_key() -> Option<String> {
    std::env::var("GEMINI_API_KEY")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            std::env::var("GOOGLE_API_KEY")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
}

fn emit(app: &AppHandle, event: VoiceEvent) {
    let _ = app.emit("voice-event", event);
}

#[tauri::command]
pub fn voice_provider_info() -> VoiceProviderInfo {
    VoiceProviderInfo {
        provider: "gemini-live".into(),
        model: provider_model(),
        configured: api_key().is_some(),
    }
}

#[tauri::command]
pub async fn voice_connect(
    app: AppHandle,
    bridge: State<'_, VoiceBridge>,
) -> Result<VoiceProviderInfo, String> {
    let key = api_key().ok_or_else(|| {
        "Gemini Live is not configured. Set GEMINI_API_KEY in the environment before launching VYOM."
            .to_string()
    })?;
    let model = provider_model();
    let voice = provider_voice();
    let (sender, receiver) = mpsc::unbounded_channel();

    let mut active_sender = bridge.sender.lock().await;
    if let Some(previous) = active_sender.take() {
        let _ = previous.send(VoiceCommand::Disconnect);
    }
    *active_sender = Some(sender);
    drop(active_sender);

    let info = VoiceProviderInfo {
        provider: "gemini-live".into(),
        model: model.clone(),
        configured: true,
    };

    tauri::async_runtime::spawn(run_voice_session(app, receiver, key, model, voice));
    Ok(info)
}

#[tauri::command]
pub async fn voice_send_audio(
    audio_base64: String,
    bridge: State<'_, VoiceBridge>,
) -> Result<(), String> {
    if audio_base64.len() > 64_000 {
        return Err("Audio chunk is larger than the allowed realtime frame.".into());
    }

    let active_sender = bridge.sender.lock().await;
    let sender = active_sender
        .as_ref()
        .ok_or_else(|| "Voice provider is not connected.".to_string())?;
    sender
        .send(VoiceCommand::Audio(audio_base64))
        .map_err(|_| "Voice provider connection is unavailable.".to_string())
}

/// Speak a Brain-produced result through the live session.
///
/// The frontend calls this when a Brain task completes, so the user hears
/// the VERIFIED outcome of real tool execution rather than whatever the
/// conversational model would have improvised.
#[tauri::command]
pub async fn voice_speak(text: String, bridge: State<'_, VoiceBridge>) -> Result<(), String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Ok(());
    }
    let bounded: String = trimmed.chars().take(1200).collect();
    let active_sender = bridge.sender.lock().await;
    let sender = active_sender
        .as_ref()
        .ok_or_else(|| "Voice provider is not connected.".to_string())?;
    sender
        .send(VoiceCommand::Speak(bounded))
        .map_err(|_| "Voice provider connection is unavailable.".to_string())
}

#[tauri::command]
pub async fn voice_audio_stream_end(bridge: State<'_, VoiceBridge>) -> Result<(), String> {
    let active_sender = bridge.sender.lock().await;
    if let Some(sender) = active_sender.as_ref() {
        let _ = sender.send(VoiceCommand::AudioStreamEnd);
    }
    Ok(())
}

#[tauri::command]
pub async fn voice_disconnect(bridge: State<'_, VoiceBridge>) -> Result<(), String> {
    let mut active_sender = bridge.sender.lock().await;
    if let Some(sender) = active_sender.take() {
        let _ = sender.send(VoiceCommand::Disconnect);
    }
    Ok(())
}

async fn run_voice_session(
    app: AppHandle,
    mut commands: mpsc::UnboundedReceiver<VoiceCommand>,
    key: String,
    model: String,
    voice: String,
) {
    emit(&app, VoiceEvent::simple("connecting"));
    let endpoint = format!("{LIVE_ENDPOINT}?key={key}");
    let websocket = match connect_async(&endpoint).await {
        Ok((websocket, _)) => websocket,
        Err(_) => {
            emit(
                &app,
                VoiceEvent::error(
                    "provider-disconnected",
                    "Could not connect to Gemini Live. Check the network and API key.",
                    true,
                ),
            );
            emit(&app, VoiceEvent::simple("disconnected"));
            return;
        }
    };

    let (mut writer, mut reader) = websocket.split();
    let setup = json!({
        "setup": {
            "model": format!("models/{model}"),
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": { "voiceName": voice }
                    }
                },
                "thinkingConfig": { "thinkingLevel": "minimal" }
            },
            // This session is VYOM's EARS AND MOUTH ONLY - it is not the
            // agent. The previous instruction here was a V0 demo script:
            // it declared that only four commands were "supported", told
            // the model to recite fixed figures ("38 qualified leads"),
            // and ended with "Do not claim real external actions or
            // data". That is precisely why the running product answered
            // "I cannot browse / code / control the PC": the voice model
            // was told it had no capabilities, and the user's words never
            // reached the Brain that does.
            //
            // Every spoken request is now transcribed and handed to the
            // Brain, which plans, calls real tools, verifies, and sends
            // its result back here to be spoken (see voice_speak).
            "systemInstruction": {
                "parts": [{
                    "text": "You are VYOM, an autonomous AI desktop operating system with full real-world execution capabilities. \
VYOM's execution is performed by its native Brain runtime: desktop app control, browser automation, filesystem, terminal, PowerShell, Python, coding, and workflow automation. \
LANGUAGE & DIALECT RULE: You understand and speak ALL Indian languages (Hindi, Hinglish, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Urdu, Odia, etc.) and ALL International languages (English, Spanish, French, German, Japanese, Chinese, Arabic, Russian, Portuguese, Italian, Korean, etc.). Always detect and strictly match the exact language and dialect the user is speaking. \
VOICE & ACCENT STYLE: You speak with a natural, sweet, expressive Indian female voice (natural Hindi / Hinglish / Indian English). Speak smoothly, warmly, politely, and finish every thought completely without cutting off midway. \
CAPABILITIES: When the user asks about your capabilities, explain proudly and warmly that you are VYOM, their autonomous AI assistant who can control the computer, open applications, automate browsers, write code, run commands, manage files, and execute desktop workflows. NEVER claim you are only a chat bot or unable to run tools or automation. \
RULES: (1) When the user asks for a real desktop action, tool, search, or PC operation (play a song, open Chrome, weather, files, anything executable), the Brain runtime plans and executes it. For such action requests SAY NOTHING AT ALL and produce no audio of your own - wait; the runtime will send you the real result as SPEAK: text, and you read that aloud. Never invent progress narration, false error messages, or refusals like 'me nahi chala sakti' - you are not the executor, the Brain is. (2) NEVER state or imply that you cannot do something; you have no visibility into what the Brain can do. (3) Small talk, greetings, and pure conversation questions you may answer directly yourself, briefly and warmly. (4) When given text prefixed with SPEAK:, read exactly that text aloud naturally. (5) Speak in a warm, helpful, proactive tone."
                }]
            },
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "disabled": false,
                    // HIGH start-sensitivity treated ANY ambient sound (breathing,
                    // background noise, a TV in another room) as the user starting
                    // to speak, which then let the model generate an unprompted
                    // reply ("I love you", "also very good") to audio that was
                    // never a real command. LOW requires a clearer speech onset
                    // before a turn even starts. (There is no MEDIUM value in the
                    // Live API - only HIGH/LOW/UNSPECIFIED(=HIGH); verified against
                    // https://ai.google.dev/api/live before picking this.)
                    "startOfSpeechSensitivity": "START_SENSITIVITY_LOW",
                    // END_SENSITIVITY_HIGH + a 320ms silence window ended the
                    // user's turn on any brief pause - a breath, a moment of
                    // thought, code-switching between Hindi/English/Gujarati
                    // mid-sentence. Each premature end-of-turn reset the
                    // frontend's transcript (see handleLevel in
                    // use-voice-runtime.ts) and the FIRST HALF of a still-
                    // forming sentence was dispatched to the Brain as if it
                    // were the complete command; the second half then
                    // arrived seconds later as an unrelated second command.
                    // The user observed this as duplicate/competing tasks, a
                    // stray HTTP 503 (both tasks racing the same API), and a
                    // multi-minute apparent "delay". LOW sensitivity plus a
                    // longer window tolerates a natural pause without ending
                    // the turn.
                    "endOfSpeechSensitivity": "END_SENSITIVITY_LOW",
                    "prefixPaddingMs": 20,
                    "silenceDurationMs": 1200
                },
                "activityHandling": "START_OF_ACTIVITY_INTERRUPTS"
            },
            "inputAudioTranscription": {},
            "outputAudioTranscription": {}
        }
    });

    if writer
        .send(Message::Text(setup.to_string().into()))
        .await
        .is_err()
    {
        emit(
            &app,
            VoiceEvent::error(
                "provider-disconnected",
                "Gemini Live disconnected during setup.",
                true,
            ),
        );
        emit(&app, VoiceEvent::simple("disconnected"));
        return;
    }

    loop {
        tokio::select! {
            outbound = commands.recv() => {
                match outbound {
                    Some(VoiceCommand::Audio(data)) => {
                        let payload = json!({
                            "realtimeInput": {
                                "audio": {
                                    "data": data,
                                    "mimeType": "audio/pcm;rate=16000"
                                }
                            }
                        });
                        if writer.send(Message::Text(payload.to_string().into())).await.is_err() {
                            break;
                        }
                    }
                    Some(VoiceCommand::AudioStreamEnd) => {
                        let payload = json!({ "realtimeInput": { "audioStreamEnd": true } });
                        if writer.send(Message::Text(payload.to_string().into())).await.is_err() {
                            break;
                        }
                    }
                    Some(VoiceCommand::Speak(text)) => {
                        // The SPEAK: prefix is the contract established in
                        // the system instruction: read exactly this text,
                        // add nothing.
                        let payload = json!({
                            "clientContent": {
                                "turns": [{
                                    "role": "user",
                                    "parts": [{ "text": format!("SPEAK: {text}") }]
                                }],
                                "turnComplete": true
                            }
                        });
                        if writer.send(Message::Text(payload.to_string().into())).await.is_err() {
                            break;
                        }
                    }
                    Some(VoiceCommand::Disconnect) | None => {
                        let _ = writer.send(Message::Close(None)).await;
                        emit(&app, VoiceEvent::simple("disconnected"));
                        return;
                    }
                }
            }
            inbound = reader.next() => {
                match inbound {
                    Some(Ok(Message::Text(text))) => {
                        if let Ok(payload) = serde_json::from_str::<Value>(&text) {
                            handle_server_message(&app, &model, &payload);
                        }
                    }
                    Some(Ok(Message::Binary(bytes))) => {
                        if let Ok(text) = std::str::from_utf8(&bytes) {
                            if let Ok(payload) = serde_json::from_str::<Value>(text) {
                                handle_server_message(&app, &model, &payload);
                            }
                        }
                    }
                    Some(Ok(Message::Ping(payload))) => {
                        if writer.send(Message::Pong(payload)).await.is_err() {
                            break;
                        }
                    }
                    Some(Ok(Message::Close(_))) | None => break,
                    Some(Err(_)) => break,
                    _ => {}
                }
            }
        }
    }

    emit(
        &app,
        VoiceEvent::error(
            "provider-disconnected",
            "Gemini Live disconnected. VYOM will try to reconnect.",
            true,
        ),
    );
    emit(&app, VoiceEvent::simple("disconnected"));
}

fn handle_server_message(app: &AppHandle, model: &str, payload: &Value) {
    if payload.get("setupComplete").is_some() {
        let mut event = VoiceEvent::simple("connected");
        event.model = Some(model.into());
        emit(app, event);
    }

    let Some(content) = payload.get("serverContent") else {
        return;
    };

    if let Some(text) = content
        .get("inputTranscription")
        .and_then(|transcription| transcription.get("text"))
        .and_then(Value::as_str)
    {
        if !text.trim().is_empty() {
            emit(app, VoiceEvent::transcript("input-transcript", text.into()));
        }
    }

    if let Some(text) = content
        .get("outputTranscription")
        .and_then(|transcription| transcription.get("text"))
        .and_then(Value::as_str)
    {
        if !text.trim().is_empty() {
            emit(app, VoiceEvent::transcript("output-transcript", text.into()));
        }
    }

    if let Some(parts) = content
        .get("modelTurn")
        .and_then(|turn| turn.get("parts"))
        .and_then(Value::as_array)
    {
        for part in parts {
            let Some(inline_data) = part.get("inlineData") else {
                continue;
            };
            let Some(data) = inline_data.get("data").and_then(Value::as_str) else {
                continue;
            };
            let mime_type = inline_data
                .get("mimeType")
                .and_then(Value::as_str)
                .unwrap_or("audio/pcm;rate=24000");
            if mime_type.starts_with("audio/pcm") {
                let sample_rate = mime_type
                    .split("rate=")
                    .nth(1)
                    .and_then(|rate| rate.parse::<u32>().ok())
                    .unwrap_or(24_000);
                emit(app, VoiceEvent::audio(data.into(), sample_rate));
            }
        }
    }

    if content
        .get("interrupted")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        emit(app, VoiceEvent::simple("interrupted"));
    }
    if content
        .get("generationComplete")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        emit(app, VoiceEvent::simple("generation-complete"));
    }
    if content
        .get("turnComplete")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        emit(app, VoiceEvent::simple("turn-complete"));
    }
}

import { useCallback, useEffect, useRef, useState } from "react";
import { newCorrelationId, trace } from "@/core/trace";
import { MicrophoneCapture, PcmAudioPlayer, pcmBufferToBase64 } from "./audio-runtime";
import { GeminiLiveVoiceProvider } from "./gemini-live-provider";
import type {
  VoiceConnectionState,
  VoiceErrorCode,
  VoiceProviderEvent,
  VoiceProviderInfo,
  VoiceRuntimeError,
  VoiceRuntimeState,
} from "./types";

type VoiceRuntimeOptions = {
  onCommand: (
    command: string,
    correlationId?: string,
    options?: { supersedesPrevious?: boolean },
  ) => void;
};

type VoiceRuntimeSnapshot = {
  state: VoiceRuntimeState;
  connection: VoiceConnectionState;
  providerInfo: VoiceProviderInfo | null;
  sessionActive: boolean;
  inputTranscript: string;
  outputTranscript: string;
  level: number;
  error: VoiceRuntimeError | null;
  toggle: () => void;
  retry: () => void;
  /** Speak a Brain-produced result. No-op when voice is not connected. */
  speak: (text: string) => void;
};

function isTauriRuntime() {
  return "__TAURI_INTERNALS__" in window;
}

// Utterances that carry no instruction. Everything else - in any wording
// or language - is forwarded verbatim to the Brain, which decides whether
// it is informational or actionable.
//
// This replaces `canonicalCommand`, which mapped a transcript to one of
// exactly four hard-coded English phrases and returned null for anything
// else. A null meant the sentence was NEVER sent to the Brain, so every
// real spoken request was answered by the conversational voice model
// alone - which has no tools. That single function was why speaking to
// VYOM produced talk instead of action.
const CONVERSATIONAL_ONLY = /^(hi|hey|hello|yo|thanks|thank you|thankyou|ok|okay|cool|nice|great|hmm+|uh+|um+|namaste|shukriya|theek hai|thik hai)[\s.!,?]*$/i;

// How long the transcript must stop changing before it counts as a
// finished utterance. 700ms was shorter than an ordinary mid-sentence
// pause, so long sentences were chopped into several commands. This is
// comfortably longer than a breath and still well under the point where
// the user would perceive VYOM as slow to react.
const DISPATCH_SETTLE_MS = 1400;

// STOP is a kernel interrupt, so it must not pay the normal long-sentence
// settle cost.  This is intentionally only a debounce hint in the voice
// adapter: the text still enters the same Brain command bus, where
// is_interrupt_command() remains the authoritative classifier.  A short
// settle window gives a following object ("stop Chrome") time to arrive
// without making a bare "stop" feel unresponsive.
const INTERRUPT_DISPATCH_SETTLE_MS = 220;

// Echo Guard: When VYOM finishes speaking, room reverberation/echo-tail
// from speakers can be picked up by the microphone and cause a self-loop
// or duplicate answer. Suppress mic input for 2.5s after audio stops.
const ECHO_TAIL_GUARD_MS = 2500;
const BARGE_IN_LEVEL_THRESHOLD = 0.048;

const INTERRUPT_TOKENS = new Set([
  "stop", "cancel", "halt", "abort", "enough", "ruko", "ruk", "ja", "jao",
  "rukiye", "bas", "karo", "band", "kar", "chhodo", "chodo", "mat", "nahi",
  "rehne", "rahne", "do", "रुको", "रुक", "जाओ", "बस", "करो", "बंद", "छोड़ो",
  "मत", "रहने", "दो", "थम", "चुप", "हो",
]);

const INTERRUPT_FILLER = new Set([
  "vyom", "hey", "ok", "okay", "please", "abhi", "now", "yaar", "arre", "अभी", "अरे",
  "this", "that", "it", "ise", "isko", "usko", "ye", "yeh", "current", "task", "kaam",
  "इसको", "इसे", "ये", "यह", "काम",
]);

function isLikelyInterruptCandidate(text: string) {
  const words = normaliseForCommit(text).split(" ").filter(Boolean);
  if (words.length === 0 || words.length > 6) return false;
  const meaningful = words.filter((word) => !INTERRUPT_FILLER.has(word));
  return meaningful.length > 0 && meaningful.every((word) => INTERRUPT_TOKENS.has(word));
}

/**
 * ONE SPOKEN UTTERANCE = ONE IDENTITY.
 *
 * Input transcription arrives as growing revisions of the same sentence.
 * Treating each revision as a new command produced several independent
 * reasoning missions for one thing the user said - eight, in the worst
 * logged case, each with its own planning call.
 *
 * An utterance now carries an id, a revision counter and a dispatch
 * state. Revisions update the SAME utterance; only a stable (final)
 * revision is dispatched; and a later revision of an already-dispatched
 * utterance SUPERSEDES it (cancelling the in-flight task) rather than
 * racing alongside it.
 */
type UtteranceState = "collecting" | "dispatched" | "superseded";

type Utterance = {
  id: string;
  revision: number;
  text: string;
  isFinal: boolean;
  state: UtteranceState;
  dispatchedText: string | null;
};

function newUtterance(): Utterance {
  return {
    id: `utt_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    revision: 0,
    text: "",
    isFinal: false,
    state: "collecting",
    dispatchedText: null,
  };
}

/**
 * Is `next` a continuation of the same sentence, or a genuinely new one?
 *
 * A continuation extends what was already heard. A new utterance starts
 * over - which is what happens after VYOM has replied, or after a real
 * pause resets the transcript.
 */
function isSameUtterance(current: Utterance, next: string) {
  if (!current.text) return true;
  const a = current.text.toLowerCase().trim();
  const b = next.toLowerCase().trim();
  return b.startsWith(a) || a.startsWith(b);
}

function isDispatchable(transcript: string) {
  const clean = transcript.trim();
  if (clean.length < 2) return false;
  return !CONVERSATIONAL_ONLY.test(clean);
}

/**
 * ONE ACOUSTIC TURN = ONE COMMITTED COMMAND.
 *
 * `isSameUtterance` compares lowercased text, but the commit guard below
 * compared RAW text. Gemini Live emits the same sentence on two streams
 * that differ only in capitalisation and final punctuation, so the guard
 * never matched and both were committed:
 *
 *   16:09:12.063  "you can hear me?"   -> task + reply + TTS
 *   16:09:12.108  "You can hear me?"   -> task + reply + TTS
 *   16:09:22.145  "यह ड्यूल ऑडियो क्यों आ रही है?"  -> task + reply + TTS
 *   16:09:22.244  "ये ड्यूल ऑडियो क्यों आ रही है?"  -> task + reply + TTS
 *
 * 45ms and 99ms apart - far inside the 1400ms settle window, so these are
 * two transcriptions of ONE thing the user said, not two commands. VYOM
 * answered each twice. The user's very next question was about the
 * duplicate audio this produced.
 */
function normaliseForCommit(text: string) {
  return text
    .toLowerCase()
    .normalize("NFKC")
    .replace(/[.,!?;:'"।॥\s]+/g, " ")
    .trim();
}

/**
 * Are these two transcripts the same acoustic turn heard twice?
 *
 * Deliberately NOT a blanket "similar text collapses" rule: a user who
 * genuinely says "open chrome" twice in a row must get two actions. The
 * discriminator is TIME - only transcripts committed within the same
 * speaking turn can be duplicates of it.
 */
const DUPLICATE_WINDOW_MS = 2200;

function isDuplicateCommit(previous: string, next: string) {
  const a = normaliseForCommit(previous);
  const b = normaliseForCommit(next);
  if (!a || !b) return false;
  if (a === b) return true;
  // One stream finalised slightly ahead of the other, so one transcript is
  // a prefix of the fuller one.
  if (a.startsWith(b) || b.startsWith(a)) return true;
  // Same words, one token reheard differently ("यह" vs "ये").
  const wordsA = a.split(" ");
  const wordsB = b.split(" ");
  if (Math.abs(wordsA.length - wordsB.length) > 1) return false;
  const shared = wordsA.filter((word) => wordsB.includes(word)).length;
  return shared / Math.max(wordsA.length, wordsB.length) >= 0.8;
}

function mergeTranscript(current: string, incoming: string) {
  const clean = incoming.trim();
  if (!clean) return current;
  if (!current || clean.toLowerCase().startsWith(current.toLowerCase())) return clean;
  if (current.toLowerCase().endsWith(clean.toLowerCase())) return current;
  return `${current} ${clean}`.replace(/\s+/g, " ").trim();
}

function microphoneError(error: unknown): VoiceRuntimeError {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return {
      code: "permission-denied",
      message: "Microphone permission was denied. Allow microphone access in Windows and relaunch voice.",
      recoverable: true,
    };
  }
  if (error instanceof DOMException && ["NotFoundError", "NotReadableError", "OverconstrainedError"].includes(error.name)) {
    return {
      code: "microphone-unavailable",
      message: "No usable microphone is available. Check the input device and Windows privacy settings.",
      recoverable: true,
    };
  }
  return {
    code: "microphone-unavailable",
    message: "VYOM could not start microphone capture.",
    recoverable: true,
  };
}

function providerError(error: unknown): VoiceRuntimeError {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("GEMINI_API_KEY")) {
    return {
      code: "provider-unconfigured",
      message: "Gemini Live needs GEMINI_API_KEY in the native VYOM environment.",
      recoverable: false,
    };
  }
  return {
    code: "api-error",
    message: "Gemini Live could not start. Check the API key and network connection.",
    recoverable: true,
  };
}

export function useVoiceRuntime({ onCommand }: VoiceRuntimeOptions): VoiceRuntimeSnapshot {
  const [state, setStateValue] = useState<VoiceRuntimeState>("Idle");
  const [connection, setConnectionValue] = useState<VoiceConnectionState>("inactive");
  const [providerInfo, setProviderInfo] = useState<VoiceProviderInfo | null>(null);
  const [sessionActive, setSessionActiveValue] = useState(false);
  const [inputTranscript, setInputTranscriptValue] = useState("");
  const [outputTranscript, setOutputTranscriptValue] = useState("");
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<VoiceRuntimeError | null>(null);

  const providerRef = useRef<GeminiLiveVoiceProvider | null>(null);
  const microphoneRef = useRef<MicrophoneCapture | null>(null);
  const playerRef = useRef<PcmAudioPlayer | null>(null);
  const stateRef = useRef<VoiceRuntimeState>("Idle");
  const connectionRef = useRef<VoiceConnectionState>("inactive");
  const sessionActiveRef = useRef(false);
  const inputTranscriptRef = useRef("");
  const outputTranscriptRef = useRef("");
  const dispatchedCommandRef = useRef<string | null>(null);
  // The one utterance currently being heard. Revisions update it in
  // place; they never create a second command for the same sentence.
  const utteranceRef = useRef<Utterance>(newUtterance());
  // The last command actually committed to the Brain in this voice
  // session, with its wall-clock time. Survives the per-turn Utterance
  // reset, which is what makes it able to catch a duplicate stream.
  const lastCommittedTextRef = useRef<string | null>(null);
  const lastCommitAtRef = useRef(0);
  const dispatchTimerRef = useRef<number | null>(null);
  const turnCompleteRef = useRef(false);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const interruptionTimerRef = useRef<number | null>(null);
  const lastLevelUpdateRef = useRef(0);
  const lastSpeechAtRef = useRef(0);
  const speakingStartedAtRef = useRef(0);
  const speakingFinishedAtRef = useRef(0);
  const onCommandRef = useRef(onCommand);
  onCommandRef.current = onCommand;

  const setState = useCallback((next: VoiceRuntimeState) => {
    stateRef.current = next;
    setStateValue(next);
  }, []);

  const setConnection = useCallback((next: VoiceConnectionState) => {
    connectionRef.current = next;
    setConnectionValue(next);
  }, []);

  const setSessionActive = useCallback((next: boolean) => {
    sessionActiveRef.current = next;
    setSessionActiveValue(next);
  }, []);

  const setInputTranscript = useCallback((next: string) => {
    inputTranscriptRef.current = next;
    setInputTranscriptValue(next);
  }, []);

  const setOutputTranscript = useCallback((next: string) => {
    outputTranscriptRef.current = next;
    setOutputTranscriptValue(next);
  }, []);

  const interruptPlayback = useCallback(() => {
    if (stateRef.current !== "Speaking") return;
    playerRef.current?.clear();
    speakingFinishedAtRef.current = performance.now();
    turnCompleteRef.current = false;
    setState("Interrupted");
    if (interruptionTimerRef.current) window.clearTimeout(interruptionTimerRef.current);
    interruptionTimerRef.current = window.setTimeout(() => {
      if (sessionActiveRef.current) setState("Listening");
    }, 120);
  }, [setState]);

  const handleLevel = useCallback((nextLevel: number) => {
    const now = performance.now();
    const isEchoTailActive = now - speakingFinishedAtRef.current < ECHO_TAIL_GUARD_MS;

    lastSpeechAtRef.current = nextLevel > 0.018 ? now : lastSpeechAtRef.current;
    if (now - lastLevelUpdateRef.current > 70) {
      setLevel(Math.min(nextLevel * 5.5, 1));
      lastLevelUpdateRef.current = now;
    }

    // In echo tail window or while speaking, require a higher barge-in threshold
    const effectiveLevelThreshold = (stateRef.current === "Speaking" || isEchoTailActive)
      ? BARGE_IN_LEVEL_THRESHOLD
      : 0.032;

    if (nextLevel > effectiveLevelThreshold) {
      if (stateRef.current === "Idle" && sessionActiveRef.current) {
        // The user has started speaking again after a settled turn: this
        // is a NEW utterance, with its own identity. Without the reset the
        // next sentence would look like a revision of the previous one and
        // supersede a command that had already been carried out.
        dispatchedCommandRef.current = null;
        utteranceRef.current = newUtterance();
        setInputTranscript("");
        setOutputTranscript("");
        setState("Listening");
      }
      if (stateRef.current === "Speaking" && now - speakingStartedAtRef.current > 260) {
        interruptPlayback();
      }
    }
  }, [interruptPlayback, setInputTranscript, setOutputTranscript, setState]);

  const sendAudio = useCallback((pcm: ArrayBuffer) => {
    if (connectionRef.current !== "connected") return;
    const now = performance.now();
    // ECHO GUARD: Do not stream microphone frames during speaking or the 2.5s echo-tail
    // window unless user has explicitly barged in (handled above).
    if (stateRef.current === "Speaking" || (now - speakingFinishedAtRef.current < ECHO_TAIL_GUARD_MS)) {
      return;
    }
    void providerRef.current?.sendAudio(pcmBufferToBase64(pcm)).catch(() => {
      if (sessionActiveRef.current) setConnection("reconnecting");
    });
  }, [setConnection]);

  const scheduleReconnect = useCallback(() => {
    if (!sessionActiveRef.current || reconnectTimerRef.current) return;
    if (reconnectAttemptRef.current >= 3) {
      setConnection("error");
      setError({
        code: "provider-disconnected",
        message: "Gemini Live could not reconnect. Voice is paused; text input remains available.",
        recoverable: true,
      });
      return;
    }

    reconnectAttemptRef.current += 1;
    setConnection("reconnecting");
    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null;
      void providerRef.current?.connect().catch(() => scheduleReconnect());
    }, 650 * reconnectAttemptRef.current);
  }, [setConnection]);

  const handleProviderEvent = useCallback((event: VoiceProviderEvent) => {
    switch (event.kind) {
      case "connecting":
        setConnection(reconnectAttemptRef.current > 0 ? "reconnecting" : "connecting");
        break;
      case "connected":
        reconnectAttemptRef.current = 0;
        setConnection("connected");
        setError(null);
        if (event.model) {
          setProviderInfo((current) => ({
            provider: current?.provider ?? "gemini-live",
            configured: true,
            model: event.model!,
          }));
        }
        if (stateRef.current === "Idle") setState("Listening");
        break;
      case "input-transcript": {
        const nextTranscript = mergeTranscript(inputTranscriptRef.current, event.text ?? "");
        setInputTranscript(nextTranscript);
        if (stateRef.current !== "Speaking" && stateRef.current !== "Interrupted") {
          setState("Understanding");
        }
        // Input transcription streams in GROWING fragments: "cardboard
        // codex", then "cardboard codex cursor", then "... and spy one".
        // The old 700ms silence timer fired on each of those prefixes, and
        // because every prefix is a different string the duplicate guard
        // never matched - one spoken sentence became eight separate Brain
        // tasks, eight planning missions and the 429 storm in the logs.
        //
        // Dispatch now requires the transcript to have STOPPED GROWING:
        // the timer is only allowed to fire on a value identical to the
        // one seen when it was armed. A still-extending utterance re-arms
        // instead of dispatching a fragment of the user's sentence.
        // Fold this fragment into the CURRENT utterance, or begin a new
        // one if the user has plainly started a different sentence.
        {
          const current = utteranceRef.current;
          if (!isSameUtterance(current, nextTranscript) && current.state !== "collecting") {
            utteranceRef.current = newUtterance();
          }
          const utterance = utteranceRef.current;
          utterance.revision += 1;
          utterance.text = nextTranscript;
          utterance.isFinal = false;
        }

        if (dispatchTimerRef.current) window.clearTimeout(dispatchTimerRef.current);
        const armedRevision = utteranceRef.current.revision;
        const settleMs = isLikelyInterruptCandidate(utteranceRef.current.text)
          ? INTERRUPT_DISPATCH_SETTLE_MS
          : DISPATCH_SETTLE_MS;
        dispatchTimerRef.current = window.setTimeout(() => {
          dispatchTimerRef.current = null;
          const utterance = utteranceRef.current;
          const correlationId = newCorrelationId();

          // A newer revision arrived while this timer was pending: the
          // user is still speaking, so this is not the finished sentence.
          if (utterance.revision !== armedRevision) {
            trace(correlationId, "voice.utterance.still-growing", {
              utterance_id: utterance.id, revision: utterance.revision,
            });
            return;
          }

          // Stable for the settle window -> this utterance is FINAL.
          utterance.isFinal = true;
          const text = utterance.text.trim();

          if (!isDispatchable(text)) {
            trace(correlationId, "voice.utterance.skipped", {
              utterance_id: utterance.id, revision: utterance.revision,
              transcript: text, reason: "conversational-only",
            });
            return;
          }
          if (utterance.dispatchedText === text) {
            trace(correlationId, "voice.utterance.duplicate", {
              utterance_id: utterance.id, revision: utterance.revision,
            });
            return;
          }

          // SESSION-LEVEL COMMIT GUARD. The per-utterance check above is
          // not enough on its own: when a turn settles, `handleLevel`
          // builds a NEW Utterance for the next sentence, so a second
          // transcription of the SAME acoustic turn arriving milliseconds
          // later carried a fresh id and a null dispatchedText - and sailed
          // straight through. This guard is keyed on the session, not the
          // utterance object, so it still holds across that reset.
          const sinceLastCommit = Date.now() - lastCommitAtRef.current;
          if (
            lastCommittedTextRef.current !== null &&
            sinceLastCommit < DUPLICATE_WINDOW_MS &&
            isDuplicateCommit(lastCommittedTextRef.current, text)
          ) {
            trace(correlationId, "voice.utterance.duplicate-stream-merged", {
              utterance_id: utterance.id, revision: utterance.revision,
              previous: lastCommittedTextRef.current, transcript: text,
              gap_ms: sinceLastCommit,
            });
            utterance.dispatchedText = text;
            utterance.state = "superseded";
            return;
          }

          // If THIS utterance was already dispatched at an earlier
          // revision, the new text supersedes it: submitToBrain cancels
          // the in-flight task server-side, so one sentence can never own
          // two concurrent reasoning missions.
          const supersedesPrevious = utterance.dispatchedText !== null;
          if (supersedesPrevious) {
            utterance.state = "superseded";
            trace(correlationId, "voice.utterance.superseded", {
              utterance_id: utterance.id, revision: utterance.revision,
              previous: utterance.dispatchedText, transcript: text,
            });
          }

          utterance.dispatchedText = text;
          utterance.state = "dispatched";
          dispatchedCommandRef.current = text;
          lastCommittedTextRef.current = text;
          lastCommitAtRef.current = Date.now();
          trace(correlationId, "voice.transcript.dispatched", {
            utterance_id: utterance.id, revision: utterance.revision,
            is_final: true, transcript: text,
          });
          onCommandRef.current(text, correlationId, { supersedesPrevious });
        }, settleMs);
        break;
      }
      case "output-transcript":
        setOutputTranscript(mergeTranscript(outputTranscriptRef.current, event.text ?? ""));
        break;
      case "audio":
        if (event.data) {
          setState("Speaking");
          speakingStartedAtRef.current = performance.now();
          void playerRef.current?.enqueue(event.data, event.sampleRate ?? 24_000);
        }
        break;
      case "interrupted":
        interruptPlayback();
        break;
      case "generation-complete":
        break;
      case "turn-complete":
        turnCompleteRef.current = true;
        if (!playerRef.current?.isPlaying) setState("Idle");
        break;
      case "error":
        setError({
          code: event.code ?? "api-error",
          message: event.message ?? "Gemini Live reported an error.",
          recoverable: event.recoverable ?? true,
        });
        if (event.recoverable) scheduleReconnect();
        else setConnection("error");
        break;
      case "disconnected":
        setConnection("disconnected");
        if (sessionActiveRef.current) scheduleReconnect();
        break;
    }
  }, [interruptPlayback, scheduleReconnect, setConnection, setInputTranscript, setOutputTranscript, setState]);

  useEffect(() => {
    if (!isTauriRuntime()) return;
    const provider = new GeminiLiveVoiceProvider();
    providerRef.current = provider;
    let removeListener: (() => void) | undefined;

    void provider.getInfo().then(setProviderInfo).catch(() => undefined);
    void provider.subscribe(handleProviderEvent).then((remove) => { removeListener = remove; });

    playerRef.current = new PcmAudioPlayer(
      () => {
        speakingStartedAtRef.current = performance.now();
        setState("Speaking");
      },
      () => {
        speakingFinishedAtRef.current = performance.now();
        if (turnCompleteRef.current && stateRef.current === "Speaking") setState("Idle");
      },
      (outputLevel) => setLevel(Math.min(outputLevel * 4.5, 1)),
    );

    return () => {
      removeListener?.();
      provider.destroy();
      void provider.disconnect();
      void microphoneRef.current?.stop();
      void playerRef.current?.close();
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
      if (interruptionTimerRef.current) window.clearTimeout(interruptionTimerRef.current);
    };
  }, [handleProviderEvent, setState]);

  const stop = useCallback(async () => {
    setSessionActive(false);
    reconnectAttemptRef.current = 0;
    if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
    playerRef.current?.clear();
    await providerRef.current?.endAudioStream().catch(() => undefined);
    await providerRef.current?.disconnect().catch(() => undefined);
    await microphoneRef.current?.stop().catch(() => undefined);
    microphoneRef.current = null;
    setConnection("inactive");
    setState("Idle");
    setLevel(0);
  }, [setConnection, setSessionActive, setState]);

  const start = useCallback(async () => {
    if (!isTauriRuntime()) {
      setError({
        code: "native-required",
        message: "Real voice is available only inside the native Tauri VYOM application.",
        recoverable: false,
      });
      return;
    }

    setError(null);
    setInputTranscript("");
    setOutputTranscript("");
    turnCompleteRef.current = false;
    dispatchedCommandRef.current = null;
    utteranceRef.current = newUtterance();
    lastCommittedTextRef.current = null;
    lastCommitAtRef.current = 0;
    setConnection("connecting");

    try {
      const microphone = new MicrophoneCapture();
      microphoneRef.current = microphone;
      await microphone.start({ onAudio: sendAudio, onLevel: handleLevel });
      setSessionActive(true);
      setState("Listening");
    } catch (microphoneFailure) {
      setError(microphoneError(microphoneFailure));
      setConnection("error");
      setSessionActive(false);
      return;
    }

    try {
      const info = await providerRef.current!.connect();
      setProviderInfo(info);
    } catch (providerFailure) {
      setError(providerError(providerFailure));
      await stop();
      setConnection("error");
    }
  }, [handleLevel, sendAudio, setConnection, setInputTranscript, setOutputTranscript, setSessionActive, setState, stop]);

  const toggle = useCallback(() => {
    if (sessionActiveRef.current) void stop();
    else void start();
  }, [start, stop]);

  // ALWAYS-ON VOICE. The user's requirement: "muje click na karna pade
  // bolne ke liye, vo automatically on hi rahe". The session starts by
  // itself the moment the app launches (native runtime + configured
  // provider) and stays on for the whole session. This runs exactly ONCE
  // per mount: if the user deliberately stops voice afterwards, it stays
  // stopped until they start it again - auto-start must never fight the
  // user's own hands. A permission failure surfaces the normal
  // recoverable notice instead of silently retrying in a loop.
  const autoStartedRef = useRef(false);
  useEffect(() => {
    if (!isTauriRuntime() || autoStartedRef.current) return;
    if (sessionActiveRef.current || connectionRef.current !== "inactive") return;
    if (!providerInfo?.configured) return;
    autoStartedRef.current = true;
    void start();
  }, [providerInfo, start]);

  const retry = useCallback(() => {
    void stop().then(start);
  }, [start, stop]);

  const speak = useCallback((text: string) => {
    if (!isTauriRuntime() || connectionRef.current !== "connected") return;
    void providerRef.current?.speak(text).catch(() => undefined);
  }, []);

  return {
    state,
    connection,
    providerInfo,
    sessionActive,
    inputTranscript,
    outputTranscript,
    level,
    error,
    toggle,
    retry,
    speak,
  };
}

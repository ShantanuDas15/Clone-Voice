"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  MAX_RECORDING_SECONDS,
  MIN_RECORDING_SECONDS,
  detectRecordingSupport,
  micErrorMessage,
} from "@/lib/recording";

export type RecorderState =
  | { phase: "idle" }
  | { phase: "requesting" }
  | { phase: "recording" }
  | { phase: "stopped"; blob: Blob; seconds: number }
  | { phase: "error"; message: string };

/**
 * Recording state machine: idle → requesting → recording → stopped | error.
 * Tracks are always released (mic indicator off), the recording auto-stops at the maximum
 * length or when the tab is hidden, and a failed or too-short recording yields no blob.
 */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>({ phase: "idle" });
  const [seconds, setSeconds] = useState(0);
  // The live stream, exposed so the UI can meter it; null whenever the microphone is released.
  const [stream, setStream] = useState<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const discardRef = useRef(false); // set when the result must not be published (error/unmount)
  const requestIdRef = useRef(0);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setStream(null);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, []);

  const fail = useCallback(
    (message: string) => {
      discardRef.current = true;
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          // Already stopping.
        }
      }
      releaseStream();
      chunksRef.current = [];
      setState({ phase: "error", message });
    },
    [releaseStream],
  );

  const start = useCallback(async () => {
    const support = detectRecordingSupport();
    if (!support.supported) {
      setState({ phase: "error", message: support.reason });
      return;
    }
    const requestId = ++requestIdRef.current;
    discardRef.current = false;
    chunksRef.current = [];
    setSeconds(0);
    setState({ phase: "requesting" });

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      if (requestId === requestIdRef.current) {
        setState({ phase: "error", message: micErrorMessage(e) });
      }
      return;
    }
    if (requestId !== requestIdRef.current) {
      // Cancelled or unmounted while the permission prompt was open: release immediately.
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    streamRef.current = stream;
    setStream(stream);

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: support.mimeType });
    } catch (e) {
      fail(micErrorMessage(e));
      return;
    }
    recorderRef.current = recorder;

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onerror = () => fail("Recording failed. Please try again.");
    recorder.onstop = () => {
      const elapsed = (Date.now() - startedAtRef.current) / 1000;
      releaseStream();
      if (discardRef.current) return;
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      chunksRef.current = [];
      if (elapsed < MIN_RECORDING_SECONDS || blob.size === 0) {
        setState({
          phase: "error",
          message: `The recording was too short. Record at least ${MIN_RECORDING_SECONDS} seconds.`,
        });
        return;
      }
      setSeconds(elapsed);
      setState({ phase: "stopped", blob, seconds: elapsed });
    };
    // A device unplugged mid-recording ends its track.
    stream.getAudioTracks().forEach((track) => {
      track.onended = () => {
        if (recorderRef.current?.state === "recording") {
          fail("The microphone was disconnected. Please reconnect it and record again.");
        }
      };
    });

    startedAtRef.current = Date.now();
    recorder.start(1000);
    setState({ phase: "recording" });
    timerRef.current = setInterval(() => {
      const elapsed = (Date.now() - startedAtRef.current) / 1000;
      setSeconds(elapsed);
      if (elapsed >= MAX_RECORDING_SECONDS) stop();
    }, 250);
  }, [fail, releaseStream, stop]);

  /** Throw away the current take (or cancel a pending permission prompt) and return to idle. */
  const discard = useCallback(() => {
    requestIdRef.current += 1;
    discardRef.current = true;
    stop();
    releaseStream();
    chunksRef.current = [];
    setSeconds(0);
    setState({ phase: "idle" });
  }, [releaseStream, stop]);

  // Stop when the tab is hidden; a long background recording is unlikely to be intentional.
  const recording = state.phase === "recording";
  useEffect(() => {
    if (!recording) return;
    const onHidden = () => {
      if (document.visibilityState === "hidden") stop();
    };
    document.addEventListener("visibilitychange", onHidden);
    return () => document.removeEventListener("visibilitychange", onHidden);
  }, [recording, stop]);

  // Unmount: never leave the microphone open.
  useEffect(
    () => () => {
      requestIdRef.current += 1;
      discardRef.current = true;
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (timerRef.current) clearInterval(timerRef.current);
    },
    [],
  );

  return { state, seconds, stream, start, stop, discard };
}

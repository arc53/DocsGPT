import React from 'react';

//Recognition runs in-browser

export type RecordingState = 'idle' | 'recording' | 'transcribing' | 'error';

interface SpeechRecognitionLike extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type LegacyAudioWindow = Window &
  typeof globalThis & { webkitAudioContext?: typeof AudioContext };

const LEVEL_FFT_SIZE = 1024;
const LEVEL_SMOOTHING = 0.6;

type SpeechWindow = Window &
  typeof globalThis & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };

const recognitionClass = (): SpeechRecognitionConstructor | undefined => {
  if (typeof window === 'undefined') return undefined;
  const speechWindow = window as SpeechWindow;
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
};

export const voiceInputSupported = (): boolean => {
  if (typeof window === 'undefined') return false;
  // Gated on a secure origin, where the failure looks identical to the API
  // being absent.
  if (!window.isSecureContext) return false;
  return recognitionClass() !== undefined;
};

/** Message worth showing, or null for outcomes that are not errors. */
const errorMessage = (code: string): string | null => {
  switch (code) {
    // The user pressed stop.
    case 'aborted':
      return null;
    case 'no-speech':
      return 'No speech was picked up.';
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone access was blocked.';
    case 'audio-capture':
      return 'No microphone was found.';
    case 'network':
      return 'Voice input is unavailable right now.';
    case 'language-not-supported':
      return 'Voice input does not support this language.';
    default:
      return 'Voice input stopped unexpectedly.';
  }
};

interface UseVoiceInputOptions {
  onStart: () => void;
  /** Final words plus the interim tail. */
  onTranscript: (text: string) => void;
  onEnd?: () => void;
}

/** The composer's microphone; one button toggles it. */
export const useVoiceInput = ({
  onStart,
  onTranscript,
  onEnd,
}: UseVoiceInputOptions) => {
  const [recordingState, setRecordingState] =
    React.useState<RecordingState>('idle');
  const [error, setError] = React.useState<string | null>(null);
  const recognitionRef = React.useRef<SpeechRecognitionLike | null>(null);
  // The Web Speech API exposes no audio, so the waveform needs a second
  // capture of its own. Kept in a ref so the draw loop re-renders nothing.
  const analyserRef = React.useRef<AnalyserNode | null>(null);
  const audioContextRef = React.useRef<AudioContext | null>(null);
  const levelStreamRef = React.useRef<MediaStream | null>(null);
  // Finals accumulate; the interim tail is rebuilt each event, never kept.
  const finalTranscriptRef = React.useRef('');
  const isMountedRef = React.useRef(true);

  const stopLevelMeter = React.useCallback(() => {
    analyserRef.current = null;
    levelStreamRef.current?.getTracks().forEach((track) => track.stop());
    levelStreamRef.current = null;
    void audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
  }, []);

  /** Best-effort: a browser that refuses this still transcribes fine. */
  const startLevelMeter = React.useCallback(async () => {
    const audioWindow = window as LegacyAudioWindow;
    const AudioContextClass =
      audioWindow.AudioContext ?? audioWindow.webkitAudioContext;
    if (!AudioContextClass || !navigator.mediaDevices?.getUserMedia) return;

    // Never `await context.resume()`: without user activation that promise
    // never settles at all, stranding everything below it, so no analyser is
    // built. Constructed before the first await so it stays under the click's
    // activation, which is insurance for browsers that do not treat a live
    // capture as activation the way Chrome does.
    const context = new AudioContextClass();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Recording may have ended while permission was granted.
      if (!isMountedRef.current || !recognitionRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        void context.close().catch(() => undefined);
        return;
      }

      const analyser = context.createAnalyser();
      analyser.fftSize = LEVEL_FFT_SIZE;
      analyser.smoothingTimeConstant = LEVEL_SMOOTHING;
      // Not connected to the destination: that would play the microphone
      // back through the page's speakers.
      context.createMediaStreamSource(stream).connect(analyser);

      levelStreamRef.current = stream;
      audioContextRef.current = context;
      analyserRef.current = analyser;
    } catch {
      void context.close().catch(() => undefined);
    }
  }, []);

  React.useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      // `abort`, not `stop`: nothing left to deliver, and it frees the
      // microphone at once.
      recognitionRef.current?.abort();
      recognitionRef.current = null;
      stopLevelMeter();
    };
  }, [stopLevelMeter]);

  const start = React.useCallback(() => {
    const RecognitionClass = recognitionClass();
    if (!RecognitionClass) {
      setRecordingState('error');
      setError(
        typeof window !== 'undefined' && !window.isSecureContext
          ? 'Voice input needs a secure connection (HTTPS).'
          : 'This browser does not support voice input.',
      );
      return;
    }

    const recognition = new RecognitionClass();
    // Without this the engine stops at the first pause.
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    if (typeof navigator !== 'undefined' && navigator.language)
      recognition.lang = navigator.language;

    finalTranscriptRef.current = '';

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      // From `resultIndex`, not 0: the API returns the whole list every
      // time, and earlier results are already banked.
      for (
        let index = event.resultIndex;
        index < event.results.length;
        index += 1
      ) {
        const result = event.results[index];
        const text = result[0]?.transcript ?? '';
        if (result.isFinal) finalTranscriptRef.current += text;
        else interim += text;
      }
      onTranscript(`${finalTranscriptRef.current}${interim}`.trim());
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      const message = errorMessage(event.error);
      if (!isMountedRef.current || !message) return;
      setRecordingState('error');
      setError(message);
    };

    recognition.onend = () => {
      recognitionRef.current = null;
      // Not on stop(), so the bars stay live while the last utterance
      // finalises.
      stopLevelMeter();
      if (!isMountedRef.current) return;
      // An error already set its own state; do not overwrite it.
      setRecordingState((previous) =>
        previous === 'error' ? previous : 'idle',
      );
      onEnd?.();
    };

    try {
      recognition.start();
    } catch {
      // Already running, if a stop is still unwinding.
      return;
    }

    recognitionRef.current = recognition;
    setError(null);
    onStart();
    setRecordingState('recording');
    void startLevelMeter();
  }, [onEnd, onStart, onTranscript, startLevelMeter, stopLevelMeter]);

  const toggle = React.useCallback(() => {
    if (recordingState === 'transcribing') return;
    if (recordingState === 'recording') {
      // `stop`, not `abort`: the last utterance still has a final result
      // to deliver.
      setRecordingState('transcribing');
      recognitionRef.current?.stop();
      return;
    }
    start();
  }, [recordingState, start]);

  const clearError = React.useCallback(() => {
    setError(null);
    setRecordingState((previous) => (previous === 'error' ? 'idle' : previous));
  }, []);

  return { recordingState, error, toggle, clearError, analyserRef };
};

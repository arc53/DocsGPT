import React from 'react';

import type { MicButtonState } from '../components/ComposerControls';
import { useVoiceInput, voiceInputSupported } from './useVoiceInput';

interface UseDictationOptions {
  enabled: boolean;
  /** Read when dictation starts; the transcript is appended to it. */
  getDraft: () => string;
  onDraftChange: (value: string) => void;
  /** '\n' for a textarea, ' ' for a single-line input. */
  separator: string;
  onEnd?: () => void;
}

/** Microphone state plus merging the live transcript into an input's draft. */
export const useDictation = ({
  enabled,
  getDraft,
  onDraftChange,
  separator,
  onEnd,
}: UseDictationOptions) => {
  const baseRef = React.useRef('');

  const handleStart = React.useCallback(() => {
    baseRef.current = getDraft();
  }, [getDraft]);

  const handleTranscript = React.useCallback(
    (text: string) => {
      // The base is captured once, so interim revisions only replace the
      // transcript.
      const base = baseRef.current;
      onDraftChange(
        base.trim() ? `${base.replace(/\s+$/, '')}${separator}${text}` : text,
      );
    },
    [onDraftChange, separator],
  );

  const voice = useVoiceInput({
    onStart: handleStart,
    onTranscript: handleTranscript,
    onEnd,
  });

  const state: MicButtonState =
    voice.recordingState === 'recording' ||
    voice.recordingState === 'transcribing'
      ? voice.recordingState
      : 'idle';

  return {
    // Firefox has no SpeechRecognition, nor does an insecure origin.
    available: enabled && voiceInputSupported(),
    state,
    isDictating: state !== 'idle',
    error: voice.error,
    clearError: voice.clearError,
    toggle: voice.toggle,
    stop: voice.stop,
    analyserRef: voice.analyserRef,
  };
};

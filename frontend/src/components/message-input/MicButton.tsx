import { Mic, Square } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '../ui/button';
import { Spinner } from '../ui/spinner';

export type RecordingState = 'idle' | 'recording' | 'transcribing' | 'error';

type MicButtonProps = {
  recordingState: RecordingState;
  loading: boolean;
  onClick: () => void;
};

const VOICE_LABEL_KEY: Record<RecordingState, string> = {
  idle: 'conversation.voice.start',
  error: 'conversation.voice.start',
  recording: 'conversation.voice.stopRecording',
  transcribing: 'conversation.voice.transcribingAudio',
};

const VOICE_TEXT_KEY: Record<RecordingState, string> = {
  idle: 'conversation.voice.voice',
  error: 'conversation.voice.voice',
  recording: 'conversation.voice.stop',
  transcribing: 'conversation.voice.transcribing',
};

export default function MicButton({
  recordingState,
  loading,
  onClick,
}: MicButtonProps) {
  const { t } = useTranslation();
  const voiceButtonLabel = t(VOICE_LABEL_KEY[recordingState]);
  const voiceButtonText = t(VOICE_TEXT_KEY[recordingState]);
  const isRecording = recordingState === 'recording';

  return (
    <Button
      type="button"
      variant={isRecording ? 'destructive-outline' : 'outline'}
      size="sm"
      shape="pill"
      onClick={onClick}
      aria-label={voiceButtonLabel}
      title={voiceButtonLabel}
      disabled={loading || recordingState === 'transcribing'}
      className="justify-start"
    >
      {recordingState === 'transcribing' ? (
        <Spinner size="xs" label={t('conversation.voice.transcribingAudio')} />
      ) : isRecording ? (
        <Square className="size-3.5 fill-current sm:size-4" />
      ) : (
        <Mic className="size-3.5 sm:size-4" />
      )}
      <span
        className={
          isRecording
            ? 'text-xs sm:text-sm'
            : 'text-foreground text-xs sm:text-sm'
        }
      >
        {voiceButtonText}
      </span>
    </Button>
  );
}

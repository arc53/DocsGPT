import { LoaderCircle, Mic, Square } from 'lucide-react';

import { Button } from '../ui/button';

export type RecordingState = 'idle' | 'recording' | 'transcribing' | 'error';

type MicButtonProps = {
  recordingState: RecordingState;
  loading: boolean;
  onClick: () => void;
};

const getVoiceButtonLabel = (recordingState: RecordingState): string => {
  if (recordingState === 'recording') return 'Stop recording';
  if (recordingState === 'transcribing') return 'Transcribing audio';
  return 'Voice input';
};

const getVoiceButtonText = (recordingState: RecordingState): string => {
  if (recordingState === 'recording') return 'Stop';
  if (recordingState === 'transcribing') return 'Transcribing';
  return 'Voice';
};

export default function MicButton({
  recordingState,
  loading,
  onClick,
}: MicButtonProps) {
  const voiceButtonLabel = getVoiceButtonLabel(recordingState);
  const voiceButtonText = getVoiceButtonText(recordingState);
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
        <LoaderCircle className="size-3.5 animate-spin sm:size-4" />
      ) : isRecording ? (
        <Square className="size-3.5 fill-current sm:size-4" />
      ) : (
        <Mic className="size-3.5 sm:size-4" />
      )}
      <span
        className={
          isRecording
            ? 'text-xs sm:text-sm'
            : 'text-muted-foreground dark:text-foreground text-xs sm:text-sm'
        }
      >
        {voiceButtonText}
      </span>
    </Button>
  );
}

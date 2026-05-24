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

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={onClick}
      aria-label={voiceButtonLabel}
      title={voiceButtonLabel}
      disabled={loading || recordingState === 'transcribing'}
      className={`xs:px-3 xs:py-1.5 dark:border-border flex h-auto items-center justify-start rounded-full border bg-transparent px-2 py-1 shadow-none transition-colors ${
        recordingState === 'recording'
          ? 'border-[#B42318] bg-[#FEE4E2] text-[#B42318] dark:bg-[#4A2323]'
          : 'border-border dark:hover:bg-accent hover:bg-gray-100'
      } ${
        loading || recordingState === 'transcribing'
          ? 'cursor-not-allowed opacity-60'
          : ''
      }`}
    >
      {recordingState === 'transcribing' ? (
        <LoaderCircle className="mr-1 h-3.5 w-3.5 animate-spin sm:mr-1.5 sm:h-4 sm:w-4" />
      ) : recordingState === 'recording' ? (
        <Square className="mr-1 h-3.5 w-3.5 fill-current sm:mr-1.5 sm:h-4 sm:w-4" />
      ) : (
        <Mic className="mr-1 h-3.5 w-3.5 sm:mr-1.5 sm:h-4 sm:w-4" />
      )}
      <span
        className={`xs:text-xs dark:text-foreground text-xs font-medium sm:text-sm ${
          recordingState === 'recording'
            ? 'text-[#B42318]'
            : 'text-muted-foreground'
        }`}
      >
        {voiceButtonText}
      </span>
    </Button>
  );
}

import React from 'react';
import styled, { css, keyframes, useTheme } from 'styled-components';

import { Attachment } from '../types/index';
import { CircleAlert, LoaderCircle, Mic, Paperclip, X } from './icons';
import { focusRing, radii, shadows } from './tokens';

const spin = keyframes`
  to { transform: rotate(360deg); }
`;

/**
 * Determinate while uploading; indeterminate while the server parses, since
 * parsing reports no progress.
 */
const ProgressRing = styled.svg<{ $indeterminate?: boolean }>`
  width: 14px;
  height: 14px;
  color: ${(props) => props.theme.primary};
  transform: rotate(-90deg);
  animation: ${(props) => (props.$indeterminate ? spin : 'none')} 900ms linear
    infinite;
  transform-origin: center;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;

const CIRCUMFERENCE = 2 * Math.PI * 6;

const AttachmentProgress = ({ attachment }: { attachment: Attachment }) => {
  const indeterminate = attachment.status === 'processing';
  const fraction = indeterminate
    ? 0.25
    : Math.min(Math.max(attachment.progress, 0), 100) / 100;

  return (
    <ProgressRing viewBox="0 0 16 16" $indeterminate={indeterminate}>
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        opacity="0.25"
      />
      <circle
        cx="8"
        cy="8"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={CIRCUMFERENCE}
        strokeDashoffset={CIRCUMFERENCE * (1 - fraction)}
      />
    </ProgressRing>
  );
};

// Compact chips: a muted pill per file, sized to fit three on a row.
const ChipList = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 8px 0 8px;
`;

const FailureList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 12px 0 12px;
  font-size: 12px;
  line-height: 1.5;
  color: ${(props) => props.theme.destructive};
  overflow-wrap: anywhere;
`;

const Chip = styled.div<{ $failed?: boolean; $pending?: boolean }>`
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  height: 28px;
  padding: 0 2px 0 10px;
  border-radius: ${radii.full};
  font-size: 12px;
  line-height: 1;
  border: 1px solid
    ${(props) =>
      props.$failed ? props.theme.destructiveBorder : 'transparent'};
  background: ${(props) =>
    props.$failed ? props.theme.destructiveSoft : props.theme.muted};
  color: ${(props) =>
    props.$failed ? props.theme.destructive : props.theme.foreground};
  opacity: ${(props) => (props.$pending ? 0.7 : 1)};
`;

const ChipGlyph = styled.span<{ $failed?: boolean }>`
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  color: ${(props) =>
    props.$failed ? props.theme.destructive : props.theme.primary};
`;

const ChipLabel = styled.span`
  min-width: 0;
  max-width: 140px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-weight: 500;
`;

const ChipRemove = styled.button<{ $failed?: boolean }>`
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: ${radii.full};
  background: transparent;
  color: ${(props) =>
    props.$failed ? 'inherit' : props.theme.mutedForeground};
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;

  &:hover {
    background-color: ${(props) => props.theme.accent};
    color: ${(props) =>
      props.$failed ? props.theme.destructive : props.theme.foreground};
  }

  ${focusRing}
`;

const statusLabel = (attachment: Attachment): string => {
  if (attachment.status === 'uploading')
    return `Uploading ${attachment.progress}%`;
  if (attachment.status === 'processing') return 'Processing';
  if (attachment.status === 'failed') return attachment.error ?? 'Failed';
  return 'Ready';
};

export const AttachmentChips = ({
  attachments,
  onRemove,
}: {
  attachments: Attachment[];
  onRemove: (id: string) => void;
}) => {
  // Tooltips are unreachable on touch, so failure reasons are shown inline.
  const failures = attachments.filter(
    (attachment) => attachment.status === 'failed' && attachment.error,
  );

  return (
    <>
      <ChipList>
        {attachments.map((attachment) => {
          const failed = attachment.status === 'failed';
          return (
            <Chip
              key={attachment.id}
              $failed={failed}
              $pending={!failed && attachment.status !== 'completed'}
              title={`${attachment.fileName} — ${statusLabel(attachment)}`}
            >
              <ChipGlyph aria-hidden="true" $failed={failed}>
                {failed ? (
                  <CircleAlert size={14} />
                ) : attachment.status === 'completed' ? (
                  <Paperclip size={14} />
                ) : (
                  <AttachmentProgress attachment={attachment} />
                )}
              </ChipGlyph>
              <ChipLabel>{attachment.fileName}</ChipLabel>
              <ChipRemove
                type="button"
                $failed={failed}
                onClick={() => onRemove(attachment.id)}
                aria-label={`Remove ${attachment.fileName}`}
              >
                <X size={14} />
              </ChipRemove>
            </Chip>
          );
        })}
      </ChipList>

      {failures.length > 0 && (
        <FailureList role="alert">
          {failures.map((attachment) => (
            <span key={attachment.id}>
              {attachment.fileName}: {attachment.error}
            </span>
          ))}
        </FailureList>
      )}
    </>
  );
};

export const ControlBar = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px 8px 12px;
`;

export const ControlGroup = styled.div`
  display: flex;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
`;

const spinner = keyframes`
  to { transform: rotate(360deg); }
`;

const Spinner = styled(LoaderCircle)`
  animation: ${spinner} 0.9s linear infinite;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;

// Button outline sm pill; recording is destructive-outline.
const ControlButton = styled.button<{
  $recording?: boolean;
  $iconOnly?: boolean;
}>`
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  margin: 0;
  padding: ${(props) => (props.$iconOnly ? '0' : '0 10px')};
  ${(props) =>
    props.$iconOnly
      ? 'width: 32px; flex-shrink: 0; justify-content: center;'
      : ''}
  border-radius: ${radii.full};
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  outline: none;
  transition:
    background-color 0.15s ease,
    color 0.15s ease,
    border-color 0.15s ease;

  ${(props) =>
    props.$recording
      ? css`
          border: 1px solid ${props.theme.destructive};
          background: transparent;
          color: ${props.theme.destructive};

          &:hover:not(:disabled) {
            background: ${props.theme.destructive};
            color: ${props.theme.destructiveForeground};
          }

          &:focus-visible {
            box-shadow: 0 0 0 3px ${props.theme.destructiveRing};
          }
        `
      : css`
          border: 1px solid ${props.theme.border};
          background: ${props.theme.controlFill};
          color: ${props.theme.foreground};
          box-shadow: ${shadows.xs};

          &:hover:not(:disabled) {
            background: ${props.theme.controlHover};
          }

          &:focus-visible {
            border-color: ${props.theme.ring};
            box-shadow: 0 0 0 3px ${props.theme.ringSoft};
          }
        `}

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }
`;

const SquareGlyph = styled.span`
  display: block;
  width: 10px;
  height: 10px;
  margin: 3px;
  border-radius: 2px;
  background-color: currentColor;
`;

export const AttachButton = ({
  onClick,
  disabled,
}: {
  onClick: () => void;
  disabled?: boolean;
}) => (
  // A label wrapping a display:none input cannot be reached by keyboard.
  <ControlButton
    type="button"
    onClick={onClick}
    disabled={disabled}
    aria-label="Attach files"
  >
    <Paperclip size={16} />
    Attach
  </ControlButton>
);

export type MicButtonState = 'idle' | 'recording' | 'transcribing';

const MIC_LABELS: Record<MicButtonState, string> = {
  idle: 'Voice',
  recording: 'Stop',
  transcribing: 'Transcribing',
};

const MIC_TITLES: Record<MicButtonState, string> = {
  idle: 'Voice input',
  recording: 'Stop recording',
  transcribing: 'Transcribing audio',
};

export const MicButton = ({
  state,
  disabled,
  onClick,
  variant = 'pill',
}: {
  state: MicButtonState;
  disabled?: boolean;
  onClick: () => void;
  variant?: 'pill' | 'icon';
}) => (
  <ControlButton
    type="button"
    onClick={onClick}
    disabled={disabled || state === 'transcribing'}
    $recording={state === 'recording'}
    $iconOnly={variant === 'icon'}
    aria-label={MIC_TITLES[state]}
  >
    {state === 'recording' ? (
      <SquareGlyph aria-hidden="true" />
    ) : state === 'transcribing' ? (
      <Spinner size={16} />
    ) : (
      <Mic size={16} />
    )}
    {variant === 'pill' && MIC_LABELS[state]}
  </ControlButton>
);

export const ComposerNote = styled.div<{ $tone?: 'danger' }>`
  padding: 4px 4px 0 4px;
  font-size: 12px;
  line-height: 1.5;
  color: ${(props) =>
    props.$tone === 'danger'
      ? props.theme.destructive
      : props.theme.mutedForeground};
`;

const SentList = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
`;

const SentChip = styled.span`
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  height: 28px;
  padding: 0 10px;
  border-radius: ${radii.full};
  background: ${(props) => props.theme.muted};
  color: ${(props) => props.theme.foreground};
  font-size: 12px;
  line-height: 1;

  svg {
    flex-shrink: 0;
    color: ${(props) => props.theme.primary};
  }
`;

export const SentAttachments = ({
  attachments,
}: {
  attachments: { id: string; fileName: string }[];
}) => (
  <SentList>
    {attachments.map((attachment) => (
      <SentChip key={attachment.id} title={attachment.fileName}>
        <Paperclip size={14} />
        <ChipLabel>{attachment.fileName}</ChipLabel>
      </SentChip>
    ))}
  </SentList>
);

// One bar per frame: roughly a second of history at 60fps.
const WAVEFORM_BARS = 48;
const BAR_GAP_RATIO = 0.4;
// Speech peaks well below full scale; the floor keeps a quiet line visible.
const LEVEL_GAIN = 2.8;
const MIN_BAR_RATIO = 0.06;

const WaveformRow = styled.div<{ $minHeight: string }>`
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  min-height: ${(props) => props.$minHeight};
`;

const WaveformCanvas = styled.canvas`
  flex: 1;
  min-width: 0;
  height: 28px;
  display: block;
`;

const ListeningLabel = styled.span`
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 500;
  color: ${(props) => props.theme.mutedForeground};
`;

/**
 * Live microphone level, drawn to canvas in a rAF loop so frames do not
 * re-render React. A null analyser draws a flat line.
 */
export const VoiceWaveform = ({
  analyserRef,
  label,
  minHeight = '40px',
}: {
  analyserRef: React.RefObject<AnalyserNode | null>;
  label: string;
  /** Min height of the input it replaces, to avoid a layout shift. */
  minHeight?: string;
}) => {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const theme = useTheme();
  const barColor = theme.primary;

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

    // Safari exposed webkitSpeechRecognition from 14.1 but roundRect only
    // from 16.4, so dictation can run where the rounded path throws.
    const canRoundRect = typeof context.roundRect === 'function';
    const levels = new Array<number>(WAVEFORM_BARS).fill(0);
    // Bare `Uint8Array` widens to ArrayBufferLike, which the analyser
    // signature rejects.
    let samples: Uint8Array<ArrayBuffer> | null = null;
    let frame = 0;

    const draw = () => {
      frame = window.requestAnimationFrame(draw);

      const analyser = analyserRef.current;
      let level = 0;
      if (analyser) {
        if (!samples || samples.length !== analyser.fftSize)
          samples = new Uint8Array(analyser.fftSize);
        analyser.getByteTimeDomainData(samples);
        // Time-domain bytes are centred on 128.
        let sumSquares = 0;
        for (let index = 0; index < samples.length; index += 1) {
          const deviation = (samples[index] - 128) / 128;
          sumSquares += deviation * deviation;
        }
        level = Math.sqrt(sumSquares / samples.length);
      }
      levels.push(Math.min(1, level * LEVEL_GAIN));
      levels.shift();

      // The panel can resize, so dimensions are read each frame.
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (!width || !height) return;
      if (canvas.width !== Math.round(width * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      context.fillStyle = barColor;

      const slot = width / WAVEFORM_BARS;
      const barWidth = Math.max(1, slot * (1 - BAR_GAP_RATIO));
      const radius = barWidth / 2;
      for (let index = 0; index < WAVEFORM_BARS; index += 1) {
        const magnitude = Math.max(MIN_BAR_RATIO, levels[index]);
        const barHeight = magnitude * height;
        const x = index * slot + (slot - barWidth) / 2;
        const y = (height - barHeight) / 2;
        context.globalAlpha = 0.35 + 0.65 * (index / WAVEFORM_BARS);
        if (canRoundRect) {
          context.beginPath();
          context.roundRect(x, y, barWidth, barHeight, radius);
          context.fill();
        } else {
          context.fillRect(x, y, barWidth, barHeight);
        }
      }
      context.globalAlpha = 1;
    };

    frame = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(frame);
  }, [analyserRef, barColor]);

  return (
    <WaveformRow role="status" aria-label={label} $minHeight={minHeight}>
      <WaveformCanvas ref={canvasRef} aria-hidden="true" />
      <ListeningLabel>{label}</ListeningLabel>
    </WaveformRow>
  );
};

export const DropOverlay = styled.div`
  position: absolute;
  inset: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  padding: 16px;
  box-sizing: border-box;
  background: ${(props) => props.theme.background};
  opacity: 0.94;
  font-size: 14px;
  font-weight: 500;
  color: ${(props) => props.theme.mutedForeground};
`;

export const DropTarget = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 22px;
  border-radius: ${radii.xl};
  border: 1px dashed ${(props) => props.theme.primary};
  background: ${(props) => props.theme.secondary};
  color: ${(props) => props.theme.foreground};
`;

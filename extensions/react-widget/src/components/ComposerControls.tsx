import React from 'react';
import styled, { keyframes, useTheme } from 'styled-components';

import { Attachment } from '../types/index';
import { radii } from './tokens';

const ClipIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M13 7.5 8.1 12.4a3.04 3.04 0 0 1-4.3-4.3l5.3-5.3a2.03 2.03 0 0 1 2.87 2.87l-5.3 5.3a1.01 1.01 0 0 1-1.44-1.44l4.6-4.6" />
  </svg>
);

const MicIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <rect x="5.75" y="1.5" width="4.5" height="8" rx="2.25" />
    <path d="M3.5 7.5a4.5 4.5 0 0 0 9 0M8 12v2.5" />
  </svg>
);

const SquareIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="currentColor"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <rect x="4" y="4" width="8" height="8" rx="1.5" />
  </svg>
);

const DocumentIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M9 1.5H4.5A1.5 1.5 0 0 0 3 3v10a1.5 1.5 0 0 0 1.5 1.5h7A1.5 1.5 0 0 0 13 13V5.5L9 1.5Z" />
    <path d="M9 1.5V5.5H13" />
  </svg>
);

const AlertIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M8 2 1.8 13h12.4L8 2Z" />
    <path d="M8 6.5v3M8 11.5h.01" />
  </svg>
);

const CrossIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="10"
    height="10"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M4 4l8 8M12 4l-8 8" />
  </svg>
);

const spin = keyframes`
  to { transform: rotate(360deg); }
`;

/**
 * Determinate while bytes move, indeterminate while the server parses: that
 * phase has no percentage, and a bar frozen at 100% reads as a hang.
 */
const ProgressRing = styled.svg<{ $indeterminate?: boolean }>`
  width: 14px;
  height: 14px;
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

const ChipList = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 2px 2px 0 2px;
`;

const FailureList = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 2px 0 2px;
  font-size: 11.5px;
  line-height: 1.45;
  color: ${(props) => props.theme.danger!.text};
  overflow-wrap: anywhere;
`;

const Chip = styled.div<{ $failed?: boolean }>`
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: min(100%, 200px);
  padding: 4px 4px 4px 8px;
  border-radius: ${radii.full};
  font-size: 12px;
  line-height: 1.5;
  border: 1px solid
    ${(props) =>
      props.$failed ? props.theme.danger!.border : props.theme.hairline};
  background: ${(props) =>
    props.$failed ? props.theme.danger!.soft : props.theme.primary.bg};
  color: ${(props) =>
    props.$failed ? props.theme.danger!.text : props.theme.primary.text};
`;

const ChipGlyph = styled.span`
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  color: ${(props) => props.theme.accent!.base};
`;

const ChipLabel = styled.span`
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
`;

const ChipRemove = styled.button`
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: ${radii.full};
  background: transparent;
  color: inherit;
  opacity: 0.65;
  cursor: pointer;
  transition: opacity 0.15s ease;

  &:hover {
    opacity: 1;
  }

  &:focus-visible {
    outline: 2px solid ${(props) => props.theme.accent!.base};
    outline-offset: 1px;
    opacity: 1;
  }
`;

/** Chip status, for the hover title. */
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
  // A touch user cannot see a tooltip, and a phone picker's unsupported
  // file lands here. Say why in the open.
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
              title={`${attachment.fileName} — ${statusLabel(attachment)}`}
            >
              <ChipGlyph aria-hidden="true">
                {failed ? (
                  <AlertIcon />
                ) : attachment.status === 'completed' ? (
                  <DocumentIcon />
                ) : (
                  <AttachmentProgress attachment={attachment} />
                )}
              </ChipGlyph>
              <ChipLabel>{attachment.fileName}</ChipLabel>
              <ChipRemove
                type="button"
                onClick={() => onRemove(attachment.id)}
                aria-label={`Remove ${attachment.fileName}`}
              >
                <CrossIcon />
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
  gap: 6px;
  padding: 0 2px;
`;

export const ControlGroup = styled.div`
  display: flex;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
`;

const ControlButton = styled.button<{ $recording?: boolean }>`
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border-radius: ${radii.full};
  border: 1px solid
    ${(props) =>
      props.$recording ? props.theme.danger!.border : props.theme.hairline};
  background: ${(props) =>
    props.$recording ? props.theme.danger!.soft : 'transparent'};
  color: ${(props) =>
    props.$recording ? props.theme.danger!.text : props.theme.secondary.text};
  font-family: inherit;
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease,
    border-color 0.15s ease;

  &:hover:not(:disabled) {
    background: ${(props) =>
      props.$recording ? props.theme.danger!.soft : props.theme.secondary.bg};
    color: ${(props) =>
      props.$recording ? props.theme.danger!.text : props.theme.primary.text};
  }

  &:focus-visible {
    outline: 2px solid ${(props) => props.theme.accent!.base};
    outline-offset: 2px;
  }

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }
`;

export const AttachButton = ({
  onClick,
  disabled,
}: {
  onClick: () => void;
  disabled?: boolean;
}) => (
  // A button opening a hidden input, not a label wrapping one: a
  // `display: none` input takes no focus, so the label form is unreachable
  // from the keyboard.
  <ControlButton
    type="button"
    onClick={onClick}
    disabled={disabled}
    aria-label="Attach files"
    title="Attach files"
  >
    <ClipIcon aria-hidden="true" />
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
}: {
  state: MicButtonState;
  disabled?: boolean;
  onClick: () => void;
}) => (
  <ControlButton
    type="button"
    onClick={onClick}
    disabled={disabled || state === 'transcribing'}
    $recording={state === 'recording'}
    aria-label={MIC_TITLES[state]}
    title={MIC_TITLES[state]}
  >
    {state === 'recording' ? (
      <SquareIcon aria-hidden="true" />
    ) : (
      <MicIcon aria-hidden="true" />
    )}
    {MIC_LABELS[state]}
  </ControlButton>
);

export const ComposerNote = styled.div<{ $tone?: 'danger' }>`
  padding: 2px 4px 0 4px;
  font-size: 11.5px;
  line-height: 1.5;
  color: ${(props) =>
    props.$tone === 'danger'
      ? props.theme.danger!.text
      : props.theme.secondary.text};
`;

const SentList = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
`;

const SentChip = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: min(100%, 200px);
  padding: 3px 10px;
  border-radius: ${radii.full};
  border: 1px solid ${(props) => props.theme.hairline};
  background: ${(props) => props.theme.secondary.bg};
  color: ${(props) => props.theme.secondary.text};
  font-size: 11.5px;
  line-height: 1.6;
`;

export const SentAttachments = ({
  attachments,
}: {
  attachments: { id: string; fileName: string }[];
}) => (
  <SentList>
    {attachments.map((attachment) => (
      <SentChip key={attachment.id} title={attachment.fileName}>
        <DocumentIcon width={12} height={12} aria-hidden="true" />
        <ChipLabel>{attachment.fileName}</ChipLabel>
      </SentChip>
    ))}
  </SentList>
);

// One bar per animation frame, so the row holds about a second of history.
const WAVEFORM_BARS = 48;
const BAR_GAP_RATIO = 0.4;
// Speech peaks well below full scale; the floor keeps a quiet line visible.
const LEVEL_GAIN = 2.8;
const MIN_BAR_RATIO = 0.06;

const WaveformRow = styled.div`
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  min-height: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '60px' : '40px'};
`;

const WaveformCanvas = styled.canvas`
  flex: 1;
  min-width: 0;
  height: 28px;
  display: block;
`;

const ListeningLabel = styled.span`
  flex-shrink: 0;
  font-size: 11.5px;
  font-weight: 500;
  color: ${(props) => props.theme.secondary.text};
`;

/**
 * Live microphone level, standing in for the input while dictation runs.
 * Canvas inside a rAF loop, because sixty React updates a second would
 * re-render the whole composer. A null analyser draws the resting line.
 */
export const VoiceWaveform = ({
  analyserRef,
  label,
}: {
  analyserRef: React.RefObject<AnalyserNode | null>;
  label: string;
}) => {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const theme = useTheme();
  const barColor = theme.accent!.base;

  React.useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context) return;

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
        // Time-domain bytes ride on 128; RMS of the deviation is the level.
        let sumSquares = 0;
        for (let index = 0; index < samples.length; index += 1) {
          const deviation = (samples[index] - 128) / 128;
          sumSquares += deviation * deviation;
        }
        level = Math.sqrt(sumSquares / samples.length);
      }
      levels.push(Math.min(1, level * LEVEL_GAIN));
      levels.shift();

      // Re-read each frame: the panel resizes and the row reflows.
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
        context.beginPath();
        context.roundRect(x, y, barWidth, barHeight, radius);
        context.fill();
      }
      context.globalAlpha = 1;
    };

    frame = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(frame);
  }, [analyserRef, barColor]);

  return (
    <WaveformRow role="status" aria-label={label}>
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
  background: ${(props) => props.theme.primary.bg};
  opacity: 0.94;
  font-size: 13px;
  font-weight: 500;
  color: ${(props) => props.theme.secondary.text};
`;

export const DropTarget = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 22px;
  border-radius: ${radii.md};
  border: 1px dashed ${(props) => props.theme.accent!.base};
  background: ${(props) => props.theme.accent!.soft};
  color: ${(props) => props.theme.primary.text};
`;

export { ClipIcon };

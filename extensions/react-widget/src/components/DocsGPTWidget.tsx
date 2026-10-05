import React, { useRef } from 'react';
import DOMPurify from 'dompurify';
import styled, {
  keyframes,
  css,
  createGlobalStyle,
  ThemeProvider,
} from 'styled-components';
import {
  FEEDBACK,
  MESSAGE_TYPE,
  Query,
  SentAttachment,
  Status,
  WidgetCoreProps,
  WidgetProps,
} from '../types/index';
import { fetchAnswerStreaming, sendFeedback } from '../requests/streamingApi';
import {
  acceptAttribute,
  normalizeExtensions,
  useAttachments,
} from '../hooks/useAttachments';
import { useBackDismiss } from '../hooks/useBackDismiss';
import { useDictation } from '../hooks/useDictation';
import { useVisualViewportBounds } from '../hooks/useVisualViewportBounds';
import { isTouchPrimary } from '../utils/helper';
import { renderAnswer } from '../utils/markdown';
import {
  AttachButton,
  AttachmentChips,
  ComposerNote,
  ControlBar,
  ControlGroup,
  DropOverlay,
  DropTarget,
  MicButton,
  SentAttachments,
  VoiceWaveform,
} from './ComposerControls';
import {
  ArrowDown,
  Check,
  ChevronRight,
  CircleAlert,
  CloudUpload,
  Copy,
  Database,
  DocsGPTMark,
  ExternalLink,
  FileText,
  Globe,
  Maximize2,
  MessageCircle,
  Minimize2,
  RotateCcw,
  SendArrow,
  ThumbsDown,
  ThumbsUp,
  X,
} from './icons';
import { focusRing, fonts, radii, shadows, themes } from './tokens';
import {
  prettifyName,
  toolNames,
  workflowStepLabel,
  type StreamEvent,
} from '../utils/streamEvents';

/**
 * Inter, the app's face, as a 48 KB Latin variable font. Declared only once
 * the panel mounts, so a page that never opens the chat downloads nothing.
 */
const INTER_URL =
  'https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5/files/inter-latin-wght-normal.woff2';

const InterFontFace = createGlobalStyle`
  @font-face {
    font-family: 'DocsGPT Inter';
    font-style: normal;
    font-weight: 100 900;
    font-display: swap;
    src: url('${INTER_URL}') format('woff2');
  }
`;

/** What the stream's catch block shows when the request itself failed. */
const CONNECTION_ERROR =
  'Something went wrong. Check your connection and try again.';

/** How long a source a citation opened stays highlighted. */
const SOURCE_HIGHLIGHT_MS = 2000;

const isWebSource = (source: string) => /^https?:\/\//i.test(source);

/** `example.com/faq` for a source's URL; the URL itself if it won't parse. */
const sourceHost = (source: string) => {
  try {
    const url = new URL(source);
    const path = url.pathname.replace(/\/$/, '');
    return `${url.host}${path}`;
  } catch {
    return source;
  }
};

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const sizesConfig = {
  small: { size: 'small', width: '320px', height: '400px' },
  medium: { size: 'medium', width: '400px', height: '80vh' },
  large: { size: 'large', width: '666px', height: '75vh' },
  getCustom: (custom: {
    width: string;
    height: string;
    maxWidth?: string;
    maxHeight?: string;
  }) => ({
    size: 'custom',
    width: custom.width,
    height: custom.height,
    maxWidth: custom.maxWidth || '968px',
    maxHeight: custom.maxHeight || '70vh',
  }),
};

type Dimensions = {
  size: string;
  width: string;
  height: string;
  maxWidth?: string;
  maxHeight?: string;
};
const expandedDimensions = (base: Dimensions): Dimensions => ({
  ...base,
  width: 'min(880px, calc(100vw - 32px))',
  height: 'min(900px, calc(100vh - 32px))',
  maxWidth: 'calc(100vw - 32px)',
  maxHeight: 'calc(100vh - 32px)',
});
const openContainer = keyframes`
  from {
    width: 200px;
    height: 100px;
  }
`;
const closeContainer = keyframes`
  to {
    width: 200px;
    height: 100px;
  }
`;
const reducedIn = keyframes`
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
`;
const reducedOut = keyframes`
  from {
    opacity: 1;
  }
  to {
    opacity: 0;
  }
`;
const panelIn = keyframes`
  from {
    opacity: 0;
    transform: scale(0.94) translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
`;
const panelOut = keyframes`
  from {
    opacity: 1;
    transform: none;
  }
  to {
    opacity: 0;
    transform: scale(0.94) translateY(8px);
  }
`;
const fadeIn = keyframes`
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
`;
const settleIn = keyframes`
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
`;
const Overlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  z-index: 999;
  transition: opacity 0.5s;
`;

const WidgetContainer = styled.div<{ $modal?: boolean }>`
  all: initial;
  position: fixed;
  right: ${(props) => (props.$modal ? '50%' : '10px')};
  bottom: ${(props) => (props.$modal ? '50%' : '10px')};
  z-index: 1001;
  display: block;
  &.modal {
    transform: translate(50%, 50%);
  }
  align-items: center;
  text-align: left;

  @media only screen and (max-width: 768px) {
    right: 0;
    /* Keyboard inset; see useVisualViewportBounds. */
    bottom: var(--dgpt-vv-bottom, 0px);
    &.modal {
      transform: none;
    }
  }
`;

const StyledContainer = styled.div<{ $isOpen: boolean }>`
  all: initial;
  box-sizing: border-box;
  max-height: ${(props) => props.theme.dimensions!.maxHeight};
  max-width: ${(props) => props.theme.dimensions!.maxWidth};
  width: ${(props) => props.theme.dimensions!.width};
  height: ${(props) => props.theme.dimensions!.height};
  position: relative;
  flex-direction: column;
  bottom: 0;
  left: 0;
  background-color: ${(props) => props.theme.background};
  color: ${(props) => props.theme.foreground};
  font-family: ${fonts.sans};
  /* all: initial re-enables Safari's text auto-inflation. */
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
  display: flex;
  padding: 0;
  overflow: hidden;
  border-radius: ${radii['2xl']};
  box-shadow: ${shadows.modal};
  transform-origin: ${(props) =>
    props.theme.dimensions!.size === 'large' ? 'center' : '100% 100%'};
  animation: ${({ $isOpen, theme }) =>
    theme.dimensions!.size === 'large'
      ? $isOpen
        ? css`
            ${panelIn} 200ms cubic-bezier(0.16, 1, 0.3, 1) forwards
          `
        : css`
            ${panelOut} 180ms cubic-bezier(0.4, 0, 1, 1) forwards
          `
      : $isOpen
        ? css`
            ${openContainer} 150ms ease-in
          `
        : css`
            ${closeContainer} 250ms ease-in forwards
          `};
  transition:
    width 280ms cubic-bezier(0.4, 0, 0.2, 1),
    height 280ms cubic-bezier(0.4, 0, 0.2, 1);

  @media (prefers-reduced-motion: reduce) {
    animation: ${({ $isOpen }) =>
      $isOpen
        ? css`
            ${reducedIn} 120ms ease-out forwards
          `
        : css`
            ${reducedOut} 120ms ease-in forwards
          `};
    transition: none;
  }

  @media only screen and (max-width: 768px) {
    width: 100vw;
    /* 100dvh unless a keyboard is covering part of it. */
    height: var(--dgpt-vv-height, 100dvh);
    max-width: 100vw;
    max-height: var(--dgpt-vv-height, 100dvh);
    border-radius: 0;
    /* Expanding is desktop-only; easing after the keyboard reads as lag. */
    transition: none;
  }
`;

// The app's default Button in pill shape, at launcher scale.
const FloatingButton = styled.button<{ $bg?: string; $hidden: boolean }>`
  box-sizing: border-box;
  position: fixed;
  display: ${(props) => (props.$hidden ? 'none' : 'inline-flex')};
  z-index: 500;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 48px;
  margin: 0;
  padding: 0 20px;
  bottom: 16px;
  right: 16px;
  border: none;
  border-radius: ${radii.full};
  background: ${(props) => props.$bg ?? props.theme.primary};
  color: ${(props) => props.theme.primaryForeground};
  font-family: ${fonts.sans};
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  box-shadow: ${shadows.lg};
  cursor: pointer;
  outline: none;
  transition:
    background-color 0.15s ease,
    opacity 0.15s ease;
  animation: ${fadeIn} 200ms ease-out;

  &:hover {
    ${(props) =>
      props.$bg
        ? 'opacity: 0.9;'
        : `background-color: ${props.theme.primaryHover};`}
  }

  &:focus-visible {
    box-shadow:
      0 0 0 3px ${(props) => props.theme.ringSoft},
      ${shadows.lg};
  }

  img {
    width: 20px;
    height: 20px;
    object-fit: contain;
  }

  @media (prefers-reduced-motion: reduce) {
    transition: none;
    animation: none;
  }
`;
// ghost-muted icon-sm: 32px, rounded-md, accent hover.
const IconButton = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: ${radii.md};
  background-color: transparent;
  color: ${(props) => props.theme.mutedForeground};
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;

  &:hover {
    background-color: ${(props) => props.theme.accent};
    color: ${(props) => props.theme.foreground};
  }

  ${focusRing}
`;

const ExpandButton = styled(IconButton)`
  @media only screen and (max-width: 768px) {
    display: none;
  }
`;

// The side panel's PanelHeader at widget scale.
const Header = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-shrink: 0;
  box-sizing: border-box;
  padding: 16px 16px 12px 16px;
  border-bottom: 1px solid ${(props) => props.theme.border};
`;

const AvatarImage = styled.img<{ $size: number }>`
  width: ${(props) => props.$size}px;
  height: ${(props) => props.$size}px;
  flex-shrink: 0;
  border-radius: ${radii.full};
  object-fit: cover;
`;

// A white glyph on the brand circle: the stand-in when no image is set.
const AvatarMark = styled.span<{ $size: number }>`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
  width: ${(props) => props.$size}px;
  height: ${(props) => props.$size}px;
  border-radius: ${radii.full};
  background-color: ${(props) => props.theme.primary};
  color: ${(props) => props.theme.primaryForeground};
`;

// The generic person, filling the circle the way the old default image did.
const PersonGlyph = ({ size }: { size: number }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width={size}
    height={size}
    viewBox="0 0 40 40"
    fill="currentColor"
    aria-hidden="true"
    focusable="false"
  >
    <circle cx="20" cy="16" r="7" />
    <ellipse cx="20" cy="39.5" rx="18" ry="12.5" />
  </svg>
);

/**
 * The embedder's image, or a stand-in on the brand circle when none is set
 * or it fails to load: the generic person, or the DocsGPT mark.
 */
const AgentAvatar = ({
  src,
  size,
  fallback,
}: {
  src?: string;
  size: number;
  fallback: 'person' | 'mark';
}) => {
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [src]);
  if (!src || failed)
    return (
      <AvatarMark $size={size} aria-hidden="true">
        {fallback === 'mark' ? (
          <DocsGPTMark size={Math.round(size * 0.55)} />
        ) : (
          <PersonGlyph size={size} />
        )}
      </AvatarMark>
    );
  return (
    <AvatarImage
      $size={size}
      src={src}
      alt=""
      onError={() => setFailed(true)}
    />
  );
};

const ContentWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
`;

const HeaderActions = styled.div`
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  margin: -4px -8px 0 0;
`;

const Title = styled.h3`
  font-size: 20px;
  font-weight: 600;
  line-height: 1.25;
  color: ${(props) => props.theme.foreground};
  margin: 0;
  overflow-wrap: break-word;
`;

const Description = styled.p`
  font-size: 14px;
  line-height: 1.43;
  color: ${(props) => props.theme.mutedForeground};
  margin: 0;
  padding: 0;
  overflow-wrap: break-word;
`;

const Conversation = styled.div`
  height: 100%;
  box-sizing: border-box;
  padding: 16px;
  text-align: left;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
  scrollbar-width: thin;
  scrollbar-color: ${(props) => props.theme.scrollbarThumb} transparent;
  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-thumb {
    background-color: ${(props) => props.theme.scrollbarThumb};
    border-radius: ${radii.full};
  }
  &::-webkit-scrollbar-track {
    background: transparent;
  }
`;
// Always visible; the first glyph sits on the answer's text edge.
const ActionsRow = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: -8px;
  padding: 0;
`;
// ghost-muted icon-sm pill.
const ActionButton = styled.button<{
  $tone?: 'primary' | 'destructive';
  $copied?: boolean;
}>`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: ${radii.full};
  background-color: ${(props) =>
    props.$copied ? props.theme.secondary : 'transparent'};
  color: ${(props) =>
    props.$copied
      ? props.theme.secondaryForeground
      : props.$tone === 'primary'
        ? props.theme.primary
        : props.$tone === 'destructive'
          ? props.theme.destructive
          : props.theme.mutedForeground};
  font-family: inherit;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;

  &:hover:not(:disabled) {
    background-color: ${(props) =>
      props.$copied ? props.theme.secondary : props.theme.accent};
    color: ${(props) =>
      props.$copied
        ? props.theme.secondaryForeground
        : props.$tone === 'primary'
          ? props.theme.primary
          : props.$tone === 'destructive'
            ? props.theme.destructive
            : props.theme.foreground};
  }

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }

  ${focusRing}
`;
const Turn = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
`;
const ActionHint = styled.span`
  margin-left: 4px;
  font-size: 12px;
  line-height: 1;
  color: ${(props) => props.theme.destructive};
  animation: ${settleIn} 0.18s ease-out;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;
const MessageBubble = styled.div<{ $type: MESSAGE_TYPE }>`
  display: flex;
  flex-direction: column;
  align-items: ${(props) =>
    props.$type === 'QUESTION' ? 'flex-end' : 'flex-start'};
  gap: 8px;
  min-width: 0;
  font-size: 16px;
  animation: ${settleIn} 0.22s ease-out;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;
const Message = styled.div<{ $type: MESSAGE_TYPE }>`
  display: block;
  box-sizing: border-box;
  min-width: 0;
  line-height: 1.5;
  overflow-wrap: break-word;
  ${(props) =>
    props.$type === 'QUESTION'
      ? css`
          max-width: 85%;
          padding: 16px 20px;
          border-radius: ${radii['3xl']};
          background: ${props.theme.secondary};
          color: ${props.theme.foreground};
          white-space: pre-wrap;
        `
      : css`
          width: 100%;
          padding: 0;
          background: transparent;
          color: ${props.theme.foreground};
        `}
`;
// The app's answer markdown: lib/markdown.tsx, MarkdownAnswer, ui/table and
// CodeFrame, spelled out for the widget's markdown-it output.
const Markdown = styled.div`
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;

  & > :first-child {
    margin-top: 0;
  }

  a {
    color: ${(props) => props.theme.primary};
    text-decoration: none;
    text-underline-offset: 4px;
    border-radius: ${radii.sm};
    outline: none;
  }

  a:hover {
    text-decoration: underline;
  }

  a:focus-visible {
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }

  h1,
  h2,
  h3,
  h4,
  h5,
  h6 {
    margin: 16px 0 8px 0;
    font-weight: 600;
    line-height: 1.375;
    color: ${(props) => props.theme.foreground};
  }

  h1 {
    font-size: 20px;
  }

  h2 {
    font-size: 18px;
  }

  h3 {
    margin-top: 12px;
    font-size: 16px;
  }

  h4,
  h5,
  h6 {
    margin-top: 12px;
    font-size: 16px;
  }

  p {
    margin: 0;
  }

  strong {
    font-weight: 600;
  }

  hr {
    width: 100%;
    margin: 4px 0;
    border: none;
    border-top: 1px solid ${(props) => props.theme.border};
  }

  blockquote {
    margin: 0;
    padding-left: 12px;
    border-left: 2px solid ${(props) => props.theme.border};
    color: ${(props) => props.theme.mutedForeground};
  }

  ul,
  ol {
    margin: 0;
    padding: 0 0 0 16px;
    list-style-position: inside;
    white-space: normal;
  }

  ul {
    list-style-type: disc;
  }

  ol {
    list-style-type: decimal;
  }

  li + li,
  li > ul,
  li > ol {
    margin-top: 0.5em;
  }

  li p {
    display: inline;
  }

  code:not(.dgpt-code-body code) {
    padding: 4px 8px;
    border-radius: ${radii.md};
    background-color: ${(props) => props.theme.accent};
    color: ${(props) => props.theme.foreground};
    font-family: ${fonts.mono};
    font-size: 12px;
    font-weight: 400;
    white-space: pre-line;
    overflow-wrap: break-word;
  }

  /* Citation pill: Button secondary xs pill, h-5 min-w-5. */
  .dgpt-cite {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    height: 20px;
    min-width: 20px;
    margin: 0 2px;
    padding: 0 8px;
    border: none;
    border-radius: ${radii.full};
    background-color: ${(props) => props.theme.secondary};
    color: ${(props) => props.theme.secondaryForeground};
    font-family: inherit;
    font-size: 12px;
    font-weight: 500;
    line-height: 1;
    vertical-align: text-bottom;
    cursor: pointer;
    outline: none;
    transition: background-color 0.15s ease;
  }

  .dgpt-cite:hover {
    background-color: ${(props) => props.theme.secondaryHover};
  }

  .dgpt-cite:focus-visible {
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }

  /* The app's Tooltip: foreground box, background text, 12px. */
  .dgpt-cite::after {
    content: attr(aria-label);
    position: absolute;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    padding: 6px 12px;
    border-radius: ${radii.md};
    background-color: ${(props) => props.theme.foreground};
    color: ${(props) => props.theme.background};
    font-size: 12px;
    font-weight: 400;
    line-height: 1.5;
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.12s ease;
    z-index: 3;
  }

  .dgpt-cite:hover::after,
  .dgpt-cite:focus-visible::after {
    opacity: 1;
    transition-delay: 0.4s;
  }

  /* CodeFrame */
  .dgpt-code {
    width: 100%;
    min-width: 0;
    overflow: hidden;
    border: 1px solid ${(props) => props.theme.border};
    border-radius: ${radii.xl};
  }

  .dgpt-code-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 4px 8px;
    background-color: ${(props) => props.theme.answerSurface};
  }

  .dgpt-code-language {
    color: ${(props) => props.theme.foreground};
    font-size: 12px;
    font-weight: 500;
  }

  .dgpt-code-copy {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border: none;
    border-radius: ${radii.full};
    background-color: transparent;
    color: ${(props) => props.theme.mutedForeground};
    cursor: pointer;
    outline: none;
    transition:
      background-color 0.15s ease,
      color 0.15s ease;
  }

  .dgpt-code-copy:hover {
    background-color: ${(props) => props.theme.accent};
    color: ${(props) => props.theme.foreground};
  }

  .dgpt-code-copy:focus-visible {
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }

  .dgpt-code-copy .dgpt-code-copy-done,
  .dgpt-code-copy.is-copied .dgpt-code-copy-idle {
    display: none;
  }

  .dgpt-code-copy.is-copied .dgpt-code-copy-done {
    display: block;
  }

  .dgpt-code-copy.is-copied,
  .dgpt-code-copy.is-copied:hover {
    background-color: ${(props) => props.theme.secondary};
    color: ${(props) => props.theme.secondaryForeground};
  }

  .dgpt-code-body {
    box-sizing: border-box;
    margin: 0;
    padding: 12px;
    overflow-x: auto;
    background-color: ${(props) => props.theme.code.background};
    color: ${(props) => props.theme.code.text};
    font-family: ${fonts.mono};
    font-size: 12px;
    line-height: 1.5;
    white-space: pre;
    tab-size: 2;
    scrollbar-width: thin;
    scrollbar-color: ${(props) => props.theme.scrollbarThumb} transparent;
  }

  .dgpt-code-body code {
    font-family: inherit;
    font-size: inherit;
    white-space: inherit;
  }

  .token.comment,
  .token.prolog,
  .token.cdata {
    color: ${(props) => props.theme.code.comment};
  }

  .token.keyword,
  .token.boolean,
  .token.important {
    color: ${(props) => props.theme.code.keyword};
  }

  .token.string,
  .token.char,
  .token.attr-value,
  .token.regex,
  .token.inserted {
    color: ${(props) => props.theme.code.string};
  }

  .token.number,
  .token.constant {
    color: ${(props) => props.theme.code.number};
  }

  .token.function {
    color: ${(props) => props.theme.code.function};
  }

  .token.operator {
    color: ${(props) => props.theme.code.operator};
  }

  .token.property,
  .token.tag,
  .token.deleted,
  .token.symbol {
    color: ${(props) => props.theme.code.property};
  }

  .token.class-name,
  .token.attr-name,
  .token.namespace {
    color: ${(props) => props.theme.code.className};
  }

  .token.variable {
    color: ${(props) => props.theme.code.variable};
  }

  /* ui/table: a bordered frame that scrolls sideways when it must. */
  .dgpt-table-container {
    width: 100%;
    overflow-x: auto;
    border: 1px solid ${(props) => props.theme.border};
    border-radius: ${radii.sm};
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
    scrollbar-color: ${(props) => props.theme.scrollbarThumb} transparent;
  }

  .dgpt-table {
    width: 100%;
    min-width: 0;
    border-collapse: collapse;
    text-align: left;
    font-size: 14px;
  }

  .dgpt-table thead {
    background-color: ${(props) => props.theme.muted};
  }

  .dgpt-table th {
    padding: 4px 12px;
    font-weight: 400;
    color: ${(props) => props.theme.foreground};
    vertical-align: middle;
  }

  .dgpt-table td {
    padding: 8px 12px;
    font-weight: 400;
    vertical-align: middle;
  }

  .dgpt-table tr {
    border-bottom: 1px solid ${(props) => props.theme.border};
  }

  .dgpt-table tbody tr:last-child {
    border-bottom: none;
  }
`;
// Alert variant="destructive".
const ErrorAlert = styled.div`
  display: grid;
  grid-template-columns: 16px 1fr;
  column-gap: 12px;
  row-gap: 4px;
  box-sizing: border-box;
  width: 100%;
  padding: 12px 16px;
  font-size: 14px;
  color: ${(props) => props.theme.destructive};
  background-color: ${(props) => props.theme.destructiveSoft};
  border: 1px solid ${(props) => props.theme.destructiveBorder};
  border-radius: ${radii.xl};

  & > svg {
    grid-row: span 2;
    align-self: center;
  }
`;
const ErrorTitle = styled.h5`
  grid-column-start: 2;
  margin: 0;
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  letter-spacing: -0.025em;
`;
const ErrorText = styled.p<{ $raw?: boolean }>`
  grid-column-start: 2;
  margin: 0;
  font-family: ${(props) => (props.$raw ? fonts.mono : 'inherit')};
  font-size: ${(props) => (props.$raw ? '12px' : '14px')};
  line-height: 1.625;
  white-space: pre-wrap;
  overflow-wrap: break-word;
`;
const ErrorTurn = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
`;
const shimmerSweep = keyframes`
  to {
    background-position: -200% 0;
  }
`;
const statusPulse = keyframes`
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
`;
const StatusLine = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  font-size: 12px;
  font-family: inherit;
  color: ${(props) => props.theme.mutedForeground};
`;
const StatusDot = styled.span`
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 9999px;
  background-color: ${(props) => props.theme.mutedForeground};
  opacity: 0.5;
  animation: ${statusPulse} 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;
// Gradient clipped to the glyphs and swept across them.
const ShimmerText = styled.span`
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background-image: ${(props) => {
    const { base, highlight } = props.theme.shimmer;
    return `linear-gradient(90deg, ${base} 0%, ${base} 40%, ${highlight} 50%, ${base} 60%, ${base} 100%)`;
  }};
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: ${shimmerSweep} 2s linear infinite;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
    background-image: none;
    color: ${(props) => props.theme.mutedForeground};
  }
`;
// Shown only while scrolled away from the latest turn.
const ScrollToLatest = styled.button`
  position: absolute;
  /* Auto-margin centring, not translateX: settleIn owns transform. */
  left: 0;
  right: 0;
  bottom: 16px;
  margin: 0 auto;
  width: 32px;
  height: 32px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  border: 1px solid ${(props) => props.theme.border};
  border-radius: ${radii.full};
  background-color: ${(props) => props.theme.background};
  color: ${(props) => props.theme.foreground};
  line-height: 0;
  cursor: pointer;
  box-shadow: ${shadows.xs};
  animation: ${settleIn} 0.18s ease-out;
  z-index: 2;
  transition: background-color 0.15s ease;

  &:hover {
    background-color: ${(props) => props.theme.muted};
  }

  &:focus-visible {
    outline: none;
    box-shadow:
      0 0 0 3px ${(props) => props.theme.ringSoft},
      ${shadows.xs};
  }
`;
const ConversationArea = styled.div`
  position: relative;
  flex: 1;
  min-height: 0;
`;
const Composer = styled.div`
  flex-shrink: 0;
  box-sizing: border-box;
  padding: 12px 16px 0 16px;
`;
// border bg-card rounded-3xl; the rows pad themselves.
const PromptContainer = styled.form<{ $stacked?: boolean }>`
  box-sizing: border-box;
  padding: ${(props) => (props.$stacked ? '0' : '0 8px 0 0')};
  background-color: ${(props) => props.theme.card};
  border: 1px solid ${(props) => props.theme.border};
  border-radius: ${radii['3xl']};
  /* Stacked needs room for the chips and control row; inline keeps the cap. */
  max-height: ${(props) => (props.$stacked ? 'none' : '160px')};
  display: flex;
  flex-direction: ${(props) => (props.$stacked ? 'column' : 'row')};
  align-items: ${(props) => (props.$stacked ? 'stretch' : 'center')};
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease;

  /* The field recipe, only while the text field has focus: tabbing on to a
     control moves the ring to that control. */
  &:has(textarea:focus-visible) {
    border-color: ${(props) => props.theme.ring};
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }
`;
const PromptRow = styled.div`
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
`;
const HiddenFileInput = styled.input`
  display: none;
`;
const StyledTextarea = styled.textarea<{
  $hidden?: boolean;
  $stacked?: boolean;
}>`
  box-sizing: border-box;
  ${(props) => (props.$hidden ? 'display: none;' : '')}
  width: 100%;
  margin: 0;
  border: none;
  padding: ${(props) => (props.$stacked ? '14px 16px 6px 16px' : '14px 8px 14px 16px')};
  background-color: transparent;
  font-size: 16px;
  font-family: inherit;
  color: ${(props) => props.theme.foreground};
  outline: none;
  resize: none;
  transition: height 0.1s ease;
  overflow-wrap: break-word;
  white-space: pre-wrap;
  line-height: 1.25;
  text-align: left;
  min-height: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '64px' : '48px'};
  max-height: 140px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: ${(props) => props.theme.scrollbarThumb} transparent;
  &::-webkit-scrollbar {
    width: 6px;
    height: 6px;
  }
  &::-webkit-scrollbar-thumb {
    background-color: ${(props) => props.theme.scrollbarThumb};
    border-radius: ${radii.full};
  }
  &::-webkit-scrollbar-track {
    background: transparent;
  }
  &::placeholder {
    text-align: left;
    color: ${(props) => props.theme.mutedForeground};
  }
`;
// Grey while empty, brand once there is something to send.
const StyledButton = styled.button`
  display: flex;
  justify-content: center;
  align-items: center;
  flex-shrink: 0;
  background-color: ${(props) => props.theme.primary};
  color: ${(props) => props.theme.primaryForeground};
  border-radius: ${radii.full};
  min-width: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '44px' : '36px'};
  width: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '44px' : '36px'};
  height: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '44px' : '36px'};
  margin: 0;
  padding: 0px;
  border: none;
  cursor: pointer;
  outline: none;
  transition:
    background-color 0.15s ease,
    opacity 0.15s ease;

  &:hover:not(:disabled) {
    background-color: ${(props) => props.theme.primaryHover};
  }

  &:focus-visible {
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }

  &:disabled {
    background-color: ${(props) => props.theme.sendIdle};
    color: ${(props) => props.theme.mutedForeground};
    opacity: 0.5;
    cursor: default;
  }
`;
const StopGlyph = styled.span`
  display: block;
  width: 14px;
  height: 14px;
  border-radius: 4px;
  background-color: currentColor;
`;
// Centred in the empty conversation.
const HeroContainer = styled.div`
  box-sizing: border-box;
  width: 100%;
  margin: auto 0;
`;
// SharedAgentCard: a filled Card, at the top of the conversation.
const HeroWrapper = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 12px;
  box-sizing: border-box;
  padding: 16px;
  border-radius: ${radii['2xl']};
  background-color: ${(props) => props.theme.muted};
`;
const HeroText = styled.div`
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  flex: 1;
`;
const HeroTitle = styled.h3`
  color: ${(props) => props.theme.foreground};
  font-size: 16px;
  font-weight: 600;
  line-height: 1.375;
  margin: 0px;
  padding: 0px;
  overflow-wrap: break-word;
`;
// A filled Card turns muted text to foreground.
const HeroDescription = styled.p`
  color: ${(props) => props.theme.foreground};
  font-size: 12px;
  line-height: 1.625;
  margin: 0px;
  padding: 0px;
  overflow-wrap: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
`;
const Hyperlink = styled.a`
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
  border-radius: ${radii.sm};
  transition: color 0.15s ease;
  &:hover {
    color: ${(props) => props.theme.foreground};
  }
  ${focusRing}
`;
const Tagline = styled.div`
  text-align: center;
  display: block;
  color: ${(props) => props.theme.mutedForeground};
  padding: 8px 12px;
  font-size: 12px;
`;

// Sources: a ghost toggle row over one answer-surface well listing them all.
const SourcesBlock = styled.div`
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  min-width: 0;
`;
const SourcesToggle = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  margin: 0 0 0 -10px;
  padding: 0 10px;
  border: none;
  border-radius: ${radii.sm};
  background-color: transparent;
  color: ${(props) => props.theme.mutedForeground};
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition: background-color 0.15s ease;

  &:hover {
    background-color: ${(props) => props.theme.accent};
  }

  .dgpt-sources-count {
    font-weight: 400;
    opacity: 0.7;
  }

  .dgpt-sources-chevron {
    transition: transform 0.15s ease;
  }

  &[aria-expanded='true'] .dgpt-sources-chevron {
    transform: rotate(90deg);
  }

  ${focusRing}
`;
const SourcesWell = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  box-sizing: border-box;
  width: 100%;
  margin-top: 8px;
  padding: 4px;
  border-radius: ${radii['2xl']};
  background-color: ${(props) => props.theme.answerSurface};
`;
const sourceRow = css`
  display: flex;
  align-items: flex-start;
  gap: 10px;
  box-sizing: border-box;
  min-width: 0;
  padding: 8px 12px;
  border-radius: ${radii.xl};
  color: ${(props) => props.theme.foreground};
  text-decoration: none;
  outline: none;
  transition:
    background-color 0.15s ease,
    box-shadow 0.15s ease;

  & > svg {
    flex-shrink: 0;
    margin-top: 2px;
    color: ${(props) => props.theme.mutedForeground};
  }

  &[data-highlighted='true'] {
    background-color: ${(props) => props.theme.accent};
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }

  &:focus-visible {
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }
`;
const SourceItem = styled.div`
  ${sourceRow}
`;
const SourceLink = styled.a`
  ${sourceRow}

  & > svg.dgpt-source-external {
    margin-top: 4px;
  }

  &:hover {
    background-color: ${(props) => props.theme.accent};
  }

  &:hover .dgpt-source-title {
    color: ${(props) => props.theme.primary};
    text-decoration: underline;
    text-underline-offset: 2px;
  }
`;
const SourceText = styled.span`
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;

  .dgpt-source-title {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 14px;
    line-height: 1.43;
  }

  .dgpt-source-detail {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    color: ${(props) => props.theme.mutedForeground};
    font-size: 12px;
    line-height: 1.33;
  }
`;

type Source = NonNullable<Query['sources']>[number];

const SourcesComponent = ({
  sources,
  turn,
  open,
  highlighted,
  onToggle,
}: {
  sources: Source[];
  /** The answer's index, which keys its rows for a citation to find. */
  turn: number;
  open: boolean;
  highlighted: number | null;
  onToggle: () => void;
}) => (
  <SourcesBlock>
    <SourcesToggle type="button" aria-expanded={open} onClick={onToggle}>
      <Database size={16} />
      <span>Sources</span>
      <span className="dgpt-sources-count">{sources.length}</span>
      <ChevronRight size={16} className="dgpt-sources-chevron" />
    </SourcesToggle>
    {open && (
      <SourcesWell>
        {sources.map((source, index) => {
          const key = `${turn}-${index}`;
          const isHighlighted = highlighted === index;
          // A file's `source` is its path in the library, which no visitor
          // can open; only a web source is a link.
          return isWebSource(source.source) ? (
            <SourceLink
              key={key}
              data-source={key}
              data-highlighted={isHighlighted}
              href={source.source}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Globe size={16} />
              <SourceText>
                <span className="dgpt-source-title">
                  {source.title || sourceHost(source.source)}
                </span>
                <span className="dgpt-source-detail">
                  {sourceHost(source.source)}
                </span>
              </SourceText>
              <ExternalLink size={12} className="dgpt-source-external" />
            </SourceLink>
          ) : (
            <SourceItem
              key={key}
              data-source={key}
              data-highlighted={isHighlighted}
              tabIndex={-1}
            >
              <FileText size={16} />
              <SourceText>
                <span className="dgpt-source-title">{source.title}</span>
                {source.text && (
                  <span className="dgpt-source-detail">{source.text}</span>
                )}
              </SourceText>
            </SourceItem>
          );
        })}
      </SourcesWell>
    )}
  </SourcesBlock>
);

const Hero = ({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon?: string;
}) => {
  return (
    <HeroContainer>
      <HeroWrapper>
        <AgentAvatar src={icon} size={48} fallback="mark" />
        <HeroText>
          <HeroTitle>{title}</HeroTitle>
          <HeroDescription>{description}</HeroDescription>
        </HeroText>
      </HeroWrapper>
    </HeroContainer>
  );
};
export const DocsGPTWidget = (props: WidgetProps) => {
  const {
    buttonIcon,
    buttonText = 'Ask a question',
    buttonBg,
    defaultOpen = false,
    ...coreProps
  } = props;

  const [open, setOpen] = React.useState<boolean>(defaultOpen);
  const [isFloatingButtonVisible, setIsFloatingButtonVisible] =
    React.useState(!defaultOpen);

  const handleClose = () => {
    setIsFloatingButtonVisible(true);
    setOpen(false);
  };
  const handleOpen = () => {
    setOpen(true);
    setIsFloatingButtonVisible(false);
  };
  return (
    <ThemeProvider theme={themes[coreProps.theme ?? 'dark']}>
      <FloatingButton
        type="button"
        $bg={buttonBg}
        onClick={handleOpen}
        $hidden={!isFloatingButtonVisible}
      >
        {buttonIcon ? (
          <img src={buttonIcon} alt="" />
        ) : (
          <MessageCircle size={20} />
        )}
        <span>{buttonText}</span>
      </FloatingButton>
      <WidgetCore isOpen={open} handleClose={handleClose} {...coreProps} />
    </ThemeProvider>
  );
};

export const WidgetCore = ({
  apiHost = 'https://gptcloud.arc53.com',
  apiKey = '527686a3-e867-4b4d-9fec-f5f45fdb613a',
  avatar,
  heroIcon,
  title = 'Get AI assistance',
  description = "DocsGPT's AI Chatbot is here to help",
  heroTitle = 'Welcome to DocsGPT !',
  heroDescription = 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.',
  size = 'medium',
  theme = 'dark',
  collectFeedback = true,
  isOpen = false,
  showSources = true,
  handleClose,
  prefilledQuery = '',
  allowedFileExtensions,
  showMicButton = false,
}: WidgetCoreProps) => {
  const [prompt, setPrompt] = React.useState<string>('');
  const [mounted, setMounted] = React.useState(false);
  const [status, setStatus] = React.useState<Status>('idle');
  const [queries, setQueries] = React.useState<Query[]>([]);
  const [conversationId, setConversationId] = React.useState<string | null>(
    null,
  );
  // Auto-follow the stream only while already near the bottom.
  const [isPinnedToLatest, setIsPinnedToLatest] = React.useState(true);
  const [isExpanded, setIsExpanded] = React.useState(false);
  const [copiedIndex, setCopiedIndex] = React.useState<number | null>(null);
  const [feedbackErrorIndex, setFeedbackErrorIndex] = React.useState<
    number | null
  >(null);
  const [isDraggingFiles, setIsDraggingFiles] = React.useState(false);
  // Answers whose sources list is open, by turn index.
  const [openSources, setOpenSources] = React.useState<Set<number>>(
    () => new Set(),
  );
  // The source a citation pill just opened.
  const [highlightedSource, setHighlightedSource] = React.useState<{
    turn: number;
    source: number;
  } | null>(null);
  const highlightTimerRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const endMessageRef = React.useRef<HTMLDivElement | null>(null);
  const promptRef = React.useRef<HTMLTextAreaElement | null>(null);
  const attachmentInputRef = React.useRef<HTMLInputElement | null>(null);
  // dragenter/dragleave fire per child crossed, hence a depth count.
  const dragDepthRef = React.useRef(0);

  // On a phone the composer waits to be tapped: autofocus costs half the
  // display to a keyboard nobody asked for.
  const [touchPrimary] = React.useState(isTouchPrimary);

  // Typed as a click handler, but no close path reads the event.
  const closePanel = () => {
    (handleClose as ((event?: React.MouseEvent) => void) | undefined)?.();
  };

  // The node exists only once mounted.
  useVisualViewportBounds(isOpen && mounted, containerRef);
  // Touch only: nothing fills the screen on desktop.
  useBackDismiss(isOpen && touchPrimary, closePanel);

  // An empty list disables attachments.
  const acceptedExtensions = React.useMemo(
    () => normalizeExtensions(allowedFileExtensions),
    [allowedFileExtensions],
  );
  const attachmentsEnabled = acceptedExtensions.length > 0;

  const {
    attachments,
    addFiles,
    remove: removeAttachment,
    clear: clearAttachments,
    pendingCount,
    failedCount,
    completed: completedAttachments,
  } = useAttachments({ apiKey, apiHost, acceptedExtensions });

  const resizePrompt = React.useCallback(() => {
    const el = promptRef.current;
    if (!el) return;
    const baseHeight = size === 'large' ? 64 : 48;
    const maxHeight = 140;
    el.style.height = 'auto';
    el.style.height = `${Math.max(
      baseHeight,
      Math.min(el.scrollHeight, maxHeight),
    )}px`;
  }, [size]);

  const getPromptDraft = React.useCallback(
    () => promptRef.current?.value ?? '',
    [],
  );

  const applyDraft = React.useCallback(
    (value: string) => {
      setPrompt(value);
      // The height can only be recomputed once React has committed.
      window.requestAnimationFrame(resizePrompt);
    },
    [resizePrompt],
  );

  const focusPrompt = React.useCallback(() => {
    window.requestAnimationFrame(() => promptRef.current?.focus());
  }, []);

  const dictation = useDictation({
    enabled: showMicButton,
    getDraft: getPromptDraft,
    onDraftChange: applyDraft,
    separator: '\n',
    onEnd: focusPrompt,
  });

  React.useEffect(() => {
    if (isOpen) {
      setMounted(true); // Mount the component
      appendQuery(prefilledQuery);
    } else {
      // Wait for animations before unmounting
      const timeout = setTimeout(() => {
        setMounted(false);
      }, 250);
      return () => clearTimeout(timeout);
    }
  }, [isOpen]);

  // Beyond this the reader is deliberately looking away.
  const STICK_THRESHOLD_PX = 48;

  const distanceFromBottom = (el: HTMLDivElement) =>
    el.scrollHeight - el.scrollTop - el.clientHeight;

  const scrollToLatest = (smooth = true) => {
    const el = conversationRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
    setIsPinnedToLatest(true);
  };

  // Explicit request: land immediately rather than easing.
  const jumpToLatest = () => scrollToLatest(false);

  const handleConversationScroll = () => {
    const el = conversationRef.current;
    if (!el) return;
    setIsPinnedToLatest(distanceFromBottom(el) < STICK_THRESHOLD_PX);
  };

  React.useEffect(() => {
    const el = conversationRef.current;
    if (!el || !isPinnedToLatest) return;
    // Easing per token never catches up, so jump while streaming.
    if (status === 'loading') el.scrollTop = el.scrollHeight;
    else scrollToLatest();
  }, [queries.length, queries[queries.length - 1]?.response, status]);

  // Shortening the panel leaves scrollTop where it was, dropping the tail of
  // the latest answer below the fold. A frame later, once the height lands.
  React.useEffect(() => {
    const viewport = window.visualViewport;
    if (!isOpen || !viewport) return;
    const repin = () =>
      window.requestAnimationFrame(() => {
        const el = conversationRef.current;
        if (el && isPinnedToLatest) el.scrollTop = el.scrollHeight;
      });
    viewport.addEventListener('resize', repin);
    return () => viewport.removeEventListener('resize', repin);
  }, [isOpen, isPinnedToLatest]);

  const setFeedbackAt = (index: number, value?: FEEDBACK) =>
    setQueries((prev: Query[]) =>
      prev.map((q, i) => {
        if (i !== index) return q;
        const updated = { ...q };
        if (value) updated.feedback = value;
        else delete updated.feedback;
        return updated;
      }),
    );

  async function handleFeedback(feedback: FEEDBACK, index: number) {
    const query = queries[index];
    if (!query.response || !conversationId) {
      console.log(
        'Cannot submit feedback: missing response or conversation ID',
      );
      return;
    }

    const previous = query.feedback;
    const next = previous === feedback ? undefined : feedback;

    setFeedbackAt(index, next);

    try {
      const response = await sendFeedback(
        {
          question: query.prompt,
          answer: query.response,
          feedback: next ?? null,
          apikey: apiKey,
          conversation_id: conversationId,
          question_index: index,
        },
        apiHost,
      );
      if (response.status !== 200) {
        throw new Error(`Feedback rejected with status ${response.status}`);
      }
    } catch (err) {
      console.warn('Feedback not saved:', err);
      setFeedbackAt(index, previous);
      setFeedbackErrorIndex(index);
      setTimeout(
        () => setFeedbackErrorIndex((cur) => (cur === index ? null : cur)),
        2600,
      );
    }
  }

  const stopGenerating = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus('idle');
  };

  async function stream(question: string, attachmentIds: string[] = []) {
    setStatus('loading');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await fetchAnswerStreaming({
        signal: controller.signal,
        question: question,
        apiKey: apiKey,
        apiHost: apiHost,
        history: queries,
        conversationId: conversationId,
        attachments: attachmentIds,
        onEvent: (event: MessageEvent) => {
          let data: StreamEvent;
          try {
            data = JSON.parse(event.data);
          } catch {
            // One malformed frame must not fail the whole turn.
            return;
          }

          const patch = (change: (query: Query) => void) => {
            setQueries((prev: Query[]) => {
              if (prev.length === 0) return prev;
              const updated = [...prev];
              const current = { ...updated[updated.length - 1] };
              change(current);
              updated[updated.length - 1] = current;
              return updated;
            });
          };

          const appendAnswer = (d: StreamEvent) => {
            if (typeof d.answer !== 'string') return;
            patch((query) => {
              query.response = (query.response ?? '') + d.answer;
            });
          };

          const noteToolCalls = (calls: unknown) => {
            const names = toolNames(calls);
            if (names.length === 0) return;
            patch((query) => {
              query.toolCalls = [
                ...new Set([...(query.toolCalls ?? []), ...names]),
              ];
            });
          };

          const handlers: Record<string, (d: StreamEvent) => void> = {
            answer: appendAnswer,
            end: () => setStatus('idle'),
            id: (d) => setConversationId(d.id as string),
            error: (d) => {
              patch((query) => {
                query.error = d.error as string;
              });
              setStatus('idle');
            },
            source: (d) => {
              if (!showSources) return;
              patch((query) => {
                query.sources = d.source as Query['sources'];
              });
            },
            thought: (d) =>
              patch((query) => {
                query.thought =
                  (query.thought ?? '') + ((d.thought as string) ?? '');
              }),
            notice: (d) =>
              patch((query) => {
                query.notice = (d.notice as string) ?? '';
              }),
            // Workflow agents report progress per node instead of `notice`.
            workflow_step: (d) => {
              const label = workflowStepLabel(d);
              if (label) {
                patch((query) => {
                  query.notice = label;
                });
              }
            },
            tool_calls: (d) => noteToolCalls(d.tool_calls),
            tool_call: (d) => noteToolCalls([d.data]),
            // Blocked content must leave the screen, reasoning included.
            guardrail: (d) => {
              if (!d.retract) return;
              patch((query) => {
                query.response = '';
                query.thought = '';
              });
            },
            // Recorded server-side; nothing to render.
            message_id: () => undefined,
          };

          // Unknown types are ignored; untyped frames are answer deltas.
          const handle = (data.type && handlers[data.type]) || appendAnswer;
          handle(data);
        },
      });
    } catch {
      const updatedQueries = [...queries];
      updatedQueries[updatedQueries.length - 1].error = CONNECTION_ERROR;
      setQueries(updatedQueries);
      setStatus('idle');
      //setEventInterrupt(false)
    }
  }

  const appendQuery = async (userQuery: string) => {
    if (!userQuery) return;

    // Only parsed attachments have a server id. The send is held until none
    // are pending, so this is the whole list.
    const sent: SentAttachment[] = completedAttachments.map((attachment) => ({
      id: attachment.attachmentId as string,
      fileName: attachment.fileName,
    }));

    setIsPinnedToLatest(true);
    queries.push({
      prompt: userQuery,
      attachments: sent.length > 0 ? sent : undefined,
    });
    setPrompt('');
    if (sent.length > 0) clearAttachments();
    await stream(
      userQuery,
      sent.map((attachment) => attachment.id),
    );
  };
  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(
        () => setCopiedIndex((cur) => (cur === index ? null : cur)),
        1600,
      );
    } catch (err) {
      console.warn('Copy failed:', err);
    }
  };

  const toggleSources = (turn: number) =>
    setOpenSources((prev) => {
      const next = new Set(prev);
      if (next.has(turn)) next.delete(turn);
      else next.add(turn);
      return next;
    });

  // The widget has no source reader: a pill opens the answer's sources,
  // brings the cited one into view and marks it for a moment.
  const openCitedSource = (turn: number, source: number) => {
    setOpenSources((prev) => (prev.has(turn) ? prev : new Set(prev).add(turn)));
    setHighlightedSource({ turn, source });
    if (highlightTimerRef.current !== null)
      window.clearTimeout(highlightTimerRef.current);
    highlightTimerRef.current = window.setTimeout(() => {
      setHighlightedSource(null);
      highlightTimerRef.current = null;
    }, SOURCE_HIGHLIGHT_MS);
    window.requestAnimationFrame(() => {
      const row = containerRef.current?.querySelector<HTMLElement>(
        `[data-source="${turn}-${source}"]`,
      );
      if (!row) return;
      row.scrollIntoView({
        block: 'nearest',
        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      });
      row.focus({ preventScroll: true });
    });
  };

  React.useEffect(
    () => () => {
      if (highlightTimerRef.current !== null)
        window.clearTimeout(highlightTimerRef.current);
    },
    [],
  );

  // The answer is injected HTML, so its pills and copy buttons are handled
  // here rather than by React.
  const handleAnswerClick =
    (turn: number) => (event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target as HTMLElement;
      const cite = target.closest<HTMLElement>('.dgpt-cite');
      if (cite) {
        const n = Number(cite.dataset.cite);
        if (Number.isInteger(n) && n > 0) openCitedSource(turn, n - 1);
        return;
      }
      const copy = target.closest<HTMLButtonElement>('.dgpt-code-copy');
      if (!copy) return;
      const code =
        copy.closest('.dgpt-code')?.querySelector('pre code')?.textContent ??
        '';
      navigator.clipboard
        .writeText(code)
        .then(() => {
          copy.classList.add('is-copied');
          copy.setAttribute('aria-label', 'Copied');
          window.setTimeout(() => {
            copy.classList.remove('is-copied');
            copy.setAttribute('aria-label', 'Copy code');
          }, 2000);
        })
        .catch((err) => console.warn('Copy failed:', err));
    };

  // Re-runs the turn in place instead of appending a duplicate prompt.
  const handleRetry = async (index: number) => {
    if (status === 'loading') return;
    const prompt = queries[index]?.prompt;
    if (!prompt) return;
    // The composer list is cleared on send, so retry reuses the row's ids.
    const attached = queries[index]?.attachments;
    setQueries((prev: Query[]) => {
      const updated = [...prev];
      updated[index] = { prompt, attachments: attached };
      return updated.slice(0, index + 1);
    });
    setIsPinnedToLatest(true);
    await stream(
      prompt,
      (attached ?? []).map((attachment) => attachment.id),
    );
  };

  // Pending and failed attachments both block sending. The pending note
  // takes precedence because it clears on its own.
  const pendingNote =
    pendingCount > 0
      ? `Waiting for ${pendingCount} file${pendingCount === 1 ? '' : 's'} to finish\u2026`
      : null;
  const failedNote =
    failedCount > 0
      ? 'Remove the file that could not be attached, then send.'
      : null;
  const sendBlockedReason = pendingNote ?? failedNote;
  const isDictating = dictation.isDictating;
  const canSubmit =
    prompt.trim().length > 0 &&
    !sendBlockedReason &&
    !isDictating &&
    status !== 'loading';

  const submitPrompt = async () => {
    if (!canSubmit) return;
    // Reset first, so the empty composer does not render tall for a frame.
    if (promptRef.current) promptRef.current.style.height = 'auto';
    await appendQuery(prompt);
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    await submitPrompt();
  };
  const handlePromptKeyDown = async (
    e: React.KeyboardEvent<HTMLTextAreaElement>,
  ) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      await submitPrompt();
    }
  };
  // Auto-resize the input textarea while typing, clamping to base or max height
  const handleUserInput = () => {
    resizePrompt();
  };

  // Update prompt state, auto resize textarea to content, and maintain scroll on new lines
  const handlePromptChange = (
    event: React.ChangeEvent<HTMLTextAreaElement>,
  ) => {
    const value = event.target.value;
    // A stale voice error would hide the attachment notice below.
    if (dictation.error) dictation.clearError();
    setPrompt(value);
    resizePrompt();
    if (value.includes('\n')) {
      const el = event.currentTarget;
      el.scrollTop = el.scrollHeight;
    }
  };

  const handleAttachmentPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    // Clear it or picking the same file twice fires no change event.
    e.target.value = '';
    if (files.length > 0) addFiles(files);
  };

  const handlePromptPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!attachmentsEnabled || isDictating) return;
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (let index = 0; index < items.length; index += 1) {
      if (items[index].kind !== 'file') continue;
      const file = items[index].getAsFile();
      if (file) files.push(file);
    }
    if (files.length === 0) return;
    // Keeps the file from also being pasted as text.
    e.preventDefault();
    addFiles(files);
  };

  // Ignore drags that carry no files, such as selected text.
  const isFileDrag = (e: React.DragEvent) =>
    Array.from(e.dataTransfer?.types ?? []).includes('Files');

  // Files cannot be attached while dictating.
  const acceptsFiles = attachmentsEnabled && !isDictating;

  const handleDragEnter = (e: React.DragEvent) => {
    if (!acceptsFiles || !isFileDrag(e)) return;
    dragDepthRef.current += 1;
    setIsDraggingFiles(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    if (!acceptsFiles || !isFileDrag(e)) return;
    // Without this the browser opens the file instead of dropping it.
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!acceptsFiles || !isFileDrag(e)) return;
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setIsDraggingFiles(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    if (!acceptsFiles) return;
    e.preventDefault();
    dragDepthRef.current = 0;
    setIsDraggingFiles(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length > 0) addFiles(files);
  };

  const renderStatusLine = (query: Query, index: number) => {
    if (status !== 'loading' || index !== queries.length - 1) return null;
    // A notice/node title is more specific than "Thinking", but goes stale
    // once tokens arrive.
    const label = query.response
      ? 'Generating\u2026'
      : (query.notice ?? 'Thinking\u2026');
    return (
      <StatusLine role="status" aria-live="polite">
        <StatusDot />
        <ShimmerText>{label}</ShimmerText>
      </StatusLine>
    );
  };

  // Neither feature enabled keeps the original single-row composer.
  const hasComposerControls = attachmentsEnabled || dictation.available;

  // Errors take precedence over the pending-upload note.
  const composerNote = dictation.error
    ? { text: dictation.error, tone: 'danger' as const }
    : sendBlockedReason
      ? {
          text: sendBlockedReason,
          tone: pendingNote ? undefined : ('danger' as const),
        }
      : null;

  const sendControl =
    status === 'loading' ? (
      <StyledButton
        type="button"
        onClick={stopGenerating}
        aria-label="Stop generating"
      >
        <StopGlyph />
      </StyledButton>
    ) : (
      <StyledButton
        disabled={!canSubmit}
        aria-label="Send message"
        title={sendBlockedReason ?? undefined}
      >
        <SendArrow size={16} />
      </StyledButton>
    );

  const baseDimensions =
    typeof size === 'object' && 'custom' in size
      ? sizesConfig.getCustom(size.custom)
      : sizesConfig[size];
  const canExpand = size !== 'large';
  const dimensions =
    canExpand && isExpanded
      ? expandedDimensions(baseDimensions)
      : baseDimensions;
  if (!mounted) return null;

  return (
    <ThemeProvider theme={{ ...themes[theme], dimensions }}>
      <InterFontFace />
      {isOpen && size === 'large' && <Overlay onClick={handleClose} />}
      {
        <WidgetContainer
          ref={containerRef}
          className={`${size !== 'large' ? (isOpen ? 'open' : 'close') : 'modal'}`}
          $modal={size === 'large'}
        >
          <StyledContainer
            $isOpen={isOpen}
            onDragEnter={handleDragEnter}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <Header>
              <AgentAvatar src={avatar} size={40} fallback="person" />
              <ContentWrapper>
                <Title>{title}</Title>
                <Description>{description}</Description>
              </ContentWrapper>
              <HeaderActions>
                {canExpand && (
                  <ExpandButton
                    type="button"
                    onClick={() => setIsExpanded((prev) => !prev)}
                    aria-label={isExpanded ? 'Collapse chat' : 'Expand chat'}
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? (
                      <Minimize2 size={16} />
                    ) : (
                      <Maximize2 size={16} />
                    )}
                  </ExpandButton>
                )}
                <IconButton
                  type="button"
                  onClick={handleClose}
                  aria-label="Close chat"
                >
                  <X size={16} />
                </IconButton>
              </HeaderActions>
            </Header>
            <ConversationArea>
              <Conversation
                ref={conversationRef}
                onScroll={handleConversationScroll}
              >
                {queries.length > 0 ? (
                  queries?.map((query, index) => {
                    const sources =
                      showSources && query.sources ? query.sources : [];
                    return (
                      <Turn key={index}>
                        {query.prompt && (
                          <MessageBubble $type="QUESTION">
                            {query.attachments &&
                              query.attachments.length > 0 && (
                                <SentAttachments
                                  attachments={query.attachments}
                                />
                              )}
                            <Message
                              $type="QUESTION"
                              ref={
                                !(query.response || query.error) &&
                                index === queries.length - 1
                                  ? endMessageRef
                                  : null
                              }
                            >
                              {query.prompt}
                            </Message>
                          </MessageBubble>
                        )}
                        {query.response ? (
                          <MessageBubble $type="ANSWER">
                            {sources.length > 0 && (
                              <SourcesComponent
                                sources={sources}
                                turn={index}
                                open={openSources.has(index)}
                                highlighted={
                                  highlightedSource?.turn === index
                                    ? highlightedSource.source
                                    : null
                                }
                                onToggle={() => toggleSources(index)}
                              />
                            )}
                            {query.toolCalls && query.toolCalls.length > 0 && (
                              <StatusLine>
                                Used{' '}
                                {query.toolCalls.map(prettifyName).join(', ')}
                              </StatusLine>
                            )}
                            <Message
                              $type="ANSWER"
                              ref={
                                index === queries.length - 1
                                  ? endMessageRef
                                  : null
                              }
                            >
                              <Markdown
                                onClick={handleAnswerClick(index)}
                                dangerouslySetInnerHTML={{
                                  __html: DOMPurify.sanitize(
                                    renderAnswer(query.response, {
                                      sourceCount: sources.length,
                                    }),
                                    { ADD_ATTR: ['target'] },
                                  ),
                                }}
                              />
                            </Message>
                            {renderStatusLine(query, index)}

                            <ActionsRow>
                              <ActionButton
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleCopy(query.response ?? '', index);
                                }}
                                aria-label={
                                  copiedIndex === index
                                    ? 'Copied'
                                    : 'Copy answer'
                                }
                                $copied={copiedIndex === index}
                              >
                                {copiedIndex === index ? (
                                  <Check size={16} />
                                ) : (
                                  <Copy size={16} />
                                )}
                              </ActionButton>

                              {collectFeedback && (
                                <>
                                  <ActionButton
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleFeedback('LIKE', index);
                                    }}
                                    aria-label="Good response"
                                    aria-pressed={query.feedback === 'LIKE'}
                                    $tone={
                                      query.feedback === 'LIKE'
                                        ? 'primary'
                                        : undefined
                                    }
                                  >
                                    <ThumbsUp size={16} />
                                  </ActionButton>
                                  <ActionButton
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleFeedback('DISLIKE', index);
                                    }}
                                    aria-label="Bad response"
                                    aria-pressed={query.feedback === 'DISLIKE'}
                                    $tone={
                                      query.feedback === 'DISLIKE'
                                        ? 'destructive'
                                        : undefined
                                    }
                                  >
                                    <ThumbsDown size={16} />
                                  </ActionButton>
                                </>
                              )}
                              {feedbackErrorIndex === index && (
                                <ActionHint role="status">
                                  Couldn&apos;t save
                                </ActionHint>
                              )}
                            </ActionsRow>
                          </MessageBubble>
                        ) : query.error ? (
                          <ErrorTurn>
                            <ErrorAlert role="alert">
                              <CircleAlert size={16} />
                              <ErrorTitle>
                                Couldn&apos;t generate a response
                              </ErrorTitle>
                              <ErrorText
                                $raw={query.error !== CONNECTION_ERROR}
                              >
                                {query.error}
                              </ErrorText>
                            </ErrorAlert>
                            <ActionsRow>
                              <ActionButton
                                type="button"
                                onClick={() => handleRetry(index)}
                                disabled={status === 'loading'}
                                aria-label="Retry"
                              >
                                <RotateCcw size={16} />
                              </ActionButton>
                              <ActionButton
                                type="button"
                                onClick={() =>
                                  handleCopy(query.error ?? '', index)
                                }
                                aria-label={
                                  copiedIndex === index
                                    ? 'Copied'
                                    : 'Copy error'
                                }
                                $copied={copiedIndex === index}
                              >
                                {copiedIndex === index ? (
                                  <Check size={16} />
                                ) : (
                                  <Copy size={16} />
                                )}
                              </ActionButton>
                            </ActionsRow>
                          </ErrorTurn>
                        ) : (
                          <MessageBubble $type="ANSWER">
                            {renderStatusLine(query, index)}
                          </MessageBubble>
                        )}
                      </Turn>
                    );
                  })
                ) : (
                  <Hero
                    title={heroTitle}
                    description={heroDescription}
                    icon={heroIcon}
                  />
                )}
              </Conversation>
              {!isPinnedToLatest && queries.length > 0 && (
                <ScrollToLatest
                  type="button"
                  onClick={jumpToLatest}
                  aria-label="Scroll to latest message"
                >
                  <ArrowDown size={16} />
                </ScrollToLatest>
              )}
            </ConversationArea>
            <Composer>
              {attachmentsEnabled && (
                <HiddenFileInput
                  ref={attachmentInputRef}
                  type="file"
                  multiple
                  accept={acceptAttribute(acceptedExtensions)}
                  onChange={handleAttachmentPick}
                />
              )}
              <PromptContainer
                onSubmit={handleSubmit}
                $stacked={hasComposerControls}
              >
                {attachments.length > 0 && (
                  <AttachmentChips
                    attachments={attachments}
                    onRemove={removeAttachment}
                  />
                )}
                <PromptRow>
                  {isDictating && (
                    <VoiceWaveform
                      analyserRef={dictation.analyserRef}
                      label={
                        dictation.state === 'recording'
                          ? 'Listening\u2026'
                          : 'Finishing\u2026'
                      }
                      minHeight={size === 'large' ? '64px' : '48px'}
                    />
                  )}
                  {/* Kept mounted so promptRef stays valid while dictating. */}
                  <StyledTextarea
                    $hidden={isDictating}
                    $stacked={hasComposerControls}
                    id="chatInput"
                    ref={promptRef}
                    autoFocus={!touchPrimary}
                    onInput={handleUserInput}
                    value={prompt}
                    onChange={handlePromptChange}
                    placeholder="Ask your question"
                    aria-label="Ask your question"
                    onKeyDown={handlePromptKeyDown}
                    onPaste={handlePromptPaste}
                    /* Typing would be overwritten by the next interim
                       revision. */
                    readOnly={isDictating}
                    rows={1}
                    wrap="soft"
                  />
                  {!hasComposerControls && sendControl}
                </PromptRow>
                {hasComposerControls && (
                  <ControlBar>
                    <ControlGroup>
                      {attachmentsEnabled && (
                        <AttachButton
                          onClick={() => attachmentInputRef.current?.click()}
                          disabled={isDictating}
                        />
                      )}
                      {dictation.available && (
                        <MicButton
                          state={dictation.state}
                          // Enabled while recording: it is how dictation stops.
                          disabled={
                            status === 'loading' && dictation.state === 'idle'
                          }
                          onClick={dictation.toggle}
                        />
                      )}
                    </ControlGroup>
                    {sendControl}
                  </ControlBar>
                )}
              </PromptContainer>
              {composerNote && (
                <ComposerNote
                  role={composerNote.tone === 'danger' ? 'alert' : 'status'}
                  $tone={composerNote.tone}
                >
                  {composerNote.text}
                </ComposerNote>
              )}
              <Tagline>
                Powered by&nbsp;
                <Hyperlink
                  target="_blank"
                  rel="noopener noreferrer"
                  href="https://www.docsgpt.cloud/"
                >
                  DocsGPT
                </Hyperlink>
              </Tagline>
            </Composer>
            {isDraggingFiles && (
              <DropOverlay>
                <DropTarget>
                  <CloudUpload size={16} />
                  Drop files to attach
                </DropTarget>
              </DropOverlay>
            )}
          </StyledContainer>
        </WidgetContainer>
      }
    </ThemeProvider>
  );
};

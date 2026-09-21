import 'styled-components';

declare module 'styled-components' {
  export interface DefaultTheme {
    bg: string;
    text: string;
    primary: {
      text: string;
      bg: string;
    };
    secondary: {
      text: string;
      bg: string;
    };
    /** Gradient stops for the swept status text. */
    shimmer?: {
      base: string;
      highlight: string;
    };
    accent?: {
      base: string;
      hover: string;
      strong: string;
      contrast: string;
      soft: string;
      /** Background behind a search keyword match. */
      mark: string;
      link: string;
    };
    hairline?: string;
    danger?: {
      text: string;
      soft: string;
      border: string;
    };
    /** Present only in DocsGPTWidget theme (always provided when these styled components render) */
    dimensions?: {
      size: string;
      width: string;
      height: string;
      maxWidth?: string;
      maxHeight?: string;
    };
  }
}

export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';

export type Status = 'idle' | 'loading' | 'failed';

export type FEEDBACK = 'LIKE' | 'DISLIKE';

export type AttachmentStatus =
  | 'uploading'
  | 'processing'
  | 'completed'
  | 'failed';

export interface Attachment {
  /** Client-side key for the chip; never sent to the server. */
  id: string;
  fileName: string;
  status: AttachmentStatus;
  /** Only meaningful while `status` is 'uploading'. */
  progress: number;
  /** Server-side id; what `/stream` expects in its `attachments` array. */
  attachmentId?: string;
  /** User-facing failure reason, if any. */
  error?: string;
}

export interface SentAttachment {
  id: string;
  fileName: string;
}

export type THEME = 'light' | 'dark';

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  error?: string;
  sources?: { title: string; text: string; source: string }[];
  conversationId?: string | null;
  title?: string | null;
  /** Accumulated from thought events. */
  thought?: string;
  /** Latest notice or running workflow node; drives the status line. */
  notice?: string;
  /** Tool names from tool_calls / tool_call. */
  toolCalls?: string[];
  /** Files sent with the question. */
  attachments?: SentAttachment[];
}

export interface WidgetProps {
  apiHost?: string;
  apiKey?: string;
  avatar?: string;
  title?: string;
  description?: string;
  heroTitle?: string;
  heroDescription?: string;
  size?:
    | 'small'
    | 'medium'
    | 'large'
    | {
        custom: {
          width: string;
          height: string;
          maxWidth?: string;
          maxHeight?: string;
        };
      };
  theme?: THEME;
  buttonIcon?: string;
  buttonText?: string;
  buttonBg?: string;
  collectFeedback?: boolean;
  showSources?: boolean;
  defaultOpen?: boolean;
  /**
   * File extensions the composer accepts, e.g. `['.pdf', '.md', '.png']`.
   * Attachments are disabled while unset. A leading dot is optional and
   * matching is case-insensitive.
   */
  allowedFileExtensions?: string[];
  /**
   * Show a microphone that dictates into the input via the browser's Web
   * Speech API. Hidden where the API is unavailable or the origin is
   * insecure. Outside Chromium builds with on-device recognition, audio is
   * sent to the browser vendor's speech service.
   */
  showMicButton?: boolean;
}
export interface WidgetCoreProps extends WidgetProps {
  widgetRef?: React.RefObject<HTMLDivElement> | null;
  handleClose?: React.MouseEventHandler | undefined;
  isOpen: boolean;
  prefilledQuery?: string;
}

/**
 * Both props are forwarded to the chat opened from "Ask the AI";
 * `showMicButton` also adds a microphone to the search field.
 */
export interface SearchBarProps extends Pick<
  WidgetProps,
  'allowedFileExtensions' | 'showMicButton'
> {
  apiHost?: string;
  apiKey?: string;
  theme?: THEME;
  placeholder?: string;
  width?: string;
  buttonText?: string;
}

export interface Result {
  text: string;
  title: string;
  source: string;
}

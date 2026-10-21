import 'styled-components';
import type { WidgetTheme } from '../components/tokens';
import type { Messages } from '../locale/en';
import type { SupportedLocale } from '../locale/index';

declare module 'styled-components' {
  export interface DefaultTheme extends WidgetTheme {
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
  'uploading' | 'processing' | 'completed' | 'failed';

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
  /** Set when `error` is the widget's own message, shown in the current locale. */
  errorKey?: 'connectionError' | 'interrupted';
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

/**
 * The credit line under the chat and the search results. `true` (the
 * default) shows "Powered by DocsGPT", `false` hides it, and an object
 * replaces it, e.g. `{ label: 'Powered by Acme', href: 'https://acme.com' }`.
 */
export type PoweredBy = boolean | { label: string; href?: string };

/** A value sent in `passthrough`: nested objects and arrays are dropped by the server. */
export type PassthroughValue = string | number | boolean | null;

/** Language and text options shared by the widget and the search bar. */
export interface LocaleProps {
  // `string & {}` keeps editor suggestions for the known codes.
  /**
   * UI language: `'auto'` (the default) follows the visitor's browser, or one
   * of `en`, `es`, `fr`, `ja`, `zh`, `zh-TW`, `ru`, `de`. Anything else is
   * English. Text set through other props is never translated.
   */
  locale?: SupportedLocale | 'auto' | (string & {});
  /** Replaces individual UI strings, e.g. `{ composerPlaceholder: 'Ask us' }`. */
  translations?: Partial<Messages>;
}

export interface WidgetProps extends LocaleProps {
  apiHost?: string;
  apiKey?: string;
  /** Image in the header. Without one, a person on the brand circle. */
  avatar?: string;
  /** Image on the empty-state card. Without one, the DocsGPT mark. */
  heroIcon?: string;
  title?: string;
  description?: string;
  heroTitle?: string;
  heroDescription?: string;
  /**
   * Questions listed under the welcome card before the first message. A click
   * sends the question. Blank entries are skipped.
   */
  suggestedQuestions?: string[];
  /** Heading over `suggestedQuestions`; an empty string hides it. */
  suggestedQuestionsLabel?: string;
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
  /**
   * `'floating'` (the default) opens a panel above the launcher; `'sidebar'`
   * docks a full-height panel to the window's edge, over the page. `size`
   * doesn't apply to the sidebar. Below 769px wide both go full screen.
   */
  layout?: 'floating' | 'sidebar';
  /** The edge the sidebar docks to. Default `'right'`. */
  sidebarSide?: 'left' | 'right';
  /**
   * The sidebar's width in pixels before the visitor resizes it, between 320
   * and `min(720, 70vw)`. Default 420. The visitor's width is remembered
   * unless `persistConversations` is false.
   */
  sidebarWidth?: number;
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
  poweredBy?: PoweredBy;
  /**
   * Values sent with every question, e.g. `{ user_id: 'emp-42' }`. The agent's
   * prompt reads them as `{{ passthrough.user_id }}`, and its owner sees them on
   * each turn in Logs. Set by the embedding page, so treat them as unverified.
   */
  passthrough?: Record<string, PassthroughValue>;
  /**
   * Keep the visitor's conversations in this browser's `localStorage`, so a
   * reload continues the chat and earlier ones are listed under History.
   * `false` stores nothing and removes what an earlier visit stored.
   */
  persistConversations?: boolean;
  /**
   * Called with every event the chat fires, e.g. to send them to analytics.
   * `ref` and the controller's `on()` reach the same events.
   */
  onEvent?: (event: WidgetEvent) => void;
}

/** What `WidgetCore` exposes to whatever owns its open state. */
export interface WidgetCoreHandle {
  ask: (question: string, send: boolean) => void;
  focus: () => void;
  newChat: () => void;
  clearHistory: () => void;
}

export interface WidgetCoreProps extends WidgetProps {
  widgetRef?: React.RefObject<HTMLDivElement> | null;
  handleClose?: React.MouseEventHandler | undefined;
  isOpen: boolean;
  prefilledQuery?: string;
  coreRef?: React.Ref<WidgetCoreHandle>;
  /** Takes focus when the panel closes with focus inside it. */
  returnFocusRef?: React.RefObject<HTMLElement | null>;
  /** A one-off chat: stored conversations are neither read, written nor removed. */
  ephemeral?: boolean;
}

/**
 * `allowedFileExtensions`, `showMicButton` and `onEvent` are forwarded to the
 * chat opened from "Ask the AI"; `showMicButton` also adds a microphone to the
 * search field.
 */
export interface SearchBarProps extends Pick<
  WidgetProps,
  | 'allowedFileExtensions'
  | 'showMicButton'
  | 'avatar'
  | 'poweredBy'
  | 'passthrough'
  | 'locale'
  | 'translations'
  | 'onEvent'
> {
  apiHost?: string;
  apiKey?: string;
  theme?: THEME;
  placeholder?: string;
  width?: string;
  buttonText?: string;
  /** `pill` (default) or `rounded`, the app's 8px field corners. */
  shape?: 'pill' | 'rounded';
  /**
   * `modal` (default) opens a search dialog from a button; `dropdown` is a
   * field you type into, with the results in a panel under it.
   */
  variant?: 'modal' | 'dropdown';
}

export interface Result {
  text: string;
  title: string;
  source: string;
}

/** How a question reached the chat. */
export type QuestionSource =
  /** Typed in the composer. */
  | 'composer'
  /** One of `suggestedQuestions`. */
  | 'suggestion'
  /** The controller's `ask()`. */
  | 'api'
  /** "Ask the AI" in the search bar. */
  | 'search'
  /** The retry button on a failed answer. */
  | 'retry';

/** A source an answer drew on; `url` is set for web pages only. */
export interface AnswerSource {
  title: string;
  url?: string;
}

/**
 * Something the visitor did in the chat, or that happened to an answer.
 * `conversationId` is the server's id for the chat. It is null until the
 * server assigns one as the first answer starts, so the first
 * `question_submitted` has null.
 */
export type WidgetEvent = { conversationId: string | null } & (
  | { type: 'open' }
  | { type: 'close' }
  | { type: 'question_submitted'; question: string; source: QuestionSource }
  | {
      type: 'answer_completed';
      question: string;
      answer: string;
      sources: AnswerSource[];
    }
  | { type: 'answer_failed'; question: string; error: string }
  | { type: 'answer_stopped'; question: string }
  | {
      type: 'feedback';
      question: string;
      answer: string;
      /** The rating now saved; null when the visitor took theirs back. */
      value: 'like' | 'dislike' | null;
    }
  | { type: 'source_clicked'; title: string; url: string }
  | { type: 'answer_copied'; question: string; answer: string }
  | {
      type: 'code_copied';
      question: string;
      code: string;
      /** The code block's language, `text` when it has none. */
      language: string;
    }
  /** The chat was emptied; `conversationId` is the conversation left behind. */
  | { type: 'new_chat' }
  /** A saved conversation was shown again, on load or from History. */
  | { type: 'conversation_restored' }
  /** Everything stored for this agent was removed. */
  | { type: 'history_cleared' }
);

export type WidgetEventType = WidgetEvent['type'];

/** The event with the given `type`. */
export type WidgetEventOf<T extends WidgetEventType> = Extract<
  WidgetEvent,
  { type: T }
>;

export type WidgetEventHandler<T extends WidgetEventType = WidgetEventType> = (
  event: WidgetEventOf<T>,
) => void;

export interface AskOptions {
  /** Send right away (the default), or only put the question in the composer. */
  send?: boolean;
}

/**
 * Drives the widget from the host page: `renderDocsGPTWidget` returns one,
 * and `DocsGPTWidget` hands one to its `ref`.
 */
export interface WidgetController {
  open: () => void;
  close: () => void;
  toggle: () => void;
  isOpen: () => boolean;
  /** Opens the panel and focuses the message field. */
  focus: () => void;
  /**
   * Opens the panel and sends `question`. When the composer couldn't send
   * either (an answer is streaming, a file is uploading, the mic is on), or
   * with `{ send: false }`, the question is put in the composer instead.
   */
  ask: (question: string, options?: AskOptions) => void;
  /** Subscribes to one event type; returns a function that unsubscribes. */
  on: <T extends WidgetEventType>(
    type: T,
    handler: WidgetEventHandler<T>,
  ) => () => void;
  off: <T extends WidgetEventType>(
    type: T,
    handler: WidgetEventHandler<T>,
  ) => void;
  /** Empties the chat, stopping an answer that is still streaming. */
  newChat: () => void;
  /**
   * Removes every conversation stored for this agent in this browser, then
   * starts a new chat. Call it on logout where computers are shared.
   */
  clearHistory: () => void;
}

/** What `renderDocsGPTWidget` returns. */
export interface WidgetInstance extends WidgetController {
  /** Unmounts the widget and drops every handler. Safe to call twice. */
  destroy: () => void;
}

/** What `renderSearchBar` returns. */
export interface SearchBarInstance {
  /** Unmounts the search bar. Safe to call twice. */
  destroy: () => void;
}

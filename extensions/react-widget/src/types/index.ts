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
    /** Present only in SearchBar theme */
    name?: string;
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

export type THEME = 'light' | 'dark';

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  error?: string;
  sources?: { title: string; text: string; source: string }[];
  conversationId?: string | null;
  title?: string | null;
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
}
export interface WidgetCoreProps extends WidgetProps {
  widgetRef?: React.RefObject<HTMLDivElement> | null;
  handleClose?: React.MouseEventHandler | undefined;
  isOpen: boolean;
  prefilledQuery?: string;
}

export interface SearchBarProps {
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

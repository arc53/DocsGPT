import { css } from 'styled-components';

/**
 * Colour tokens shared by the chat widget and the search bar. Names and values
 * mirror the app's theme (`frontend/src/index.css`, `:root` and `.dark`); the
 * `/NN` shares the app writes as Tailwind opacity modifiers are spelled out as
 * rgba here.
 */
export const themes = {
  light: {
    background: '#ffffff',
    foreground: '#171717',
    card: '#ffffff',
    muted: '#f6f6f6',
    mutedForeground: '#6b6b6b',
    accent: '#ececec',
    border: '#d9d9d9',
    /** `dark:bg-input/30`; light outline buttons sit on the background. */
    controlFill: '#ffffff',
    controlHover: '#ececec',
    primary: '#7d54d1',
    /** primary/90 */
    primaryHover: 'rgba(125, 84, 209, 0.9)',
    primaryForeground: '#ffffff',
    secondary: 'rgba(125, 84, 209, 0.1)',
    /** secondary/80 */
    secondaryHover: 'rgba(125, 84, 209, 0.08)',
    secondaryForeground: '#7d54d1',
    destructive: '#ef4444',
    destructiveForeground: '#ffffff',
    /** destructive/10 */
    destructiveSoft: 'rgba(239, 68, 68, 0.1)',
    /** destructive/50 */
    destructiveBorder: 'rgba(239, 68, 68, 0.5)',
    /** destructive/20, the app's destructiveRing */
    destructiveRing: 'rgba(239, 68, 68, 0.2)',
    ring: '#7d54d1',
    /** ring/50 */
    ringSoft: 'rgba(125, 84, 209, 0.5)',
    answerSurface: '#f6f6f6',
    scrollbarThumb: '#e2e8f0',
    /** The empty composer's send button: muted. */
    sendIdle: '#f6f6f6',
    /** The swept status text: muted-foreground with a border-coloured sweep. */
    shimmer: {
      base: '#6b6b6b',
      highlight: '#d9d9d9',
    },
    /** The app's Prism theme (oneLight) behind fenced code. */
    code: {
      background: 'hsl(230, 1%, 98%)',
      text: 'hsl(230, 8%, 24%)',
      comment: 'hsl(230, 4%, 64%)',
      keyword: 'hsl(301, 63%, 40%)',
      string: 'hsl(119, 34%, 47%)',
      number: 'hsl(35, 99%, 36%)',
      function: 'hsl(221, 87%, 60%)',
      operator: 'hsl(221, 87%, 60%)',
      property: 'hsl(5, 74%, 59%)',
      className: 'hsl(35, 99%, 36%)',
      variable: 'hsl(221, 87%, 60%)',
    },
  },
  dark: {
    background: '#222327',
    foreground: '#fafafa',
    card: '#2b2c31',
    muted: '#35363b',
    mutedForeground: '#a1a1a1',
    accent: '#3e3f45',
    border: '#44454c',
    /** input/30 and input/50 over the card */
    controlFill: 'rgba(68, 69, 76, 0.3)',
    controlHover: 'rgba(68, 69, 76, 0.5)',
    primary: '#8855f1',
    primaryHover: 'rgba(136, 85, 241, 0.9)',
    primaryForeground: '#ffffff',
    secondary: 'rgba(151, 106, 243, 0.15)',
    secondaryHover: 'rgba(151, 106, 243, 0.12)',
    secondaryForeground: '#b89cf8',
    destructive: '#dc2626',
    destructiveForeground: '#ffffff',
    destructiveSoft: 'rgba(220, 38, 38, 0.1)',
    destructiveBorder: 'rgba(220, 38, 38, 0.5)',
    /** destructive/40 in dark */
    destructiveRing: 'rgba(220, 38, 38, 0.4)',
    ring: '#976af3',
    ringSoft: 'rgba(151, 106, 243, 0.5)',
    answerSurface: '#2e303e',
    scrollbarThumb: '#949494',
    /** accent in dark, where muted would vanish into the card. */
    sendIdle: '#3e3f45',
    shimmer: {
      base: '#a1a1a1',
      highlight: '#fafafa',
    },
    /** vscDarkPlus */
    code: {
      background: '#1e1e1e',
      text: '#d4d4d4',
      comment: '#6a9955',
      keyword: '#569cd6',
      string: '#ce9178',
      number: '#b5cea8',
      function: '#dcdcaa',
      operator: '#d4d4d4',
      property: '#9cdcfe',
      className: '#4ec9b0',
      variable: '#9cdcfe',
    },
  },
};

export type WidgetTheme = (typeof themes)['light'];

/** Corner radii: the app's Tailwind steps. */
export const radii = {
  /** rounded-sm */
  sm: '6px',
  /** rounded-md */
  md: '8px',
  /** rounded-xl */
  xl: '14px',
  /** rounded-2xl */
  '2xl': '18px',
  /** rounded-3xl */
  '3xl': '22px',
  full: '9999px',
};

/** Tailwind's shadow scale plus the app's modal shadow. */
export const shadows = {
  xs: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
  md: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1)',
  lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1)',
  modal: '0 4px 40px -3px rgba(0, 0, 0, 0.1)',
};

export const fonts = {
  sans: "'DocsGPT Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  mono: "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace",
};

/** The app's keyboard ring (`focus-visible:ring-3 ring-ring/50`). */
export const focusRing = css`
  outline: none;

  &:focus-visible {
    box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
  }
`;

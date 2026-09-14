/** Colour tokens shared by the chat widget and the search bar. */
export const themes = {
  dark: {
    bg: '#222327',
    text: '#fff',
    primary: {
      text: '#FAFAFA',
      bg: '#222327',
    },
    secondary: {
      text: '#A1A1AA',
      bg: '#33343A',
    },
    shimmer: {
      base: '#A1A1AA',
      highlight: '#FAFAFA',
    },
    accent: {
      base: '#8860DB',
      hover: '#9B7BE4',
      strong: '#6D42C5',
      contrast: '#FFFFFF',
      soft: 'rgba(136, 96, 219, 0.18)',
      mark: 'rgba(136, 96, 219, 0.18)',
      link: '#A78BFA',
    },
    hairline: 'rgba(255, 255, 255, 0.08)',
    danger: {
      text: '#F87171',
      soft: 'rgba(248, 113, 113, 0.10)',
      border: 'rgba(248, 113, 113, 0.32)',
    },
  },
  light: {
    bg: '#fff',
    text: '#000',
    primary: {
      text: '#222327',
      bg: '#fff',
    },
    secondary: {
      text: '#71717A',
      bg: '#F4F4F5',
    },
    shimmer: {
      base: '#71717A',
      highlight: '#D4D4D8',
    },
    accent: {
      base: '#8860DB',
      hover: '#7A4FD0',
      strong: '#6D42C5',
      contrast: '#FFFFFF',
      soft: 'rgba(136, 96, 219, 0.12)',
      mark: 'rgba(136, 96, 219, 0.26)',
      link: '#6D42C5',
    },
    hairline: 'rgba(0, 0, 0, 0.08)',
    danger: {
      text: '#B91C1C',
      soft: 'rgba(185, 28, 28, 0.06)',
      border: 'rgba(185, 28, 28, 0.24)',
    },
  },
};

/** Corner radii shared by the widget's chrome. */
export const radii = {
  sm: '8px',
  md: '12px',
  lg: '18px',
  panel: '16px',
  full: '9999px',
};

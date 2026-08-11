import React from 'react';

type SpinnerProps = {
  size?: 'small' | 'medium' | 'large';
};

const SIZE_MAP: Record<NonNullable<SpinnerProps['size']>, string> = {
  small: '20px',
  medium: '30px',
  large: '40px',
};

export default function Spinner({ size = 'medium' }: SpinnerProps) {
  const spinnerSize = SIZE_MAP[size];

  const spinnerStyle: React.CSSProperties = {
    width: spinnerSize,
    height: spinnerSize,
    aspectRatio: '1',
    borderRadius: '50%',
    background: `
      radial-gradient(farthest-side, currentColor 94%, transparent) top/8px 8px no-repeat,
      conic-gradient(transparent 30%, currentColor)
    `,
    WebkitMask:
      'radial-gradient(farthest-side, transparent calc(100% - 8px), #000 0)',
    mask: 'radial-gradient(farthest-side, transparent calc(100% - 8px), #000 0)',
    animation: 'spinner-rotate 1s infinite linear',
    color: 'currentColor',
  };

  return <div className="loader" role="status" style={spinnerStyle} />;
}

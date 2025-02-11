import React from 'react';

type SpinnerProps = {
  size?: 'small' | 'medium' | 'large';
  color?: string;
};

export default function Spinner({
  size = 'medium',
  color = 'grey',
}: SpinnerProps) {
  const sizeMap = {
    small: '20px',
    medium: '30px',
    large: '40px',
  };
  const spinnerSize = sizeMap[size];

  const spinnerStyle = {
    width: spinnerSize,
    height: spinnerSize,
    aspectRatio: '1',
    borderRadius: '50%',
    background: `
      radial-gradient(farthest-side, ${color} 94%, #0000) top/8px 8px no-repeat,
      conic-gradient(#0000 30%, ${color})
    `,
    WebkitMask:
      'radial-gradient(farthest-side, #0000 calc(100% - 8px), #000 0)',
    animation: 'l13 1s infinite linear',
  } as React.CSSProperties;

  const keyframesStyle = `@keyframes l13 {
    100% { transform: rotate(1turn) }
  }`;

  return (
    <>
      <style>{keyframesStyle}</style>
      <div className="loader" style={spinnerStyle} />
    </>
  );
}

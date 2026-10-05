/**
 * Icons vendored from lucide (https://lucide.dev), ISC licence:
 * Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as
 * part of Feather (MIT). All other copyright (c) for Lucide are held by
 * Lucide Contributors 2022.
 *
 * Copied rather than depending on lucide-react: the npm build keeps
 * dependencies external, so every embedder would install it.
 */
import React from 'react';

type IconNode = [string, Record<string, string>][];

type IconProps = Omit<React.SVGProps<SVGSVGElement>, 'ref'> & {
  size?: number;
};

const makeIcon = (node: IconNode, displayName: string) => {
  const Icon = ({ size = 16, ...props }: IconProps) => (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {node.map(([tag, attrs], index) =>
        React.createElement(tag, { key: index, ...attrs }),
      )}
    </svg>
  );
  Icon.displayName = displayName;
  return Icon;
};

export const ArrowDown = makeIcon(
  [
    ['path', { d: 'M12 5v14' }],
    ['path', { d: 'm19 12-7 7-7-7' }],
  ],
  'ArrowDown',
);
export const Check = makeIcon([['path', { d: 'M20 6 9 17l-5-5' }]], 'Check');
export const ChevronRight = makeIcon(
  [['path', { d: 'm9 18 6-6-6-6' }]],
  'ChevronRight',
);
export const CircleAlert = makeIcon(
  [
    ['circle', { cx: '12', cy: '12', r: '10' }],
    ['line', { x1: '12', x2: '12', y1: '8', y2: '12' }],
    ['line', { x1: '12', x2: '12.01', y1: '16', y2: '16' }],
  ],
  'CircleAlert',
);
export const CloudUpload = makeIcon(
  [
    ['path', { d: 'M12 13v8' }],
    ['path', { d: 'M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242' }],
    ['path', { d: 'm8 17 4-4 4 4' }],
  ],
  'CloudUpload',
);
export const Copy = makeIcon(
  [
    ['rect', { width: '14', height: '14', x: '8', y: '8', rx: '2', ry: '2' }],
    ['path', { d: 'M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2' }],
  ],
  'Copy',
);
export const Database = makeIcon(
  [
    ['ellipse', { cx: '12', cy: '5', rx: '9', ry: '3' }],
    ['path', { d: 'M3 5V19A9 3 0 0 0 21 19V5' }],
    ['path', { d: 'M3 12A9 3 0 0 0 21 12' }],
  ],
  'Database',
);
export const ExternalLink = makeIcon(
  [
    ['path', { d: 'M15 3h6v6' }],
    ['path', { d: 'M10 14 21 3' }],
    ['path', { d: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6' }],
  ],
  'ExternalLink',
);
export const FileText = makeIcon(
  [
    [
      'path',
      {
        d: 'M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z',
      },
    ],
    ['path', { d: 'M14 2v5a1 1 0 0 0 1 1h5' }],
    ['path', { d: 'M10 9H8' }],
    ['path', { d: 'M16 13H8' }],
    ['path', { d: 'M16 17H8' }],
  ],
  'FileText',
);
export const Globe = makeIcon(
  [
    ['circle', { cx: '12', cy: '12', r: '10' }],
    ['path', { d: 'M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20' }],
    ['path', { d: 'M2 12h20' }],
  ],
  'Globe',
);
export const LoaderCircle = makeIcon(
  [['path', { d: 'M21 12a9 9 0 1 1-6.219-8.56' }]],
  'LoaderCircle',
);
export const Maximize2 = makeIcon(
  [
    ['path', { d: 'M15 3h6v6' }],
    ['path', { d: 'm21 3-7 7' }],
    ['path', { d: 'm3 21 7-7' }],
    ['path', { d: 'M9 21H3v-6' }],
  ],
  'Maximize2',
);
export const MessageCircle = makeIcon(
  [
    [
      'path',
      {
        d: 'M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092 10 10 0 1 0-4.777-4.719',
      },
    ],
  ],
  'MessageCircle',
);
export const Mic = makeIcon(
  [
    ['path', { d: 'M12 19v3' }],
    ['path', { d: 'M19 10v2a7 7 0 0 1-14 0v-2' }],
    ['rect', { x: '9', y: '2', width: '6', height: '13', rx: '3' }],
  ],
  'Mic',
);
export const Minimize2 = makeIcon(
  [
    ['path', { d: 'm14 10 7-7' }],
    ['path', { d: 'M20 10h-6V4' }],
    ['path', { d: 'm3 21 7-7' }],
    ['path', { d: 'M4 14h6v6' }],
  ],
  'Minimize2',
);
export const Paperclip = makeIcon(
  [
    [
      'path',
      {
        d: 'm16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551',
      },
    ],
  ],
  'Paperclip',
);
export const RotateCcw = makeIcon(
  [
    ['path', { d: 'M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8' }],
    ['path', { d: 'M3 3v5h5' }],
  ],
  'RotateCcw',
);
export const Square = makeIcon(
  [['rect', { width: '18', height: '18', x: '3', y: '3', rx: '2' }]],
  'Square',
);
export const ThumbsDown = makeIcon(
  [
    [
      'path',
      {
        d: 'M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z',
      },
    ],
    ['path', { d: 'M17 14V2' }],
  ],
  'ThumbsDown',
);
export const ThumbsUp = makeIcon(
  [
    [
      'path',
      {
        d: 'M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z',
      },
    ],
    ['path', { d: 'M7 10v12' }],
  ],
  'ThumbsUp',
);
export const X = makeIcon(
  [
    ['path', { d: 'M18 6 6 18' }],
    ['path', { d: 'm6 6 12 12' }],
  ],
  'X',
);

/** The app's send arrow (`frontend/src/assets/send.svg`), filled. */
export const SendArrow = ({ size = 16, ...props }: IconProps) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width={(size * 11) / 14}
    height={size}
    viewBox="0 0 11 14"
    fill="currentColor"
    aria-hidden="true"
    focusable="false"
    {...props}
  >
    <path d="M0.292786 6.20676C0.105315 6.01923 0 5.76492 0 5.49976C0 5.23459 0.105315 4.98028 0.292786 4.79276L4.79279 0.292756C4.98031 0.105284 5.23462 0 5.49979 0C5.76495 0 6.01926 0.105284 6.20679 0.292756L10.7068 4.79276C10.8889 4.98136 10.9897 5.23396 10.9875 5.49616C10.9852 5.75835 10.88 6.00917 10.6946 6.19457C10.5092 6.37998 10.2584 6.48515 9.99619 6.48743C9.73399 6.48971 9.48139 6.38891 9.29279 6.20676L6.49979 3.49976L6.49979 12.9998C6.49979 13.265 6.39443 13.5193 6.20689 13.7069C6.01936 13.8944 5.765 13.9998 5.49979 13.9998C5.23457 13.9998 4.98022 13.8944 4.79268 13.7069C4.60514 13.5193 4.49979 13.265 4.49979 12.9998L4.49979 3.49976L1.70679 6.20676C1.51926 6.39423 1.26495 6.49954 0.999786 6.49954C0.734622 6.49954 0.480314 6.39423 0.292786 6.20676Z" />
  </svg>
);

/** The DocsGPT mark (`frontend/src/assets/logo-w.svg`), in currentColor. */
export const DocsGPTMark = ({ size = 22, ...props }: IconProps) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width={size}
    height={(size * 169.38) / 233.35}
    viewBox="0 0 233.35 169.38"
    fill="currentColor"
    aria-hidden="true"
    focusable="false"
    {...props}
  >
    <path d="Layer_2" />
    <path d="Layer_1-2" />
    <path d="M226.85,50.84c-4.34-10.28-10.44-19.23-18.31-26.86-7.87-7.63-17.19-13.53-27.95-17.71-10.76-4.18-22.41-6.26-34.94-6.26h-66.02v140.35c-7.6.66-15.04.42-22.33-.75-11.32-1.82-21.64-5.63-30.94-11.42-9.3-5.79-17.17-13.29-23.6-22.5-.82-1.17-1.61-2.37-2.37-3.59h-.4c1.08,5.74,2.73,11.25,4.93,16.51,4.34,10.36,10.44,19.36,18.31,26.99,7.87,7.63,17.15,13.53,27.83,17.71,8.93,3.49,18.46,5.52,28.56,6.09h0s22.41,0,22.41,0h44.09c12.37,0,23.89-2.09,34.57-6.26,10.68-4.17,19.96-10.08,27.83-17.71,7.87-7.63,13.97-16.62,18.31-26.99,4.34-10.36,6.51-21.64,6.51-33.85s-2.17-23.45-6.51-33.73ZM193,113.84c-4.58,8.43-11,14.94-19.28,19.52-8.27,4.58-17.79,6.87-28.55,6.87h-32.77V29.15h32.77c10.76,0,20.24,2.33,28.43,6.99,8.19,4.66,14.61,11.08,19.28,19.28,4.66,8.19,6.99,17.83,6.99,28.91s-2.29,21.08-6.87,29.52Z" />
    <path d="M19.41,117.55c.49.42,1.27.42,1.97,0h0c.7-.43,1.19-1.21,1.22-1.97l.37-7.84c.05-1.03-.73-1.68-1.74-1.47l-3.36.72-4.21.9c-.73.16-1.42.75-1.74,1.5v.02c-.33.75-.21,1.52.28,1.94l7.21,6.21Z" />
    <path d="M28.73,123.56l11.41,5.35c.78.37,1.8,0,2.6-.9.8-.92,1.2-2.22,1.02-3.29l-1.88-11.08c-.25-1.45-1.47-2.01-2.74-1.25l-4.23,2.53-5.29,3.17c-.92.55-1.65,1.68-1.84,2.87v.03c-.2,1.19.18,2.21.96,2.57Z" />
    <path d="M50.47,130.26c.28,1.59,1.21,2.71,2.36,2.83l16.8,1.72c1.15.12,2.29-.79,2.88-2.29h0c.6-1.52.54-3.34-.16-4.62l-7.28-13.18c-.95-1.72-2.75-1.89-4.02-.37l-4.23,5.07-5.29,6.35c-.92,1.11-1.34,2.86-1.06,4.45v.04Z" />
  </svg>
);

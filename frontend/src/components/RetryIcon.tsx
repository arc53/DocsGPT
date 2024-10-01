import * as React from 'react';
import { SVGProps } from 'react';
const RetryIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    xmlSpace="preserve"
    width={16}
    height={16}
    fill={props.fill}
    stroke={props.stroke}
    viewBox="0 0 383.748 383.748"
    {...props}
  >
    <path d="M62.772 95.042C90.904 54.899 137.496 30 187.343 30c83.743 0 151.874 68.13 151.874 151.874h30C369.217 81.588 287.629 0 187.343 0c-35.038 0-69.061 9.989-98.391 28.888a182.423 182.423 0 0 0-47.731 44.705L2.081 34.641v113.365h113.91L62.772 95.042zM381.667 235.742h-113.91l53.219 52.965c-28.132 40.142-74.724 65.042-124.571 65.042-83.744 0-151.874-68.13-151.874-151.874h-30c0 100.286 81.588 181.874 181.874 181.874 35.038 0 69.062-9.989 98.391-28.888a182.443 182.443 0 0 0 47.731-44.706l39.139 38.952V235.742z" />
  </svg>
);
export default RetryIcon;

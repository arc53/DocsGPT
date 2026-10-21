import React from 'react';
import styled from 'styled-components';

import { useMessages } from '../locale/context';
import type { PoweredBy as PoweredByProp } from '../types/index';
import { DocsGPTMark } from './icons';
import { focusRing, radii } from './tokens';

const AvatarImage = styled.img<{ $size: number }>`
  width: ${(props) => props.$size}px;
  height: ${(props) => props.$size}px;
  flex-shrink: 0;
  border-radius: ${radii.full};
  object-fit: cover;
`;

// A white glyph on the brand circle: the stand-in when no image is set.
export const AvatarMark = styled.span<{ $size: number }>`
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
export const AgentAvatar = ({
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

const DOCSGPT_URL = 'https://www.docsgpt.cloud/';

const Credit = styled.div`
  box-sizing: border-box;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.5;
  text-align: center;
  color: ${(props) => props.theme.mutedForeground};
`;

const CreditLink = styled.a`
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

/**
 * The credit line under the chat and the search results: "Powered by
 * DocsGPT" by default (translated, with only the name linked), an embedder's
 * own `{ label, href }`, or nothing for `false`. An embedder's label that
 * starts with "Powered by" links only the name after it.
 */
export const PoweredBy = ({
  value = true,
  className,
}: {
  value?: PoweredByProp;
  className?: string;
}) => {
  const { messages } = useMessages();
  if (value === false) return null;
  if (value === true) {
    // The brand sits wherever the language puts it.
    const [before, after = ''] = messages.poweredBy.split('{brand}');
    return (
      <Credit className={className}>
        {before}
        <CreditLink
          href={DOCSGPT_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          DocsGPT
        </CreditLink>
        {after}
      </Credit>
    );
  }
  const { label, href } = value;
  if (!href) return <Credit className={className}>{label}</Credit>;
  const prefix = /^powered by\s+/i.exec(label)?.[0] ?? '';
  return (
    <Credit className={className}>
      {prefix}
      <CreditLink href={href} target="_blank" rel="noopener noreferrer">
        {label.slice(prefix.length)}
      </CreditLink>
    </Credit>
  );
};

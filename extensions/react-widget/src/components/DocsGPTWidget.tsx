'use client';
import React, { useRef } from 'react';
import DOMPurify from 'dompurify';
import styled, { keyframes, css } from 'styled-components';
import {
  PaperPlaneIcon,
  RocketIcon,
  ExclamationTriangleIcon,
  Cross2Icon,
} from '@radix-ui/react-icons';
import {
  FEEDBACK,
  MESSAGE_TYPE,
  Query,
  Status,
  WidgetCoreProps,
  WidgetProps,
} from '../types/index';
import { fetchAnswerStreaming, sendFeedback } from '../requests/streamingApi';
import { ThemeProvider } from 'styled-components';
import MarkdownIt from 'markdown-it';
import {
  prettifyName,
  toolNames,
  workflowStepLabel,
  type StreamEvent,
} from '../utils/streamEvents';

const LikeIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M9.39995 5.89997V3.09999C9.39995 2.54304 9.1787 2.0089 8.78487 1.61507C8.39105 1.22125 7.85691 1 7.29996 1L4.49998 7.29996V14.9999H12.3959C12.7336 15.0037 13.0612 14.8854 13.3185 14.6667C13.5757 14.448 13.7453 14.1437 13.7959 13.8099L14.7619 7.50996C14.7924 7.30931 14.7788 7.10444 14.7222 6.90954C14.6657 6.71464 14.5674 6.53437 14.4342 6.38123C14.301 6.22808 14.1362 6.10572 13.951 6.02262C13.7659 5.93952 13.5649 5.89767 13.3619 5.89997H9.39995ZM4.49998 14.9999H2.39999C2.02869 14.9999 1.6726 14.8524 1.41005 14.5899C1.1475 14.3273 1 13.9712 1 13.5999V8.69995C1 8.32865 1.1475 7.97256 1.41005 7.71001C1.6726 7.44746 2.02869 7.29996 2.39999 7.29996H4.49998"
      fill="none"
    />
    <path
      d="M4.49998 7.29996L7.29996 1C7.85691 1 8.39105 1.22125 8.78487 1.61507C9.1787 2.0089 9.39995 2.54304 9.39995 3.09999V5.89997H13.3619C13.5649 5.89767 13.7659 5.93952 13.951 6.02262C14.1362 6.10572 14.301 6.22808 14.4342 6.38123C14.5674 6.53437 14.6657 6.71464 14.7223 6.90954C14.7788 7.10444 14.7924 7.30931 14.7619 7.50996L13.7959 13.8099C13.7453 14.1437 13.5757 14.448 13.3185 14.6667C13.0612 14.8854 12.7336 15.0037 12.3959 14.9999H4.49998M4.49998 7.29996V14.9999M4.49998 7.29996H2.39999C2.02869 7.29996 1.6726 7.44746 1.41005 7.71001C1.1475 7.97256 1 8.32865 1 8.69995V13.5999C1 13.9712 1.1475 14.3273 1.41005 14.5899C1.6726 14.8524 2.02869 14.9999 2.39999 14.9999H4.49998"
      strokeWidth="1.39999"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const DislikeIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M6.37776 10.1001V12.9C6.37776 13.457 6.599 13.9911 6.99282 14.3849C7.38664 14.7788 7.92077 15 8.47772 15L11.2777 8.70011V1.00025H3.38181C3.04419 0.996436 2.71656 1.11477 2.45929 1.33344C2.20203 1.55212 2.03246 1.8564 1.98184 2.19023L1.01585 8.49012C0.985398 8.69076 0.998931 8.89563 1.05551 9.09053C1.1121 9.28543 1.21038 9.46569 1.34355 9.61884C1.47671 9.77198 1.64159 9.89434 1.82674 9.97744C2.01189 10.0605 2.2129 10.1024 2.41583 10.1001H6.37776ZM11.2777 1.00025H13.1466C13.5428 0.993247 13.9277 1.13195 14.2284 1.39002C14.5291 1.64809 14.7245 2.00758 14.7776 2.40023V7.30014C14.7245 7.69279 14.5291 8.05227 14.2284 8.31035C13.9277 8.56842 13.5428 8.70712 13.1466 8.70011H11.2777"
      fill="none"
    />
    <path
      d="M11.2777 8.70011L8.47772 15C7.92077 15 7.38664 14.7788 6.99282 14.3849C6.599 13.9911 6.37776 13.457 6.37776 12.9V10.1001H2.41583C2.2129 10.1024 2.01189 10.0605 1.82674 9.97744C1.64159 9.89434 1.47671 9.77198 1.34355 9.61884C1.21038 9.46569 1.1121 9.28543 1.05551 9.09053C0.998931 8.89563 0.985398 8.69076 1.01585 8.49012L1.98184 2.19023C2.03246 1.8564 2.20203 1.55212 2.45929 1.33344C2.71656 1.11477 3.04419 0.996436 3.38181 1.00025H11.2777M11.2777 8.70011V1.00025M11.2777 8.70011H13.1466C13.5428 8.70712 13.9277 8.56842 14.2284 8.31035C14.5291 8.05227 14.7245 7.69279 14.7776 7.30014V2.40023C14.7245 2.00758 14.5291 1.64809 14.2284 1.39002C13.9277 1.13195 13.5428 0.993247 13.1466 1.00025H11.2777"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const CopyIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <rect x="5.5" y="5.5" width="9" height="9" rx="1.5" />
    <path d="M10.5 5.5V3a1.5 1.5 0 0 0-1.5-1.5H3A1.5 1.5 0 0 0 1.5 3v6A1.5 1.5 0 0 0 3 10.5h2.5" />
  </svg>
);

const CheckIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M2.5 8.5 6 12l7.5-8" />
  </svg>
);

const RetryIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M14 8a6 6 0 1 1-1.76-4.24" />
    <path d="M14 2v4h-4" />
  </svg>
);

const StopIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="currentColor"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <rect x="4" y="4" width="8" height="8" rx="1.5" />
  </svg>
);

const ArrowDownIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg
    width="14"
    height="14"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M8 3v10M3.5 8.5 8 13l4.5-4.5" />
  </svg>
);

const themes = {
  dark: {
    bg: '#222327',
    text: '#fff',
    primary: {
      text: '#FAFAFA',
      bg: '#222327',
    },
    secondary: {
      text: '#A1A1AA',
      bg: '#38383b',
    },
    shimmer: {
      base: '#A1A1AA',
      highlight: '#FAFAFA',
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
      text: '#A1A1AA',
      bg: '#F6F6F6',
    },
    shimmer: {
      base: '#71717A',
      highlight: '#D4D4D8',
    },
  },
};

const sizesConfig = {
  small: { size: 'small', width: '320px', height: '400px' },
  medium: { size: 'medium', width: '400px', height: '80vh' },
  large: { size: 'large', width: '666px', height: '75vh' },
  getCustom: (custom: {
    width: string;
    height: string;
    maxWidth?: string;
    maxHeight?: string;
  }) => ({
    size: 'custom',
    width: custom.width,
    height: custom.height,
    maxWidth: custom.maxWidth || '968px',
    maxHeight: custom.maxHeight || '70vh',
  }),
};
const createBox = keyframes`
   0% {
        transform: scale(0.6);
      }
      90% {
        transform: scale(1.02);
      }
      100% {
        transform: scale(1);
      }
`;
const closeBox = keyframes`
  0% {
        transform: scale(1); 
      }
      10% {
        transform: scale(1.02); 
      }
      100% {
        transform: scale(0.6);
      }
`;

const openContainer = keyframes`
      0% {
        width: 200px;
        height: 100px;
      }
      100% {
        width: ${(props) => props.theme.dimensions!.width};
        height: ${(props) => props.theme.dimensions!.height};
        border-radius: 12px;
      }`;
const closeContainer = keyframes`
  0% {
        width: ${(props) => props.theme.dimensions!.width};
        height: ${(props) => props.theme.dimensions!.height};
        border-radius: 12px;
      }
      100% {
        width: 200px;
        height: 100px;
      }
`;
const fadeIn = keyframes`
  from {
        opacity: 0;
        width: ${(props) => props.theme.dimensions!.width};
        height: ${(props) => props.theme.dimensions!.height};
        transform: scale(0.9);
      }
      to {
        opacity: 1;
        transform: scale(1);
        width: ${(props) => props.theme.dimensions!.width};
        height: ${(props) => props.theme.dimensions!.height};
      }
`;

const fadeOut = keyframes`
  from {
        opacity: 1;
        width: ${(props) => props.theme.dimensions!.width};
        height: ${(props) => props.theme.dimensions!.height};
      }
      to {
        opacity: 0;
        transform: scale(0.9);
        width: ${(props) => props.theme.dimensions!.width};
        height: ${(props) => props.theme.dimensions!.height};
      }
`;
const scaleAnimation = keyframes`
  from {
      transform: scale(1.2);
      }
      to {
      transform: scale(1);
      }
`;
const settleIn = keyframes`
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
`;
const Overlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  z-index: 999;
  transition: opacity 0.5s;
`;

const WidgetContainer = styled.div<{ $modal?: boolean }>`
  all: initial;
  position: fixed;
  right: ${(props) => (props.$modal ? '50%' : '10px')};
  bottom: ${(props) => (props.$modal ? '50%' : '10px')};
  z-index: 1001;
  transform-origin: 100% 100%;
  display: block;
  &.modal {
    transform: translate(50%, 50%);
  }
  &.open {
    animation: css ${createBox} 250ms cubic-bezier(0.25, 0.1, 0.25, 1) forwards;
  }
  &.close {
    animation: css ${closeBox} 250ms cubic-bezier(0.25, 0.1, 0.25, 1) forwards;
  }
  align-items: center;
  text-align: left;
`;

const StyledContainer = styled.div<{ $isOpen: boolean }>`
  all: initial;
  max-height: ${(props) => props.theme.dimensions!.maxHeight};
  max-width: ${(props) => props.theme.dimensions!.maxWidth};
  width: ${(props) => props.theme.dimensions!.width};
  height: ${(props) => props.theme.dimensions!.height};
  position: relative;
  flex-direction: column;
  justify-content: space-between;
  bottom: 0;
  left: 0;
  background-color: ${(props) => props.theme.primary.bg};
  font-family: sans-serif;
  display: flex;
  border-radius: 12px;
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.05),
    0 2px 4px rgba(0, 0, 0, 0.1);
  padding: 26px 26px 0px 26px;
  animation: ${({ $isOpen, theme }) =>
    theme.dimensions!.size === 'large'
      ? $isOpen
        ? css`
            ${fadeIn} 150ms ease-in forwards
          `
        : css`
            ${fadeOut} 150ms ease-in forwards
          `
      : $isOpen
        ? css`
            ${openContainer} 150ms ease-in forwards
          `
        : css`
            ${closeContainer} 250ms ease-in forwards
          `};
  @media only screen and (max-width: 768px) {
    max-height: 100vh;
    max-width: 80vw;
    overflow: auto;
  }
`;

const FloatingButton = styled.div<{
  $bgcolor: string;
  $hidden: boolean;
  $isAnimatingButton: boolean;
}>`
  position: fixed;
  display: ${(props) => (props.$hidden ? 'none' : 'flex')};
  z-index: 500;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  align-items: center;
  bottom: 16px;
  color: white;
  font-family: sans-serif;
  right: 16px;
  font-weight: 500;
  border-radius: 9999px;
  background: ${(props) => props.$bgcolor};
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
  cursor: pointer;
  animation: ${(props) =>
    props.$isAnimatingButton
      ? css`
          ${scaleAnimation} 200ms forwards
        `
      : 'none'};
  &:hover {
    transform: scale(1.1);
    transition: transform 0.2s ease-in-out;
  }
  &:not(:hover) {
    transition: transform 0.2s ease-in-out;
  }
`;
const CancelButton = styled.button`
  cursor: pointer;
  position: absolute;
  top: 0;
  right: 0;
  margin: 8px;
  width: 30px;
  padding: 0;
  background-color: transparent;
  border: none;
  outline: none;
  color: inherit;
  transition: opacity 0.3s ease;
  opacity: 0.6;
  &:hover {
    opacity: 1;
  }
  .white-filter {
    filter: invert(100%);
  }
`;

const Header = styled.div`
  display: flex;
  align-items: flex-start;
`;

const ContentWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-left: 8px;
`;

const Title = styled.h3`
  font-size: 14px;
  font-weight: normal;
  color: ${(props) => props.theme.primary.text};
  margin: 0;
`;

const Description = styled.p`
  font-size: 13.75px;
  color: ${(props) => props.theme.secondary.text};
  margin: 0;
  padding: 0;
`;

const Conversation = styled.div`
  height: 100%;
  border-radius: 6px;
  text-align: left;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: ${(props) => props.theme.secondary.bg} transparent; /* thumb color track color */
`;
const ActionsRow = styled.div`
  display: flex;
  align-items: center;
  gap: 2px;
  clear: both;
  padding: 0 2px 2px 2px;
`;
const ActionButton = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 24px;
  padding: 0 6px;
  border: none;
  border-radius: 6px;
  background-color: transparent;
  color: ${(props) => props.theme.secondary.text};
  font-size: 11px;
  font-family: sans-serif;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;

  &:hover {
    background-color: ${(props) => props.theme.secondary.bg};
    color: ${(props) => props.theme.primary.text};
  }

  &:focus-visible {
    outline: 2px solid #8860db;
    outline-offset: 1px;
  }
`;
const MessageBubble = styled.div<{ $type: MESSAGE_TYPE }>`
  display: block;
  font-size: 16px;
  position: relative;
  width: 100%;
  float: right;
  margin: 0px;
  animation: ${settleIn} 0.22s ease-out;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
  /* Contains the floated Message so the bubble keeps its height. */
  &::after {
    content: '';
    display: table;
    clear: both;
  }
`;
const Message = styled.div<{ $type: MESSAGE_TYPE }>`
  background: ${(props) =>
    props.$type === 'QUESTION'
      ? 'linear-gradient(to bottom right, #8860DB, #6D42C5)'
      : props.theme.secondary.bg};
  color: ${(props) =>
    props.$type === 'ANSWER' ? props.theme.primary.text : '#fff'};
  border: none;
  float: ${(props) => (props.$type === 'QUESTION' ? 'right' : 'left')};
  max-width: ${(props) => (props.$type === 'ANSWER' ? '90%' : '80%')};
  overflow: auto;
  margin: 4px;
  display: block;
  line-height: 1.5;
  padding: 12px;
  border-radius: 6px;
  overflow-wrap: break-word;
`;
const Markdown = styled.div`
  a {
    color: #9971ec;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  a:hover {
    color: #8860db;
  }

  pre {
    padding: 8px;
    width: 90%;
    font-size: 12px;
    border-radius: 6px;
    overflow-x: auto;
    background-color: #1b1c1f;
    color: #fff;
  }

  h1 {
    font-size: clamp(14px, 40vw, 16px);
  }

  h2 {
    font-size: 14px;
  }

  h3 {
    font-size: 14px;
  }

  p {
    margin: 0px;
  }

  code:not(pre code) {
    border-radius: 6px;
    padding: 1px 3px;
    font-size: 12px;
    display: inline-block;
    background-color: #646464;
    color: #fff;
  }

  code {
    white-space: pre-wrap;
    overflow-wrap: break-word;
    word-break: break-all;
  }

  ul {
    padding: 0px;
    margin: 1rem 0;
    list-style-position: outside;
    list-style-type: disc;
    padding-left: 1rem;
    white-space: normal;
  }

  ol {
    padding: 0px;
    margin: 1rem 0;
    list-style-position: outside;
    list-style-type: decimal;
    padding-left: 1rem;
    white-space: normal;
  }

  li {
    line-height: 1.625;
  }
  .dgpt-table-container {
    margin: 20px 0;
    width: 100%;
    overflow-x: scroll !important;
    border: 1px solid #a2a2ab;
    border-radius: 6px;
    -webkit-overflow-scrolling: touch;
    -ms-overflow-style: scrollbar;
    scrollbar-width: thin;
    scrollbar-color: #a2a2ab #38383b;
  }

  table,
  .dgpt-table {
    width: 100%;
    border-collapse: collapse;
    text-align: left;
    min-width: 600px;
  }
  thead,
  .dgpt-thead {
    font-size: 12px;
    text-transform: uppercase;
  }

  th,
  .dgpt-th,
  td,
  .dgpt-td {
    padding: 10px;
    border-bottom: 1px solid #a2a2ab;
    font-size: 14px;
  }
  th {
    font-weight: normal !important;
  }
  td {
    font-weight: bold;
  }
`;
const ErrorAlert = styled.div`
  color: #b91c1c;
  border: 0.1px solid #b91c1c;
  display: flex;
  padding: 4px;
  margin: 11.2px;
  opacity: 90%;
  max-width: 70%;
  font-weight: 400;
  border-radius: 6px;
  justify-content: space-evenly;
`;
const shimmerSweep = keyframes`
  to {
    background-position: -200% 0;
  }
`;
const statusPulse = keyframes`
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
`;
const StatusLine = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  /* Message floats; without this the row wraps beside it. */
  clear: both;
  margin: 4px;
  font-size: 12px;
  font-family: sans-serif;
  color: ${(props) => props.theme.secondary.text};
`;
const StatusDot = styled.span`
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 9999px;
  background-color: ${(props) => props.theme.secondary.text};
  opacity: 0.5;
  animation: ${statusPulse} 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;
// Gradient clipped to the glyphs and swept across them.
const ShimmerText = styled.span`
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background-image: ${(props) => {
    const { base, highlight } = props.theme.shimmer!;
    return `linear-gradient(90deg, ${base} 0%, ${base} 40%, ${highlight} 50%, ${base} 60%, ${base} 100%)`;
  }};
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: ${shimmerSweep} 2s linear infinite;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
    background-image: none;
    color: ${(props) => props.theme.secondary.text};
  }
`;
// Reasoning trace from `thought` events.
const Thought = styled.div`
  clear: both;
  margin: 4px;
  padding-left: 8px;
  border-left: 2px solid ${(props) => props.theme.secondary.bg};
  font-size: 12px;
  font-family: sans-serif;
  font-style: italic;
  line-height: 1.5;
  white-space: pre-wrap;
  color: ${(props) => props.theme.secondary.text};
`;
const RetryButton = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 10px;
  border: 1px solid #b91c1c33;
  border-radius: 8px;
  background-color: transparent;
  color: #b91c1c;
  font-size: 12px;
  font-family: sans-serif;
  cursor: pointer;
  transition: background-color 0.15s ease;

  &:hover {
    background-color: #b91c1c14;
  }
`;
// Shown only while scrolled away from the latest turn.
const ScrollToLatest = styled.button`
  position: absolute;
  /* Auto-margin centring, not translateX: settleIn owns transform. */
  left: 0;
  right: 0;
  bottom: 12px;
  margin: 0 auto;
  width: 30px;
  height: 30px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 9999px;
  background-color: #8860db;
  color: #fff;
  line-height: 0;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.22);
  animation: ${settleIn} 0.18s ease-out;
  z-index: 2;
`;
const ConversationArea = styled.div`
  position: relative;
  flex: 1;
  min-height: 0;
`;
const PromptContainer = styled.form`
  /* Sole source of the gap above the composer. */
  margin: 16px 12px 0 12px;
  padding: 5px 5px 5px 4px;
  background-color: ${(props) => props.theme.secondary.bg};
  border: none;
  border-radius: 14px;
  min-height: ${(props) =>
    props.theme.dimensions!.size == 'large' ? '40px' : '23px'};
  max-height: 150px;
  display: flex;
  align-items: end;
`;
const StyledTextarea = styled.textarea`
  box-sizing: border-box;
  width: 100%;
  border: none;
  padding: ${(props) =>
    props.theme.dimensions!.size === 'large'
      ? '18px 12px 14px 12px'
      : '8px 12px 4px 12px'};
  background-color: transparent;
  font-size: 16px;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  border-radius: 6px;
  color: ${(props) => props.theme.text};
  outline: none;
  resize: none;
  transition: height 0.1s ease;
  overflow-wrap: break-word;
  white-space: pre-wrap;
  line-height: 1.4;
  text-align: left;
  min-height: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '60px' : '40px'};
  max-height: 140px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #38383b transparent;
  &::-webkit-scrollbar {
    width: 6px;
    height: 6px;
  }
  &::-webkit-scrollbar-thumb {
    background-color: #38383b;
    border-radius: 6px;
  }
  &::-webkit-scrollbar-track {
    background: transparent;
  }
  &::placeholder {
    text-align: left;
  }
`;
const StyledButton = styled.button`
  display: flex;
  justify-content: center;
  align-items: center;
  background-image: linear-gradient(to bottom right, #5af0ec, #e80d9d);
  background-color: rgba(0, 0, 0, 0.3);
  border-radius: 6px;
  min-width: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '60px' : '40px'};
  height: ${(props) =>
    props.theme.dimensions!.size === 'large' ? '60px' : '40px'};
  margin-left: 8px;
  padding: 0px;

  border: none;
  cursor: pointer;
  outline: none;
  &:hover {
    opacity: 90%;
  }
  &:disabled {
    background-image: linear-gradient(to bottom right, #2d938f, #b31877);
  }
`;
const HeroContainer = styled.div`
  position: relative;
  width: 90%;
  max-width: 500px;
  background-image: linear-gradient(to bottom right, #5af0ec, #ff1bf4);
  border-radius: 10px;
  margin: 16px auto;
  padding: 2px;
`;
const HeroWrapper = styled.div`
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 8px;
  align-items: middle;
  background-color: ${(props) => props.theme.primary.bg};
  border-radius: 10px;
  font-weight: normal;
  padding: 12px;
`;
const HeroTitle = styled.h3`
  color: ${(props) => props.theme.text};
  font-size: 16px;
  margin: 0px;
  padding: 0px;
`;
const HeroDescription = styled.p`
  color: ${(props) => props.theme.text};
  font-size: 12px;
  line-height: 1.5;
  margin: 0px;
  padding: 0px;
`;
const Hyperlink = styled.a`
  color: #9971ec;
  text-decoration: none;
`;
const Tagline = styled.div`
  text-align: center;
  display: block;
  color: ${(props) => props.theme.secondary.text};
  padding: 12px;
  font-size: 12px;
`;

const SourcesList = styled.div`
  display: flex;
  margin: 12px 0px;
  flex-wrap: wrap;
  gap: 8px;
`;

const SourceLink = styled.a`
  color: ${(props) => props.theme.primary.text};
  text-decoration: none;
  background: ${(props) => props.theme.secondary.bg};
  padding: 4px 12px;
  border-radius: 85px;
  font-size: 14px;
  transition: opacity 0.2s ease;
  display: inline-block;
  text-align: center;
  max-width: 25%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.5;

  &:hover {
    opacity: 0.8;
  }
`;

const ExtraButton = styled.button`
  color: #9971ec;
  background: transparent;
  border-radius: 85px;
  padding: 4px 12px;
  font-size: 14px;
  border: none;
  cursor: pointer;
  transition: opacity 0.2s ease;
  text-align: center;
  height: auto;
  &:hover {
    opacity: 0.8;
  }
`;
const SourcesComponent = ({
  sources,
}: {
  sources: Array<{ source: string; title: string }>;
}) => {
  const [showAll, setShowAll] = React.useState(false);
  const visibleSources = showAll ? sources : sources.slice(0, 3);
  const extraCount = sources.length - 3;

  return (
    <SourcesList>
      {visibleSources.map((source, idx) => (
        <SourceLink
          key={idx}
          href={source.source}
          target="_blank"
          rel="noopener noreferrer"
          title={source.title}
        >
          {source.title}
        </SourceLink>
      ))}
      {sources.length > 3 && (
        <ExtraButton onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show less' : `+ ${extraCount} more`}
        </ExtraButton>
      )}
    </SourcesList>
  );
};

const Hero = ({
  title,
  description,
  theme,
}: {
  title: string;
  description: string;
  theme: string;
}) => {
  return (
    <HeroContainer>
      <HeroWrapper>
        <RocketIcon
          color={theme === 'light' ? 'black' : 'white'}
          width={24}
          height={24}
        />
        <HeroTitle>{title}</HeroTitle>
        <HeroDescription>{description}</HeroDescription>
      </HeroWrapper>
    </HeroContainer>
  );
};
export const DocsGPTWidget = (props: WidgetProps) => {
  const {
    buttonIcon = 'https://d3dg1063dc54p9.cloudfront.net/widget/chat.svg',
    buttonText = 'Ask a question',
    buttonBg = 'linear-gradient(to bottom right, #5AF0EC, #E80D9D)',
    defaultOpen = false,
    ...coreProps
  } = props;

  const [open, setOpen] = React.useState<boolean>(defaultOpen);
  const [isAnimatingButton, setIsAnimatingButton] = React.useState(false);
  const [isFloatingButtonVisible, setIsFloatingButtonVisible] =
    React.useState(true);

  React.useEffect(() => {
    if (isFloatingButtonVisible)
      setTimeout(() => setIsAnimatingButton(true), 250);
    return () => {
      setIsAnimatingButton(false);
    };
  }, [isFloatingButtonVisible]);

  const handleClose = () => {
    setIsFloatingButtonVisible(true);
    setOpen(false);
  };
  const handleOpen = () => {
    setOpen(true);
    setIsFloatingButtonVisible(false);
  };
  return (
    <>
      <FloatingButton
        $bgcolor={buttonBg}
        onClick={handleOpen}
        $hidden={!isFloatingButtonVisible}
        $isAnimatingButton={isAnimatingButton}
      >
        <img width={24} src={buttonIcon} />
        <span>{buttonText}</span>
      </FloatingButton>
      <WidgetCore isOpen={open} handleClose={handleClose} {...coreProps} />
    </>
  );
};

export const WidgetCore = ({
  apiHost = 'https://gptcloud.arc53.com',
  apiKey = '527686a3-e867-4b4d-9fec-f5f45fdb613a',
  avatar = 'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png',
  title = 'Get AI assistance',
  description = "DocsGPT's AI Chatbot is here to help",
  heroTitle = 'Welcome to DocsGPT !',
  heroDescription = 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.',
  size = 'medium',
  theme = 'dark',
  collectFeedback = true,
  isOpen = false,
  showSources = true,
  handleClose,
  prefilledQuery = '',
}: WidgetCoreProps) => {
  const [prompt, setPrompt] = React.useState<string>('');
  const [mounted, setMounted] = React.useState(false);
  const [status, setStatus] = React.useState<Status>('idle');
  const [queries, setQueries] = React.useState<Query[]>([]);
  const [conversationId, setConversationId] = React.useState<string | null>(
    null,
  );
  // Auto-follow the stream only while already near the bottom.
  const [isPinnedToLatest, setIsPinnedToLatest] = React.useState(true);
  const [copiedIndex, setCopiedIndex] = React.useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const isBubbleHovered = useRef<boolean>(false);
  const conversationRef = useRef<HTMLDivElement | null>(null);
  const endMessageRef = React.useRef<HTMLDivElement | null>(null);
  const promptRef = React.useRef<HTMLTextAreaElement | null>(null);
  const md = new MarkdownIt();
  //Custom markdown for the table
  md.renderer.rules.table_open = () =>
    '<div class="dgpt-table-container"><table class="dgpt-table">';
  md.renderer.rules.table_close = () => '</table></div>';
  md.renderer.rules.thead_open = () => '<thead class="dgpt-thead">';
  md.renderer.rules.tr_open = () => '<tr class="dgpt-tr">';
  md.renderer.rules.td_open = () => '<td class="dgpt-td">';
  md.renderer.rules.th_open = () => '<th class="dgpt-th">';

  React.useEffect(() => {
    if (isOpen) {
      setMounted(true); // Mount the component
      appendQuery(prefilledQuery);
    } else {
      // Wait for animations before unmounting
      const timeout = setTimeout(() => {
        setMounted(false);
      }, 250);
      return () => clearTimeout(timeout);
    }
  }, [isOpen]);

  // Beyond this the reader is deliberately looking away.
  const STICK_THRESHOLD_PX = 48;

  const distanceFromBottom = (el: HTMLDivElement) =>
    el.scrollHeight - el.scrollTop - el.clientHeight;

  const scrollToLatest = (smooth = true) => {
    const el = conversationRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    });
    setIsPinnedToLatest(true);
  };

  // Explicit request: land immediately rather than easing.
  const jumpToLatest = () => scrollToLatest(false);

  const handleConversationScroll = () => {
    const el = conversationRef.current;
    if (!el) return;
    setIsPinnedToLatest(distanceFromBottom(el) < STICK_THRESHOLD_PX);
  };

  React.useEffect(() => {
    const el = conversationRef.current;
    if (!el || !isPinnedToLatest) return;
    // Easing per token never catches up, so jump while streaming.
    if (status === 'loading') el.scrollTop = el.scrollHeight;
    else scrollToLatest();
  }, [queries.length, queries[queries.length - 1]?.response, status]);

  async function handleFeedback(feedback: FEEDBACK, index: number) {
    let query = queries[index];
    if (!query.response || !conversationId) {
      console.log(
        'Cannot submit feedback: missing response or conversation ID',
      );
      return;
    }

    // If clicking the same feedback button that's already active, remove the feedback by sending null
    if (query.feedback === feedback) {
      try {
        const response = await sendFeedback(
          {
            question: query.prompt,
            answer: query.response,
            feedback: null,
            apikey: apiKey,
            conversation_id: conversationId,
            question_index: index,
          },
          apiHost,
        );

        if (response.status === 200) {
          const updatedQuery = { ...query };
          delete updatedQuery.feedback;
          setQueries((prev: Query[]) =>
            prev.map((q, i) => (i === index ? updatedQuery : q)),
          );
        }
      } catch (err) {
        console.error('Failed to submit feedback:', err);
      }
      return;
    }

    try {
      const response = await sendFeedback(
        {
          question: query.prompt,
          answer: query.response,
          feedback: feedback,
          apikey: apiKey,
          conversation_id: conversationId,
          question_index: index,
        },
        apiHost,
      );

      if (response.status === 200) {
        setQueries((prev: Query[]) => {
          return prev.map((q, i) => {
            if (i === index) {
              return { ...q, feedback: feedback };
            }
            return q;
          });
        });
      }
    } catch (err) {
      console.error('Failed to submit feedback:', err);
    }
  }

  const stopGenerating = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus('idle');
  };

  async function stream(question: string) {
    setStatus('loading');
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await fetchAnswerStreaming({
        signal: controller.signal,
        question: question,
        apiKey: apiKey,
        apiHost: apiHost,
        history: queries,
        conversationId: conversationId,
        onEvent: (event: MessageEvent) => {
          let data: StreamEvent;
          try {
            data = JSON.parse(event.data);
          } catch {
            // One malformed frame must not fail the whole turn.
            return;
          }

          const patch = (change: (query: Query) => void) => {
            setQueries((prev: Query[]) => {
              if (prev.length === 0) return prev;
              const updated = [...prev];
              const current = { ...updated[updated.length - 1] };
              change(current);
              updated[updated.length - 1] = current;
              return updated;
            });
          };

          const appendAnswer = (d: StreamEvent) => {
            if (typeof d.answer !== 'string') return;
            patch((query) => {
              query.response = (query.response ?? '') + d.answer;
            });
          };

          const noteToolCalls = (calls: unknown) => {
            const names = toolNames(calls);
            if (names.length === 0) return;
            patch((query) => {
              query.toolCalls = [
                ...new Set([...(query.toolCalls ?? []), ...names]),
              ];
            });
          };

          const handlers: Record<string, (d: StreamEvent) => void> = {
            answer: appendAnswer,
            end: () => setStatus('idle'),
            id: (d) => setConversationId(d.id as string),
            error: (d) => {
              patch((query) => {
                query.error = d.error as string;
              });
              setStatus('idle');
            },
            source: (d) => {
              if (!showSources) return;
              patch((query) => {
                query.sources = d.source as Query['sources'];
              });
            },
            thought: (d) =>
              patch((query) => {
                query.thought =
                  (query.thought ?? '') + ((d.thought as string) ?? '');
              }),
            notice: (d) =>
              patch((query) => {
                query.notice = (d.notice as string) ?? '';
              }),
            // Workflow agents report progress per node instead of `notice`.
            workflow_step: (d) => {
              const label = workflowStepLabel(d);
              if (label) {
                patch((query) => {
                  query.notice = label;
                });
              }
            },
            tool_calls: (d) => noteToolCalls(d.tool_calls),
            tool_call: (d) => noteToolCalls([d.data]),
            // Blocked content must leave the screen, reasoning included.
            guardrail: (d) => {
              if (!d.retract) return;
              patch((query) => {
                query.response = '';
                query.thought = '';
              });
            },
            // Recorded server-side; nothing to render.
            message_id: () => undefined,
          };

          // Unknown types are ignored; untyped frames are answer deltas.
          const handle = (data.type && handlers[data.type]) || appendAnswer;
          handle(data);
        },
      });
    } catch {
      const updatedQueries = [...queries];
      updatedQueries[updatedQueries.length - 1].error =
        'Something went wrong !';
      setQueries(updatedQueries);
      setStatus('idle');
      //setEventInterrupt(false)
    }
  }

  const appendQuery = async (userQuery: string) => {
    if (!userQuery) return;

    setIsPinnedToLatest(true);
    queries.push({ prompt: userQuery });
    setPrompt('');
    await stream(userQuery);
  };
  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(
        () => setCopiedIndex((cur) => (cur === index ? null : cur)),
        1600,
      );
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  // Re-runs the turn in place instead of appending a duplicate prompt.
  const handleRetry = async (index: number) => {
    if (status === 'loading') return;
    const prompt = queries[index]?.prompt;
    if (!prompt) return;
    setQueries((prev: Query[]) => {
      const updated = [...prev];
      updated[index] = { prompt };
      return updated.slice(0, index + 1);
    });
    setIsPinnedToLatest(true);
    await stream(prompt);
  };

  // submit handler
  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    if (promptRef.current) {
      promptRef.current.style.height = 'auto';
    }
    await appendQuery(prompt);
  };
  const handlePromptKeyDown = async (
    e: React.KeyboardEvent<HTMLTextAreaElement>,
  ) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      // Prevent sending empty messages
      if (promptRef.current && promptRef.current.value.trim() === '') return;
      //Rest the input to it's original size after submitting
      if (promptRef.current) {
        promptRef.current.value = '';
        promptRef.current.style.height = 'auto';
      }
      await appendQuery(prompt);
    }
  };
  // Auto-resize the input textarea while typing, clamping to base or max height
  const handleUserInput = () => {
    const el = promptRef.current;
    if (!el) return;
    const baseHeight = size === 'large' ? 60 : 40;
    const maxHeight = 140;
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, maxHeight);
    el.style.height = Math.max(baseHeight, next) + 'px';
  };

  // Update prompt state, auto resize textarea to content, and maintain scroll on new lines
  const handlePromptChange = (
    event: React.ChangeEvent<HTMLTextAreaElement>,
  ) => {
    const value = event.target.value;
    setPrompt(value);
    const el = event.currentTarget;
    const baseHeight = size === 'large' ? 60 : 40;
    const maxHeight = 140;
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, maxHeight);
    el.style.height = Math.max(baseHeight, next) + 'px';
    if (value.includes('\n')) {
      el.scrollTop = el.scrollHeight;
    }
  };
  const handleImageError = (
    event: React.SyntheticEvent<HTMLImageElement, Event>,
  ) => {
    event.currentTarget.src =
      'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png';
  };

  const renderStatusLine = (query: Query, index: number) => {
    if (status !== 'loading' || index !== queries.length - 1) return null;
    // A notice/node title is more specific than "Thinking", but goes stale
    // once tokens arrive.
    const label = query.response
      ? 'Generating\u2026'
      : (query.notice ?? 'Thinking\u2026');
    return (
      <StatusLine role="status" aria-live="polite">
        <StatusDot />
        <ShimmerText>{label}</ShimmerText>
      </StatusLine>
    );
  };

  const dimensions =
    typeof size === 'object' && 'custom' in size
      ? sizesConfig.getCustom(size.custom)
      : sizesConfig[size];
  if (!mounted) return null;

  return (
    <ThemeProvider theme={{ ...themes[theme], dimensions }}>
      {isOpen && size === 'large' && <Overlay onClick={handleClose} />}
      {
        <WidgetContainer
          className={`${size !== 'large' ? (isOpen ? 'open' : 'close') : 'modal'}`}
          $modal={size === 'large'}
        >
          <StyledContainer $isOpen={isOpen}>
            <div>
              <CancelButton onClick={handleClose}>
                <Cross2Icon
                  width={24}
                  height={24}
                  color={theme === 'light' ? 'black' : 'white'}
                />
              </CancelButton>
              <Header>
                <img
                  style={{
                    transform: 'translateY(-5px)',
                    maxWidth: '42px',
                    maxHeight: '42px',
                  }}
                  onError={handleImageError}
                  src={avatar}
                  alt="docs-gpt"
                />
                <ContentWrapper>
                  <Title>{title}</Title>
                  <Description>{description}</Description>
                </ContentWrapper>
              </Header>
            </div>
            <ConversationArea>
              <Conversation
                ref={conversationRef}
                onScroll={handleConversationScroll}
              >
                {queries.length > 0 ? (
                  queries?.map((query, index) => {
                    return (
                      <React.Fragment key={index}>
                        {query.prompt && (
                          <MessageBubble $type="QUESTION">
                            <Message
                              $type="QUESTION"
                              ref={
                                !(query.response || query.error) &&
                                index === queries.length - 1
                                  ? endMessageRef
                                  : null
                              }
                            >
                              {query.prompt}
                            </Message>
                          </MessageBubble>
                        )}
                        {query.response ? (
                          <MessageBubble
                            onMouseOver={() => {
                              isBubbleHovered.current = true;
                            }}
                            $type="ANSWER"
                          >
                            {showSources &&
                              query.sources &&
                              query.sources.length > 0 &&
                              query.sources.some(
                                (source) => source.source !== 'local',
                              ) && (
                                <SourcesComponent
                                  sources={query.sources.filter(
                                    (source) => source.source !== 'local',
                                  )}
                                />
                              )}
                            {query.toolCalls && query.toolCalls.length > 0 && (
                              <StatusLine>
                                Used{' '}
                                {query.toolCalls.map(prettifyName).join(', ')}
                              </StatusLine>
                            )}
                            {query.thought && (
                              <Thought>{query.thought}</Thought>
                            )}
                            <Message
                              $type="ANSWER"
                              ref={
                                index === queries.length - 1
                                  ? endMessageRef
                                  : null
                              }
                            >
                              <Markdown
                                dangerouslySetInnerHTML={{
                                  __html: DOMPurify.sanitize(
                                    md.render(query.response),
                                  ),
                                }}
                              />
                            </Message>
                            {renderStatusLine(query, index)}

                            <ActionsRow>
                              <ActionButton
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleCopy(query.response ?? '', index);
                                }}
                                aria-label={
                                  copiedIndex === index
                                    ? 'Copied'
                                    : 'Copy answer'
                                }
                              >
                                {copiedIndex === index ? (
                                  <CheckIcon />
                                ) : (
                                  <CopyIcon />
                                )}
                              </ActionButton>

                              {collectFeedback && (
                                <>
                                  <ActionButton
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleFeedback('LIKE', index);
                                    }}
                                    aria-label="Good response"
                                    aria-pressed={query.feedback === 'LIKE'}
                                  >
                                    <LikeIcon
                                      style={{
                                        stroke:
                                          query.feedback === 'LIKE'
                                            ? '#8860DB'
                                            : 'currentColor',
                                      }}
                                      fill="none"
                                    />
                                  </ActionButton>
                                  <ActionButton
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleFeedback('DISLIKE', index);
                                    }}
                                    aria-label="Bad response"
                                    aria-pressed={query.feedback === 'DISLIKE'}
                                  >
                                    <DislikeIcon
                                      style={{
                                        stroke:
                                          query.feedback === 'DISLIKE'
                                            ? '#ed8085'
                                            : 'currentColor',
                                      }}
                                      fill="none"
                                    />
                                  </ActionButton>
                                </>
                              )}
                            </ActionsRow>
                          </MessageBubble>
                        ) : (
                          <div>
                            {query.error ? (
                              <ErrorAlert>
                                <ExclamationTriangleIcon
                                  width={22}
                                  height={22}
                                  color="#b91c1c"
                                />
                                <div>
                                  <h5 style={{ margin: 2 }}>Network Error</h5>
                                  <span style={{ margin: 2, fontSize: '13px' }}>
                                    {query.error}
                                  </span>
                                  <RetryButton
                                    type="button"
                                    onClick={() => handleRetry(index)}
                                    disabled={status === 'loading'}
                                  >
                                    <RetryIcon />
                                    Try again
                                  </RetryButton>
                                </div>
                              </ErrorAlert>
                            ) : (
                              <MessageBubble $type="ANSWER">
                                {query.thought && (
                                  <Thought>{query.thought}</Thought>
                                )}
                                {renderStatusLine(query, index)}
                              </MessageBubble>
                            )}
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })
                ) : (
                  <Hero
                    title={heroTitle}
                    description={heroDescription}
                    theme={theme}
                  />
                )}
              </Conversation>
              {!isPinnedToLatest && queries.length > 0 && (
                <ScrollToLatest
                  type="button"
                  onClick={jumpToLatest}
                  aria-label="Scroll to latest message"
                >
                  <ArrowDownIcon />
                </ScrollToLatest>
              )}
            </ConversationArea>
            <div>
              <PromptContainer onSubmit={handleSubmit}>
                <StyledTextarea
                  id="chatInput"
                  ref={promptRef}
                  autoFocus
                  onInput={handleUserInput}
                  value={prompt}
                  onChange={handlePromptChange}
                  placeholder="Ask your question"
                  onKeyDown={handlePromptKeyDown}
                  rows={1}
                  wrap="soft"
                />
                {status === 'loading' ? (
                  <StyledButton
                    type="button"
                    onClick={stopGenerating}
                    aria-label="Stop generating"
                  >
                    <StopIcon width={18} height={18} color="white" />
                  </StyledButton>
                ) : (
                  <StyledButton
                    disabled={prompt.trim().length == 0}
                    aria-label="Send message"
                  >
                    <PaperPlaneIcon width={18} height={18} color="white" />
                  </StyledButton>
                )}
              </PromptContainer>
              <Tagline>
                Powered by&nbsp;
                <Hyperlink target="_blank" href="https://www.docsgpt.cloud/">
                  DocsGPT
                </Hyperlink>
              </Tagline>
            </div>
          </StyledContainer>
        </WidgetContainer>
      }
    </ThemeProvider>
  );
};

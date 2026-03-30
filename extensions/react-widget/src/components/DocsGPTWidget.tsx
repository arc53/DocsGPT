'use client';
import React, { useRef, useState } from 'react';
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
  height: 70%;
  border-radius: 6px;
  text-align: left;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: ${(props) => props.theme.secondary.bg} transparent; /* thumb color track color */
`;
const Feedback = styled.div`
  background-color: transparent;
  font-weight: normal;
  gap: 12px;
  display: flex;
  padding: 6px;
  clear: both;
`;
const MessageBubble = styled.div<{ $type: MESSAGE_TYPE }>`
  display: block;
  font-size: 16px;
  position: relative;
  width: 100%;
  float: right;
  margin: 0px;
  &:hover ${Feedback} * {
    visibility: visible;
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
//dot loading animation
const dotBounce = keyframes`
  0%, 80%, 100% {
    transform: translateY(0);
  }
  40% {
    transform: translateY(-5px);
  }
`;

const DotAnimation = styled.div`
  display: inline-block;
  animation: ${dotBounce} 1s infinite ease-in-out;
`;
// delay classes as styled components
const Delay = styled(DotAnimation)<{ $delay: number }>`
  animation-delay: ${(props) => props.$delay + 'ms'};
`;
const PromptContainer = styled.form`
  background-color: transparent;
  min-height: ${(props) =>
    props.theme.dimensions!.size == 'large' ? '40px' : '23px'};
  max-height: 150px;
  display: flex;
  align-items: end;
  justify-content: space-evenly;
`;
const StyledTextarea = styled.textarea`
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #686877;
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
  size = 'small',
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
  const [eventInterrupt, setEventInterrupt] = React.useState<boolean>(false); //click or scroll by user while autoScrolling
  const [, setHasScrolledToLast] = useState(true);

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

  const handleUserInterrupt = () => {
    if (!eventInterrupt && status === 'loading') setEventInterrupt(true);
  };

  const scrollIntoView = () => {
    if (!conversationRef?.current || eventInterrupt) return;

    if (
      status === 'idle' ||
      !queries.length ||
      !queries[queries.length - 1].response
    ) {
      conversationRef.current.scrollTo({
        behavior: 'smooth',
        top: conversationRef.current.scrollHeight,
      });
    } else {
      conversationRef.current.scrollTop = conversationRef.current.scrollHeight;
    }
    setHasScrolledToLast(true);
  };

  const checkScroll = () => {
    const el = conversationRef.current;
    if (!el) return;
    const isBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 10;
    setHasScrolledToLast(isBottom);
  };

  React.useEffect(() => {
    if (!eventInterrupt) scrollIntoView();

    conversationRef.current?.addEventListener('scroll', checkScroll);
    return () => {
      conversationRef.current?.removeEventListener('scroll', checkScroll);
    };
  }, [queries.length, queries[queries.length - 1]?.response]);

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

  async function stream(question: string) {
    setStatus('loading');
    try {
      await fetchAnswerStreaming({
        question: question,
        apiKey: apiKey,
        apiHost: apiHost,
        history: queries,
        conversationId: conversationId,
        onEvent: (event: MessageEvent) => {
          const data = JSON.parse(event.data);
          // check if the 'end' event has been received
          if (data.type === 'end') {
            setStatus('idle');
          } else if (data.type === 'id') {
            setConversationId(data.id);
          } else if (data.type === 'error') {
            const updatedQueries = [...queries];
            updatedQueries[updatedQueries.length - 1].error = data.error;
            setQueries(updatedQueries);
            setStatus('idle');
          } else if (data.type === 'source' && showSources) {
            const updatedQueries = [...queries];
            updatedQueries[updatedQueries.length - 1].sources = data.source;
            setQueries(updatedQueries);
          } else {
            const result = data.answer ? data.answer : ''; //Fallback to an empty string if data.answer is undefined
            const streamingResponse = queries[queries.length - 1].response
              ? queries[queries.length - 1].response
              : '';
            const updatedQueries = [...queries];
            updatedQueries[updatedQueries.length - 1].response =
              streamingResponse + result;
            setQueries(updatedQueries);
          }
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

    setEventInterrupt(false);
    queries.push({ prompt: userQuery });
    setPrompt('');
    await stream(userQuery);
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
            <Conversation
              ref={conversationRef}
              onWheel={handleUserInterrupt}
              onTouchMove={handleUserInterrupt}
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

                          {collectFeedback && (
                            <Feedback>
                              <button
                                style={{
                                  backgroundColor: 'transparent',
                                  border: 'none',
                                  cursor: 'pointer',
                                }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleFeedback('LIKE', index);
                                }}
                              >
                                <LikeIcon
                                  style={{
                                    stroke:
                                      query.feedback == 'LIKE'
                                        ? '#8860DB'
                                        : '#c0c0c0',
                                    visibility:
                                      query.feedback == 'LIKE'
                                        ? 'visible'
                                        : 'hidden',
                                  }}
                                  fill="none"
                                />
                              </button>
                              <button
                                style={{
                                  backgroundColor: 'transparent',
                                  border: 'none',
                                  cursor: 'pointer',
                                }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleFeedback('DISLIKE', index);
                                }}
                              >
                                <DislikeIcon
                                  style={{
                                    stroke:
                                      query.feedback == 'DISLIKE'
                                        ? '#ed8085'
                                        : '#c0c0c0',
                                    visibility:
                                      query.feedback == 'DISLIKE'
                                        ? 'visible'
                                        : 'hidden',
                                  }}
                                  fill="none"
                                />
                              </button>
                            </Feedback>
                          )}
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
                              </div>
                            </ErrorAlert>
                          ) : (
                            <MessageBubble $type="ANSWER">
                              <Message
                                $type="ANSWER"
                                style={{ fontWeight: 600 }}
                              >
                                <DotAnimation>.</DotAnimation>
                                <Delay $delay={200}>.</Delay>
                                <Delay $delay={400}>.</Delay>
                              </Message>
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
                <StyledButton
                  disabled={prompt.trim().length == 0 || status !== 'idle'}
                >
                  <PaperPlaneIcon width={18} height={18} color="white" />
                </StyledButton>
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

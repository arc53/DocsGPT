import React from 'react';
import styled, { ThemeProvider, css, keyframes } from 'styled-components';
import { WidgetCore } from './DocsGPTWidget';
import { AgentAvatar, PoweredBy } from './Branding';
import {
  focusRing,
  fonts,
  InterFontFace,
  radii,
  shadows,
  themes,
} from './tokens';
import {
  CornerDownLeft,
  ExternalLink,
  FileText,
  Globe,
  Mic,
  Search,
} from './icons';
import { MicButton, VoiceWaveform } from './ComposerControls';
import { useBackDismiss } from '../hooks/useBackDismiss';
import { useDictation } from '../hooks/useDictation';
import { useVisualViewportBounds } from '../hooks/useVisualViewportBounds';
import { SearchBarProps } from '@/types';
import { getSearchResults } from '../requests/searchAPI';
import { Result } from '@/types';
import {
  getOS,
  isTouchPrimary,
  isWebSource,
  processMarkdownString,
} from '../utils/helper';
import DOMPurify from 'dompurify';

type Shape = NonNullable<SearchBarProps['shape']>;

const fadeIn = keyframes`
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
`;

// The dialog's entrance: fade and zoom in from 95%.
const zoomIn = keyframes`
  from {
    opacity: 0;
    transform: translateX(-50%) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) scale(1);
  }
`;

// The popover's entrance: fade, zoom from 95% and slide down 8px.
const popIn = keyframes`
  from {
    opacity: 0;
    transform: translateY(-8px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: none;
  }
`;

const slideUp = keyframes`
  from {
    transform: translateY(100%);
  }
  to {
    transform: none;
  }
`;

const Main = styled.div`
  all: initial;
  font-family: ${fonts.sans};
  /* all: initial re-enables Safari's text auto-inflation. */
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
`;

const Container = styled.div`
  position: relative;
  display: inline-block;
  max-width: 100%;
`;

// SearchInput: the app's 38px field, a pill or square (rounded-md) corners.
const field = css<{ $shape: Shape; $inputWidth: string }>`
  box-sizing: border-box;
  position: relative;
  display: flex;
  align-items: center;
  width: ${(props) => props.$inputWidth};
  max-width: 100%;
  height: 38px;
  margin: 0;
  font-family: inherit;
  font-size: 14px;
  text-align: left;
  color: ${(props) => props.theme.mutedForeground};
  background-color: ${(props) => props.theme.controlFill};
  border: 1px solid ${(props) => props.theme.border};
  border-radius: ${(props) =>
    props.$shape === 'rounded' ? radii.md : radii.full};
  box-shadow: ${shadows.xs};
  transition:
    border-color 0.15s ease,
    box-shadow 0.15s ease;

  & > svg {
    position: absolute;
    left: ${(props) => (props.$shape === 'rounded' ? '12px' : '16px')};
    top: 50%;
    transform: translateY(-50%);
    color: ${(props) => props.theme.mutedForeground};
    pointer-events: none;
  }
`;

const fieldFocus = css`
  border-color: ${(props) => props.theme.ring};
  box-shadow: 0 0 0 3px ${(props) => props.theme.ringSoft};
`;

const SearchButton = styled.button<{ $shape: Shape; $inputWidth: string }>`
  ${field}
  padding: 0 ${(props) => (props.$shape === 'rounded' ? '12px' : '16px')} 0
    ${(props) => (props.$shape === 'rounded' ? '36px' : '40px')};
  cursor: text;
  -webkit-appearance: none;
  appearance: none;

  &:focus-visible {
    outline: none;
    ${fieldFocus}
  }
`;

// The dropdown's field: a real input in the same frame.
const FieldFrame = styled.div<{ $shape: Shape; $inputWidth: string }>`
  ${field}
  padding: 0 4px 0 ${(props) => (props.$shape === 'rounded' ? '36px' : '40px')};
  gap: 4px;
  cursor: text;

  &:focus-within {
    ${fieldFocus}
  }
`;

const FieldInput = styled.input`
  flex: 1;
  min-width: 0;
  height: 100%;
  margin: 0;
  padding: 0;
  font-family: inherit;
  font-size: 14px;
  color: ${(props) => props.theme.foreground};
  background: transparent;
  border: none;
  outline: none;

  &::placeholder {
    color: ${(props) => props.theme.mutedForeground};
    opacity: 1;
  }

  /* iOS Safari zooms the page in on any field under 16px. */
  @media (pointer: coarse) {
    font-size: 16px;
  }
`;

// ghost-muted icon-xs inside the field; red while recording.
const FieldMic = styled.button<{ $recording?: boolean }>`
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: ${radii.full};
  background: transparent;
  color: ${(props) =>
    props.$recording ? props.theme.destructive : props.theme.mutedForeground};
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease;

  &:hover:not(:disabled) {
    background-color: ${(props) => props.theme.accent};
    color: ${(props) =>
      props.$recording ? props.theme.destructive : props.theme.foreground};
  }

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }

  ${focusRing}
`;

const RecordingGlyph = styled.span`
  display: block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background-color: currentColor;
`;

const ButtonLabel = styled.span`
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
`;

// CommandShortcut: plain muted text, no key cap.
const Shortcut = styled.kbd`
  flex-shrink: 0;
  margin: 0 8px;
  font-family: inherit;
  font-size: 12px;
  letter-spacing: 0.1em;
  color: ${(props) => props.theme.mutedForeground};
  pointer-events: none;
`;

// overlayScrim
const SearchOverlay = styled.div`
  position: fixed;
  inset: 0;
  /* Over the chat launcher (500), under the chat panel it opens (999+). */
  z-index: 997;
  background-color: ${(props) => props.theme.scrim};
  -webkit-backdrop-filter: blur(4px);
  backdrop-filter: blur(4px);
  animation: ${fadeIn} 200ms ease-out;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;

// CommandDialog at the app's dialog recipe; a bottom sheet on phones.
const SearchDialog = styled.div`
  position: fixed;
  /* Anchored near the top so the box grows downwards as results arrive. */
  top: max(12vh, 24px);
  left: 50%;
  z-index: 998;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: calc(100% - 32px);
  max-width: 672px;
  max-height: min(560px, 76vh);
  overflow: hidden;
  color: ${(props) => props.theme.foreground};
  background-color: ${(props) => props.theme.card};
  border-radius: ${radii['2xl']};
  box-shadow: ${shadows.modal};
  transform: translateX(-50%);
  animation: ${zoomIn} 200ms ease-out;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }

  @media only screen and (max-width: 768px) {
    top: auto;
    left: 0;
    right: 0;
    /* Above an open keyboard; see useVisualViewportBounds. */
    bottom: var(--dgpt-vv-bottom, 0px);
    width: 100%;
    max-width: none;
    max-height: calc(var(--dgpt-vv-height, 100dvh) - 48px);
    border-radius: ${radii['2xl']} ${radii['2xl']} 0 0;
    transform: none;
    animation: ${slideUp} 250ms cubic-bezier(0.16, 1, 0.3, 1);

    @media (prefers-reduced-motion: reduce) {
      animation: none;
    }
  }
`;

// The app's popover: card fill, border, rounded-xl, shadow-md. Placed in
// fixed coordinates under the field so it never runs off the screen.
const SearchDropdown = styled.div`
  position: fixed;
  z-index: 998;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: ${(props) => props.theme.foreground};
  background-color: ${(props) => props.theme.card};
  border: 1px solid ${(props) => props.theme.border};
  border-radius: ${radii.xl};
  box-shadow: ${shadows.md};
  transform-origin: top left;
  animation: ${popIn} 150ms ease-out;

  @media (prefers-reduced-motion: reduce) {
    animation: none;
  }
`;

// SheetHandle
const SheetHandle = styled.div`
  display: none;
  flex-shrink: 0;
  width: 48px;
  height: 6px;
  margin: 8px auto 0;
  border-radius: ${radii.full};
  background-color: ${(props) => props.theme.border};

  @media only screen and (max-width: 768px) {
    display: block;
  }
`;

// CommandInput, palette variant: a 48px row over the list.
const SearchHeader = styled.div`
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
  min-height: 48px;
  padding: 0 12px;
  border-bottom: 1px solid ${(props) => props.theme.border};

  & > svg {
    flex-shrink: 0;
    color: ${(props) => props.theme.foreground};
    opacity: 0.5;
  }
`;

const TextField = styled.input<{ $hidden?: boolean }>`
  ${(props) => (props.$hidden ? 'display: none;' : '')}
  flex: 1;
  min-width: 0;
  height: 48px;
  margin: 0;
  padding: 0;
  font-family: inherit;
  font-size: 14px;
  color: ${(props) => props.theme.foreground};
  background-color: transparent;
  border: none;
  outline: none;

  &::placeholder {
    color: ${(props) => props.theme.mutedForeground};
    opacity: 1;
  }

  /* iOS Safari zooms the page in on any field under 16px. */
  @media (pointer: coarse) {
    font-size: 16px;
  }
`;

const SearchNote = styled.div`
  padding: 8px 12px 0;
  font-size: 12px;
  line-height: 1.5;
  color: ${(props) => props.theme.destructive};
`;

// CommandList
const SearchResultsScroll = styled.div`
  flex: 1;
  min-height: 0;
  padding: 4px;
  overflow-x: hidden;
  overflow-y: auto;
  scroll-padding: 4px;
  scrollbar-width: thin;
  scrollbar-color: ${(props) => props.theme.scrollbarThumb} transparent;
`;

// CommandItem: accent while highlighted, by pointer or arrow keys.
const Row = styled.div<{ $active?: boolean }>`
  box-sizing: border-box;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  padding: 8px;
  border-radius: ${radii.sm};
  font-size: 14px;
  color: ${(props) => props.theme.foreground};
  background-color: ${(props) =>
    props.$active ? props.theme.accent : 'transparent'};
  text-decoration: none;
  cursor: default;
  user-select: none;
  overflow-wrap: break-word;

  & > svg {
    flex-shrink: 0;
    margin-top: 2px;
    color: ${(props) => props.theme.mutedForeground};
  }

  & > svg.dgpt-row-external {
    margin-top: 4px;
  }
`;

const AskRow = styled(Row)`
  align-items: center;
`;

const AskLabel = styled.span`
  flex-shrink: 0;
  font-weight: 500;
`;

const AskQuery = styled.span`
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: ${(props) => props.theme.mutedForeground};
`;

const RowHint = styled.span`
  display: inline-flex;
  flex-shrink: 0;
  margin-left: auto;
  color: ${(props) => props.theme.mutedForeground};
`;

const RowText = styled.div`
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
`;

const RowTitle = styled.span`
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
`;

// The matching lines, as the app shows a match snippet: 12px, two lines.
const RowSnippet = styled.div`
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.5;
  color: ${(props) => props.theme.mutedForeground};

  & > span + span::before {
    content: ' · ';
  }

  code {
    font-family: ${fonts.mono};
    font-size: 11px;
  }

  /* The matched words, as the app marks them. Scoped so the host page's
     own .highlight elements are untouched. */
  .highlight {
    color: ${(props) => props.theme.primary};
    font-weight: 600;
  }

  a {
    color: inherit;
    text-decoration: none;
  }
`;

const Status = styled.div`
  padding: 12px;
  font-size: 12px;
  color: ${(props) => props.theme.mutedForeground};
`;

const RowLink = styled.a`
  display: block;
  border-radius: ${radii.sm};
  text-decoration: none;
  ${focusRing}
`;

const Footer = styled.div`
  flex-shrink: 0;
  border-top: 1px solid ${(props) => props.theme.border};
`;

type Item = { kind: 'ask' } | { kind: 'result'; result: Result };

type DropdownBox = {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
};

/** Where the dropdown goes: under the field, inside the visible viewport. */
const measureDropdown = (field: HTMLElement): DropdownBox => {
  const rect = field.getBoundingClientRect();
  const viewport = window.visualViewport;
  const viewWidth = viewport?.width ?? window.innerWidth;
  const viewBottom = viewport
    ? viewport.offsetTop + viewport.height
    : window.innerHeight;
  const gutter = 16;
  const width = Math.min(Math.max(rect.width, 560), viewWidth - gutter * 2);
  const left = Math.min(
    Math.max(rect.left, gutter),
    viewWidth - width - gutter,
  );
  const top = rect.bottom + 6;
  return {
    top,
    left,
    width,
    maxHeight: Math.max(160, Math.min(480, viewBottom - top - gutter)),
  };
};

export const SearchBar = ({
  apiKey = '74039c6d-bff7-44ce-ae55-2973cbf13837',
  apiHost = 'https://gptcloud.arc53.com',
  theme = 'dark',
  placeholder = 'Search or Ask AI...',
  width = '256px',
  buttonText = 'Search here',
  shape = 'pill',
  variant = 'modal',
  avatar,
  poweredBy = true,
  allowedFileExtensions,
  showMicButton,
}: SearchBarProps) => {
  const isDropdown = variant === 'dropdown';
  const [input, setInput] = React.useState<string>('');
  const [loading, setLoading] = React.useState<boolean>(false);
  const [failed, setFailed] = React.useState<boolean>(false);
  const [isWidgetOpen, setIsWidgetOpen] = React.useState<boolean>(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const fieldRef = React.useRef<HTMLDivElement>(null);
  const resultsRef = React.useRef<HTMLDivElement | null>(null);
  const listRef = React.useRef<HTMLDivElement | null>(null);
  // Modal: the dialog is open. Dropdown: the field is in use.
  const [isResultVisible, setIsResultVisible] = React.useState<boolean>(false);
  const [results, setResults] = React.useState<Result[]>([]);
  const [dropdownBox, setDropdownBox] = React.useState<DropdownBox | null>(
    null,
  );
  // The highlighted row among the ones that do something (Ask, web pages).
  const [activeIndex, setActiveIndex] = React.useState(0);
  const listId = React.useId();
  const debounceTimeout = React.useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const abortControllerRef = React.useRef<AbortController | null>(null);
  const getSearchDraft = React.useCallback(
    () => inputRef.current?.value ?? '',
    [],
  );
  // Deferred until the input is unhidden; hidden fields can't take focus.
  const focusSearchInput = React.useCallback(() => {
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }, []);
  const dictation = useDictation({
    enabled: Boolean(showMicButton),
    getDraft: getSearchDraft,
    onDraftChange: setInput,
    separator: ' ',
    onEnd: focusSearchInput,
  });
  const browserOS = getOS();
  // A touchscreen laptop still has Ctrl+K; this asks if touch is the only
  // way in.
  const [isTouch] = React.useState(isTouchPrimary);

  const query = input.trim();
  // The dropdown shows once there is something to search for, or a voice
  // error to explain.
  const showPanel = isDropdown
    ? isResultVisible && (query.length > 0 || Boolean(dictation.error))
    : isResultVisible;

  useVisualViewportBounds(!isDropdown && isResultVisible, resultsRef);
  // Touch only: nothing fills the screen on desktop.
  useBackDismiss(!isDropdown && isResultVisible && isTouch, () =>
    setIsResultVisible(false),
  );

  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsResultVisible(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        ((browserOS === 'win' || browserOS === 'linux') &&
          event.ctrlKey &&
          event.key === 'k') ||
        (browserOS === 'mac' && event.metaKey && event.key === 'k')
      ) {
        event.preventDefault();
        inputRef.current?.focus();
        setIsResultVisible(true);
      } else if (event.key === 'Escape') {
        setIsResultVisible(false);
        if (isDropdown) inputRef.current?.blur();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isDropdown]);

  // The dropdown follows its field through scrolling, resizing and an
  // opening keyboard.
  React.useLayoutEffect(() => {
    if (!isDropdown || !showPanel) return;
    const place = () => {
      if (fieldRef.current) setDropdownBox(measureDropdown(fieldRef.current));
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    window.visualViewport?.addEventListener('resize', place);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
      window.visualViewport?.removeEventListener('resize', place);
    };
  }, [isDropdown, showPanel]);

  React.useEffect(() => {
    setFailed(false);
    if (!query) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    if (debounceTimeout.current) {
      clearTimeout(debounceTimeout.current);
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    debounceTimeout.current = setTimeout(() => {
      getSearchResults(input, apiKey, apiHost, abortController.signal)
        .then((data) => setResults(data))
        .catch((err) => {
          if (abortController.signal.aborted) return;
          console.warn('Search failed:', err);
          setResults([]);
          setFailed(true);
        })
        // A cancelled search must not end the loading state of the one
        // that replaced it.
        .finally(() => {
          if (!abortController.signal.aborted) setLoading(false);
        });
    }, 500);

    return () => {
      abortController.abort();
      clearTimeout(debounceTimeout.current ?? undefined);
    };
  }, [input]);

  // Stop recording if the search closes mid-dictation.
  React.useEffect(() => {
    if (!isResultVisible && dictation.isDictating) dictation.stop();
  }, [isResultVisible, dictation.isDictating, dictation.stop]);

  const snippets = React.useMemo(
    () =>
      results.map((result) => ({
        result,
        lines: processMarkdownString(result.text, query).slice(0, 2),
      })),
    [results, query],
  );
  // Rows the keyboard can land on, in order: Ask, then every web page.
  const items: Item[] = React.useMemo(
    () => [
      { kind: 'ask' },
      ...results
        .filter((result) => isWebSource(result.source))
        .map((result) => ({ kind: 'result' as const, result })),
    ],
    [results],
  );

  // A new list starts on Ask, so Enter still asks the AI.
  React.useEffect(() => setActiveIndex(0), [results]);

  React.useEffect(() => {
    listRef.current
      ?.querySelector(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex]);

  const openWidget = () => {
    setIsWidgetOpen(true);
    setIsResultVisible(false);
  };

  const activate = (item: Item | undefined) => {
    if (!item) return;
    if (item.kind === 'ask') openWidget();
    else window.open(item.result.source, '_blank', 'noopener,noreferrer');
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setIsResultVisible(true);
      setActiveIndex((index) => Math.min(index + 1, items.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      // Mid-dictation the draft is still an interim transcript.
      if (query && !dictation.isDictating) activate(items[activeIndex]);
    }
  };

  const handleClose = () => {
    setIsWidgetOpen(false);
    setIsResultVisible(!isDropdown);
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (dictation.error) dictation.clearError();
    setInput(event.target.value);
    setIsResultVisible(true);
  };

  const optionId = (index: number) => `${listId}-option-${index}`;
  const webIndex = (result: Result) =>
    items.findIndex((item) => item.kind === 'result' && item.result === result);

  const shortcut = browserOS === 'mac' ? '⌘K' : 'Ctrl K';

  const comboboxProps = {
    role: 'combobox',
    'aria-expanded': showPanel,
    'aria-controls': listId,
    'aria-activedescendant': showPanel ? optionId(activeIndex) : undefined,
    'aria-autocomplete': 'list' as const,
    'aria-label': placeholder,
  };

  const renderSnippet = (lines: ReturnType<typeof processMarkdownString>) =>
    lines.length > 0 && (
      <RowSnippet>
        {lines.map((line, index) => (
          <span
            key={index}
            dangerouslySetInnerHTML={{
              __html: DOMPurify.sanitize(
                line.tag === 'code'
                  ? `<code>${line.content}</code>`
                  : line.content,
              ),
            }}
          />
        ))}
      </RowSnippet>
    );

  const list = (
    <SearchResultsScroll
      ref={listRef}
      id={listId}
      role="listbox"
      aria-label={placeholder}
    >
      <AskRow
        id={optionId(0)}
        data-index={0}
        role="option"
        aria-selected={activeIndex === 0}
        aria-disabled={dictation.isDictating || undefined}
        $active={activeIndex === 0}
        onMouseMove={() => setActiveIndex(0)}
        // Keeps the dropdown's field focused through the click.
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => !dictation.isDictating && openWidget()}
      >
        <AgentAvatar src={avatar} size={24} fallback="person" />
        <AskLabel>Ask the AI</AskLabel>
        {query && <AskQuery>{query}</AskQuery>}
        {activeIndex === 0 && !isTouch && (
          <RowHint aria-hidden="true">
            <CornerDownLeft size={14} />
          </RowHint>
        )}
      </AskRow>
      {query && loading && <Status>Searching…</Status>}
      {query && !loading && failed && (
        <Status>Search didn&apos;t work. You can still ask the AI.</Status>
      )}
      {query && !loading && !failed && results.length === 0 && (
        <Status>No results found</Status>
      )}
      {!loading &&
        snippets.map(({ result, lines }, key) => {
          if (!isWebSource(result.source))
            return (
              <Row key={key}>
                <FileText size={16} />
                <RowText>
                  <RowTitle>{result.title}</RowTitle>
                  {renderSnippet(lines)}
                </RowText>
              </Row>
            );
          const index = webIndex(result);
          return (
            <RowLink
              key={key}
              href={result.source}
              target="_blank"
              rel="noopener noreferrer"
              tabIndex={-1}
            >
              <Row
                id={optionId(index)}
                data-index={index}
                role="option"
                aria-selected={activeIndex === index}
                $active={activeIndex === index}
                onMouseMove={() => setActiveIndex(index)}
              >
                <Globe size={16} />
                <RowText>
                  <RowTitle>{result.title}</RowTitle>
                  {renderSnippet(lines)}
                </RowText>
                <ExternalLink size={12} className="dgpt-row-external" />
              </Row>
            </RowLink>
          );
        })}
    </SearchResultsScroll>
  );

  const footer = poweredBy !== false && (
    <Footer>
      <PoweredBy value={poweredBy} />
    </Footer>
  );

  return (
    <ThemeProvider theme={themes[theme]}>
      {/* The field is always on the page, so its face loads with it. */}
      <InterFontFace />
      <Main>
        <Container
          ref={containerRef}
          onBlur={(event) => {
            // Focus leaving the search bar (Tab past the field, the mic or
            // the credit link) closes the dropdown. Clicks inside keep focus.
            if (
              isDropdown &&
              !containerRef.current?.contains(event.relatedTarget)
            )
              setIsResultVisible(false);
          }}
        >
          {isDropdown ? (
            <FieldFrame
              ref={fieldRef}
              $shape={shape}
              $inputWidth={width}
              onClick={() => inputRef.current?.focus()}
            >
              <Search size={16} />
              <FieldInput
                ref={inputRef}
                value={input}
                onChange={handleInputChange}
                onFocus={() => setIsResultVisible(true)}
                onKeyDown={handleKeyDown}
                placeholder={buttonText}
                readOnly={dictation.isDictating}
                {...comboboxProps}
              />
              {!isTouch && !isResultVisible && !input && (
                <Shortcut>{shortcut}</Shortcut>
              )}
              {dictation.available && (
                <FieldMic
                  type="button"
                  $recording={dictation.state === 'recording'}
                  disabled={dictation.state === 'transcribing'}
                  aria-label={
                    dictation.state === 'recording'
                      ? 'Stop recording'
                      : 'Voice input'
                  }
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    setIsResultVisible(true);
                    dictation.toggle();
                  }}
                >
                  {dictation.state === 'recording' ? (
                    <RecordingGlyph />
                  ) : (
                    <Mic size={16} />
                  )}
                </FieldMic>
              )}
            </FieldFrame>
          ) : (
            <SearchButton
              type="button"
              onClick={() => setIsResultVisible(true)}
              $shape={shape}
              $inputWidth={width}
              aria-haspopup="dialog"
            >
              <Search size={16} />
              <ButtonLabel>{buttonText}</ButtonLabel>
              {!isTouch && <Shortcut>{shortcut}</Shortcut>}
            </SearchButton>
          )}
          {isDropdown && showPanel && dropdownBox && (
            <SearchDropdown
              ref={resultsRef}
              // Keeps the field focused, so a click in the panel doesn't
              // blur it closed; links still open on click.
              onMouseDown={(event) => event.preventDefault()}
              style={{
                top: dropdownBox.top,
                left: dropdownBox.left,
                width: dropdownBox.width,
                maxHeight: dropdownBox.maxHeight,
              }}
            >
              {dictation.error && (
                <SearchNote role="alert">{dictation.error}</SearchNote>
              )}
              {list}
              {footer}
            </SearchDropdown>
          )}
          {!isDropdown && isResultVisible && (
            <>
              <SearchOverlay onClick={() => setIsResultVisible(false)} />
              <SearchDialog
                ref={resultsRef}
                role="dialog"
                aria-modal="true"
                aria-label={placeholder}
              >
                <SheetHandle aria-hidden="true" />
                <SearchHeader>
                  <Search size={20} />
                  {dictation.isDictating && (
                    <VoiceWaveform
                      analyserRef={dictation.analyserRef}
                      label={
                        dictation.state === 'recording'
                          ? 'Listening…'
                          : 'Finishing…'
                      }
                      minHeight="48px"
                    />
                  )}
                  <TextField
                    $hidden={dictation.isDictating}
                    ref={inputRef}
                    value={input}
                    onChange={handleInputChange}
                    onKeyDown={handleKeyDown}
                    placeholder={placeholder}
                    /* A keyboard would cover the results. */
                    autoFocus={!isTouch}
                    {...comboboxProps}
                    aria-expanded="true"
                  />
                  {dictation.available && (
                    <MicButton
                      variant="icon"
                      state={dictation.state}
                      onClick={dictation.toggle}
                    />
                  )}
                </SearchHeader>
                {dictation.error && (
                  <SearchNote role="alert">{dictation.error}</SearchNote>
                )}
                {list}
                {footer}
              </SearchDialog>
            </>
          )}
        </Container>
        <WidgetCore
          theme={theme}
          apiHost={apiHost}
          apiKey={apiKey}
          avatar={avatar}
          poweredBy={poweredBy}
          prefilledQuery={input}
          isOpen={isWidgetOpen}
          handleClose={handleClose}
          size={'large'}
          allowedFileExtensions={allowedFileExtensions}
          showMicButton={showMicButton}
        />
      </Main>
    </ThemeProvider>
  );
};

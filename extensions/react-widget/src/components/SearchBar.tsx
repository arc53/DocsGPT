import React from 'react';
import styled, { ThemeProvider, keyframes } from 'styled-components';
import { WidgetCore } from './DocsGPTWidget';
import { DEFAULT_AVATAR } from './defaultAvatar';
import { radii, themes } from './tokens';
import { MicButton, VoiceWaveform } from './ComposerControls';
import { useDictation } from '../hooks/useDictation';
import { SearchBarProps } from '@/types';
import { getSearchResults } from '../requests/searchAPI';
import { Result } from '@/types';
import { getOS, processMarkdownString } from '../utils/helper';
import DOMPurify from 'dompurify';
import {
  CodeIcon,
  TextAlignLeftIcon,
  HeadingIcon,
  ReaderIcon,
  ListBulletIcon,
  QuoteIcon,
} from '@radix-ui/react-icons';

const spin = keyframes`
  to {
    transform: rotate(360deg);
  }
`;

const Main = styled.div`
  all: initial;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
`;

const SearchButton = styled.button<{ $inputWidth: string }>`
  box-sizing: border-box;
  width: ${({ $inputWidth }) => $inputWidth};
  height: 36px;
  padding: 0 72px 0 12px;
  font-family: inherit;
  font-size: 14px;
  text-align: left;
  color: ${(props) => props.theme.secondary.text};
  background-color: ${(props) => props.theme.secondary.bg};
  border: 1px solid ${(props) => props.theme.hairline};
  border-radius: ${radii.sm};
  outline: none;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  transition:
    color 0.15s ease,
    border-color 0.15s ease;

  &:hover {
    color: ${(props) => props.theme.primary.text};
  }

  &:focus-visible {
    border-color: ${(props) => props.theme.accent!.base};
    box-shadow: 0 0 0 3px ${(props) => props.theme.accent!.soft};
  }
`;

const Container = styled.div`
  position: relative;
  display: inline-block;
`;

const SearchOverlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 99;
  background-color: rgba(0, 0, 0, 0.5);
`;

const SearchResults = styled.div`
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 100;
  transform: translate(-50%, -50%);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 792px;
  max-width: 90vw;
  height: 396px;
  padding: 8px 0;
  overflow: hidden;
  color: ${(props) => props.theme.primary.text};
  background-color: ${(props) => props.theme.primary.bg};
  border: 1px solid ${(props) => props.theme.hairline};
  border-radius: ${radii.panel};
  box-shadow:
    0 12px 44px rgba(0, 0, 0, 0.18),
    0 2px 8px rgba(0, 0, 0, 0.1);

  @media only screen and (max-width: 768px) {
    width: 90vw;
    height: 80vh;
  }
`;

const SearchResultsScroll = styled.div`
  flex: 1;
  padding: 0 16px;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: ${(props) => props.theme.hairline} transparent;
`;

const IconTitleWrapper = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  color: ${(props) => props.theme.secondary.text};

  .element-icon {
    margin: 4px;
  }
`;

const Title = styled.h3`
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: ${(props) => props.theme.primary.text};
  overflow-wrap: break-word;
`;

const ContentWrapper = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
`;

const ResultWrapper = styled.div`
  box-sizing: border-box;
  display: flex;
  align-items: flex-start;
  width: 100%;
  padding: 10px 12px;
  overflow: hidden;
  overflow-wrap: break-word;
  word-break: break-word;
  border-radius: ${radii.sm};
  cursor: pointer;
  transition: background-color 0.15s ease;

  &:hover {
    background-color: ${(props) => props.theme.secondary.bg};
  }
`;

const Content = styled.div`
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-left: 7px;
  padding: 2px 0 0 14px;
  overflow: hidden;
  font-size: 14px;
  line-height: 1.6;
  color: ${(props) => props.theme.secondary.text};
  border-left: 2px solid ${(props) => props.theme.hairline};

  /* Scoped so the host page's own .highlight elements are untouched. */
  .highlight {
    padding: 1px 2px;
    border-radius: 4px;
    font-weight: 500;
    color: ${(props) => props.theme.primary.text};
    background-color: ${(props) => props.theme.accent!.mark};
  }

  /* Snippet HTML can contain raw links. */
  a {
    color: ${(props) => props.theme.accent!.link};
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  a:hover {
    color: ${(props) => props.theme.accent!.base};
  }
`;

const ContentSegment = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding-right: 16px;
  overflow: hidden;
  overflow-wrap: break-word;
`;

const Toolkit = styled.kbd`
  position: absolute;
  top: 50%;
  right: 8px;
  z-index: 1;
  transform: translateY(-50%);
  padding: 2px 6px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.6;
  white-space: nowrap;
  color: ${(props) => props.theme.secondary.text};
  background-color: ${(props) => props.theme.primary.bg};
  border: 1px solid ${(props) => props.theme.hairline};
  border-radius: ${radii.sm};
  pointer-events: none;
`;

const Loader = styled.div`
  width: 16px;
  height: 16px;
  margin: 2rem auto;
  border: 2px solid ${(props) => props.theme.hairline};
  border-top-color: ${(props) => props.theme.accent!.base};
  border-radius: 50%;
  animation: ${spin} 0.8s linear infinite;
`;

const NoResults = styled.div`
  margin-top: 2rem;
  font-size: 14px;
  text-align: center;
  color: ${(props) => props.theme.secondary.text};
`;

const AskAIButton = styled.button`
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 12px;
  width: calc(100% - 32px);
  margin: 0 16px 12px;
  padding: 10px 12px;
  font-family: inherit;
  font-size: 15px;
  font-weight: 500;
  text-align: left;
  color: ${(props) => props.theme.primary.text};
  background-color: ${(props) => props.theme.secondary.bg};
  border: 1px solid ${(props) => props.theme.hairline};
  border-radius: ${radii.md};
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease;

  &:hover:not(:disabled) {
    background-color: ${(props) => props.theme.accent!.soft};
    border-color: ${(props) => props.theme.accent!.soft};
  }

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }

  &:focus-visible {
    outline: 2px solid ${(props) => props.theme.accent!.base};
    outline-offset: 2px;
  }
`;

const SearchHeader = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 4px 16px 12px;
  border-bottom: 1px solid ${(props) => props.theme.hairline};
`;

const TextField = styled.input<{ $hidden?: boolean }>`
  ${(props) => (props.$hidden ? 'display: none;' : '')}
  flex: 1;
  min-width: 0;
  padding: 8px 0;
  font-family: inherit;
  font-size: 18px;
  color: ${(props) => props.theme.primary.text};
  background-color: transparent;
  border: none;
  outline: none;

  &::placeholder {
    color: ${(props) => props.theme.secondary.text};
    opacity: 1;
  }
`;

const EscapeInstruction = styled.kbd`
  flex-shrink: 0;
  padding: 2px 8px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.6;
  white-space: nowrap;
  color: ${(props) => props.theme.secondary.text};
  background-color: ${(props) => props.theme.secondary.bg};
  border: 1px solid ${(props) => props.theme.hairline};
  border-radius: ${radii.sm};
  cursor: pointer;
`;

const SearchNote = styled.div`
  margin: -4px 16px 8px;
  font-size: 12px;
  line-height: 1.5;
  color: ${(props) => props.theme.danger!.text};
`;

export const SearchBar = ({
  apiKey = '74039c6d-bff7-44ce-ae55-2973cbf13837',
  apiHost = 'https://gptcloud.arc53.com',
  theme = 'dark',
  placeholder = 'Search or Ask AI...',
  width = '256px',
  buttonText = 'Search here',
  allowedFileExtensions,
  showMicButton,
}: SearchBarProps) => {
  const [input, setInput] = React.useState<string>('');
  const [loading, setLoading] = React.useState<boolean>(false);
  const [isWidgetOpen, setIsWidgetOpen] = React.useState<boolean>(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const containerRef = React.useRef<HTMLInputElement>(null);
  const [isResultVisible, setIsResultVisible] = React.useState<boolean>(false);
  const [results, setResults] = React.useState<Result[]>([]);
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
  const isTouch = 'ontouchstart' in window;

  const getKeyboardInstruction = () => {
    if (isResultVisible) return 'Enter';
    return browserOS === 'mac' ? '⌘ + K' : 'Ctrl + K';
  };

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
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  React.useEffect(() => {
    if (!input) {
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
        .catch((err) => !abortController.signal.aborted && console.log(err))
        .finally(() => setLoading(false));
    }, 500);

    return () => {
      abortController.abort();
      clearTimeout(debounceTimeout.current ?? undefined);
    };
  }, [input]);

  // Stop recording if the palette closes mid-dictation.
  React.useEffect(() => {
    if (!isResultVisible && dictation.isDictating) dictation.stop();
  }, [isResultVisible, dictation.isDictating, dictation.stop]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      openWidget();
    }
  };

  const openWidget = () => {
    setIsWidgetOpen(true);
    setIsResultVisible(false);
  };

  const handleClose = () => {
    setIsWidgetOpen(false);
    setIsResultVisible(true);
  };

  return (
    <ThemeProvider theme={themes[theme]}>
      <Main>
        <Container ref={containerRef}>
          <SearchButton
            onClick={() => setIsResultVisible(true)}
            $inputWidth={width}
          >
            {buttonText}
          </SearchButton>
          {isResultVisible && (
            <>
              <SearchOverlay onClick={() => setIsResultVisible(false)} />
              <SearchResults>
                <SearchHeader>
                  {dictation.isDictating && (
                    <VoiceWaveform
                      analyserRef={dictation.analyserRef}
                      label={
                        dictation.state === 'recording'
                          ? 'Listening…'
                          : 'Finishing…'
                      }
                      minHeight="36px"
                    />
                  )}
                  <TextField
                    $hidden={dictation.isDictating}
                    ref={inputRef}
                    value={input}
                    onChange={(e) => {
                      if (dictation.error) dictation.clearError();
                      setInput(e.target.value);
                    }}
                    onKeyDown={(e) => handleKeyDown(e)}
                    placeholder={placeholder}
                    autoFocus
                  />
                  {dictation.available && (
                    <MicButton
                      variant="icon"
                      state={dictation.state}
                      onClick={dictation.toggle}
                    />
                  )}
                  <EscapeInstruction onClick={() => setIsResultVisible(false)}>
                    Esc
                  </EscapeInstruction>
                </SearchHeader>
                {dictation.error && (
                  <SearchNote role="alert">{dictation.error}</SearchNote>
                )}
                <AskAIButton
                  onClick={openWidget}
                  disabled={dictation.isDictating}
                >
                  <img src={DEFAULT_AVATAR} alt="" width={24} height={24} />
                  <span>Ask the AI</span>
                </AskAIButton>
                <SearchResultsScroll>
                  {!loading ? (
                    results.length > 0 ? (
                      results.map((res, key) => {
                        const containsSource = res.source !== 'local';
                        const processedResults = processMarkdownString(
                          res.text,
                          input,
                        );
                        if (processedResults)
                          return (
                            <ResultWrapper
                              key={key}
                              onClick={() => {
                                if (!containsSource) return;
                                window.open(
                                  res.source,
                                  '_blank',
                                  'noopener, noreferrer',
                                );
                              }}
                            >
                              <div style={{ flex: 1 }}>
                                <ContentWrapper>
                                  <IconTitleWrapper>
                                    <ReaderIcon className="title-icon" />
                                    <Title>{res.title}</Title>
                                  </IconTitleWrapper>
                                  <Content>
                                    {processedResults.map((element, index) => (
                                      <ContentSegment key={index}>
                                        <IconTitleWrapper>
                                          {element.tag === 'code' && (
                                            <CodeIcon className="element-icon" />
                                          )}
                                          {(element.tag === 'bulletList' ||
                                            element.tag === 'numberedList') && (
                                            <ListBulletIcon className="element-icon" />
                                          )}
                                          {element.tag === 'text' && (
                                            <TextAlignLeftIcon className="element-icon" />
                                          )}
                                          {element.tag === 'heading' && (
                                            <HeadingIcon className="element-icon" />
                                          )}
                                          {element.tag === 'blockquote' && (
                                            <QuoteIcon className="element-icon" />
                                          )}
                                        </IconTitleWrapper>
                                        <div
                                          style={{ flex: 1 }}
                                          dangerouslySetInnerHTML={{
                                            __html: DOMPurify.sanitize(
                                              element.content,
                                            ),
                                          }}
                                        />
                                      </ContentSegment>
                                    ))}
                                  </Content>
                                </ContentWrapper>
                              </div>
                            </ResultWrapper>
                          );
                        return null;
                      })
                    ) : (
                      <NoResults>No results found</NoResults>
                    )
                  ) : (
                    <Loader />
                  )}
                </SearchResultsScroll>
              </SearchResults>
            </>
          )}
          {isTouch ? (
            <Toolkit
              onClick={() => {
                setIsWidgetOpen(true);
              }}
              title={'Tap to Ask the AI'}
            >
              Tap
            </Toolkit>
          ) : (
            <Toolkit
              title={
                getKeyboardInstruction() === 'Enter'
                  ? 'Press Enter to Ask AI'
                  : ''
              }
            >
              {getKeyboardInstruction()}
            </Toolkit>
          )}
        </Container>
        <WidgetCore
          theme={theme}
          apiHost={apiHost}
          apiKey={apiKey}
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

import React from 'react';
import styled, { ThemeProvider, createGlobalStyle } from 'styled-components';
import { WidgetCore } from './DocsGPTWidget';
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
    QuoteIcon
} from '@radix-ui/react-icons';
const themes = {
    dark: {
        name: 'dark',
        bg: '#202124',
        text: '#EDEDED',
        primary: {
            text: "#FAFAFA",
            bg: '#111111'
        },
        secondary: {
            text: "#A1A1AA",
            bg: "#38383b"
        }
    },
    light: {
        name: 'light',
        bg: '#EAEAEA',
        text: '#171717',
        primary: {
            text: "#222327",
            bg: "#fff"
        },
        secondary: {
            text: "#A1A1AA",
            bg: "#F6F6F6"
        }
    }
}

const GlobalStyle = createGlobalStyle`
  .highlight {
    color: ${props => props.theme.name === 'dark' ? '#4B9EFF' : '#0066CC'};
    font-weight: 500;
  }
`;

const loadGeistFont = () => {
    const link = document.createElement('link');
    link.href = 'https://fonts.googleapis.com/css2?family=Geist:wght@100..900&display=swap';
    link.rel = 'stylesheet';
    document.head.appendChild(link);
};

const Main = styled.div`
    all: initial;
    font-family: 'Geist', sans-serif;
`
const SearchButton = styled.button<{ inputWidth: string }>`
    padding: 6px 6px;
    font-family: inherit;
    width: ${({ inputWidth }) => inputWidth};
    border-radius: 8px;
    display: inline;
    color: ${props => props.theme.secondary.text};
    outline: none;
    border: none;
    background-color: ${props => props.theme.secondary.bg};
    -webkit-appearance: none;
    -moz-appearance: none;
    appearance: none;
    transition: background-color 128ms linear;
    text-align: left;
    cursor: pointer;
`

const Container = styled.div`
    position: relative;
    display: inline-block;
`
const SearchOverlay = styled.div`
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: #0000001A;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    z-index: 99;
`;


const SearchResults = styled.div`
    position: fixed;
    display: flex;
    flex-direction: column;
    background-color: ${props => props.theme.name === 'dark' ? 
        'rgba(0, 0, 0, 0.15)' : 
        'rgba(255, 255, 255, 0.4)'};
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 15px;
    padding: 8px 0px 8px 0px;
    width: 792px;
    max-width: 90vw;
    height: 396px;
    z-index: 100;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    color: ${props => props.theme.primary.text};
    
    box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
    backdrop-filter: blur(82px);
    -webkit-backdrop-filter: blur(82px);
    border-radius: 10px;
    
    box-sizing: border-box;

    @media only screen and (max-width: 768px) {
        height: 80vh;
        width: 90vw;
    }
`;

const SearchResultsScroll = styled.div`
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-gutter: stable;
    scrollbar-width: thin;
    scrollbar-color: #383838 transparent;
    padding: 0 16px;
`;

const IconTitleWrapper = styled.div`
    display: flex;
    align-items: center;
    gap: 8px;

    .element-icon{
        margin: 4px;
    }
`;

const Title = styled.h3`
    font-size: 15px;
    font-weight: 400;
    color: ${props => props.theme.primary.text};
    margin: 0;
    overflow-wrap: break-word;
    white-space: normal;
    overflow: hidden;
    text-overflow: ellipsis;
`;
const ContentWrapper = styled.div`
    display: flex;
    flex-direction: column;
    gap: 12px; 
`;



const ResultWrapper = styled.div`
    display: flex;
    align-items: flex-start;
    width: 100%;
    box-sizing: border-box;
    padding: 8px 16px;
    cursor: pointer;
    background-color: transparent;
    font-family: 'Geist', sans-serif;
    border-radius: 8px;

    word-wrap: break-word;
    overflow-wrap: break-word;
    word-break: break-word;
    white-space: normal;
    overflow: hidden;
    text-overflow: ellipsis;

    &:hover {
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
    }
`;

const Content = styled.div`
    display: flex;
    margin-left: 8px;
    flex-direction: column;
    gap: 8px;
    padding: 4px 0px 0px 12px;
    font-size: 15px;
    color: ${props => props.theme.primary.text};
    line-height: 1.6;
    border-left: 2px solid ${props => props.theme.primary.text}CC;
    overflow: hidden;
    
`;
const ContentSegment = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding-right: 16px;
    overflow-wrap: break-word;
    white-space: normal;
    overflow: hidden; 
    text-overflow: ellipsis;
`

const Toolkit = styled.kbd`
    position: absolute;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    background-color: ${(props) => props.theme.primary.bg};
    color: ${(props) => props.theme.secondary.text};
    font-weight: 600;
    font-size: 10px;
    padding: 3px 6px;
    border: 1px solid ${(props) => props.theme.secondary.text};
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1;
    pointer-events: none;
`
const Loader = styled.div`
  margin: 2rem auto;
  border: 4px solid ${props => props.theme.name === 'dark' ? 'rgba(255, 255, 255, 0.2)' : 'rgba(0, 0, 0, 0.1)'};
  border-top: 4px solid ${props => props.theme.name === 'dark' ? '#FFFFFF' : props.theme.primary.bg};
  border-radius: 50%;
  width: 12px;
  height: 12px;
  animation: spin 1s linear infinite;

  @keyframes spin {
    0% {
      transform: rotate(0deg);
    }
    100% {
      transform: rotate(360deg);
    }
  }
`;

const NoResults = styled.div`
  margin-top: 2rem;
  text-align: center;
  font-size: 14px;
  color: ${props => props.theme.name === 'dark' ? '#E0E0E0' : '#505050'};
  font-weight: 500;
`;
const AskAIButton = styled.button`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 12px;
    width: calc(100% - 32px);
    margin: 0 16px 16px 16px;
    box-sizing: border-box;
    height: 50px;
    padding: 8px 24px;
    border: none;
    border-radius: 8px;
    color: ${props => props.theme.text}; 
    cursor: pointer;
    font-size: 16px;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    background-color: ${props => props.theme.name === 'dark' ? 
        'rgba(255, 255, 255, 0.05)' : 
        'rgba(0, 0, 0, 0.03)'};

    &:hover {
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        background-color: ${props => props.theme.name === 'dark' ? 
            'rgba(255, 255, 255, 0.1)' : 
            'rgba(0, 0, 0, 0.06)'}; 
    }
`;

const SearchHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid ${props => props.theme.name === 'dark' ? '#FFFFFF24' : 'rgba(0, 0, 0, 0.14)'};
`;



const TextField = styled.input`
    width: calc(100% - 32px);
    margin: 0 16px;
    padding: 12px 16px;
    border: none;
    background-color: transparent;
    color: ${props => props.theme.text}; 
    font-size: 20px;
    font-weight: 400; 
    outline: none;
    
    &:focus {
        border-color: none;
    }

    &::placeholder {
        color: ${props => props.theme.name === 'dark' ? 'rgba(255, 255, 255, 0.6)' : 'rgba(0, 0, 0, 0.5)'} !important;
        opacity: 100%; /* Force opacity to ensure placeholder is visible */
        font-weight: 500;
    }
`



const EscapeInstruction = styled.kbd`
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 12px 16px 0;
    padding: 4px 8px;
    border-radius: 4px;
    background-color: transparent;
    border: 1px solid ${props => props.theme.name === 'dark' ? 
        'rgba(237, 237, 237, 0.6)' : 
        'rgba(23, 23, 23, 0.6)'};
    color: ${props => props.theme.name === 'dark' ? '#EDEDED' : '#171717'};
    font-size: 12px;
    font-family: 'Geist', sans-serif;
    white-space: nowrap;
    cursor: pointer;
    width: fit-content;
    -webkit-appearance: none;
    -moz-appearance: none;
    appearance: none;
`;


export const SearchBar = ({
    apiKey = "74039c6d-bff7-44ce-ae55-2973cbf13837",
    apiHost = "https://gptcloud.arc53.com",
    theme = "dark",
    placeholder = "Search or Ask AI...",
    width = "256px",
    buttonText = "Search here"
}: SearchBarProps) => {
    const [input, setInput] = React.useState<string>("");
    const [loading, setLoading] = React.useState<boolean>(false);
    const [isWidgetOpen, setIsWidgetOpen] = React.useState<boolean>(false);
    const inputRef = React.useRef<HTMLInputElement>(null);
    const containerRef = React.useRef<HTMLInputElement>(null);
    const [isResultVisible, setIsResultVisible] = React.useState<boolean>(false);
    const [results, setResults] = React.useState<Result[]>([]);
    const debounceTimeout = React.useRef<ReturnType<typeof setTimeout> | null>(null);
    const abortControllerRef = React.useRef<AbortController | null>(null);
    const browserOS = getOS();
    const isTouch = 'ontouchstart' in window;

    const getKeyboardInstruction = () => {
        if (isResultVisible) return "Enter";
        return browserOS === 'mac' ? '⌘ + K' : 'Ctrl + K';
    };

    React.useEffect(() => {
        loadGeistFont()
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsResultVisible(false);
            }
        };

        const handleKeyDown = (event: KeyboardEvent) => {
            if (
                ((browserOS === 'win' || browserOS === 'linux') && event.ctrlKey && event.key === 'k') ||
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
}, [input])

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
        <ThemeProvider theme={{ ...themes[theme] }}>
            <Main>
                <GlobalStyle />
                <Container ref={containerRef}>
                    <SearchButton
                        onClick={() => setIsResultVisible(true)}
                        inputWidth={width}
                    >
                        {buttonText}
                    </SearchButton>
                    {
                        isResultVisible && (
                            <>
                            <SearchOverlay onClick={() => setIsResultVisible(false)} />
                            <SearchResults>
                                <SearchHeader>
                                    <TextField
                                        ref={inputRef}
                                        value={input}
                                        onChange={(e) => setInput(e.target.value)}
                                        onKeyDown={(e) => handleKeyDown(e)}
                                        placeholder={placeholder}
                                        autoFocus
                                    />
                                    <EscapeInstruction onClick={() => setIsResultVisible(false)}>
                                        Esc
                                    </EscapeInstruction>
                                </SearchHeader>
                                <AskAIButton onClick={openWidget}>
                                    <img
                                        src="https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png"
                                        alt="DocsGPT"
                                        width={24}
                                        height={24}
                                    />
                                    <span>Ask the AI</span>
                                </AskAIButton>
                                <SearchResultsScroll>
                                    {!loading ? (
                                        results.length > 0 ? (
                                            results.map((res, key) => {
                                                const containsSource = res.source !== 'local';
                                                const processedResults = processMarkdownString(res.text, input);
                                                if (processedResults)
                                                    return (
                                                        <ResultWrapper
                                                            key={key}
                                                            onClick={() => {
                                                                if (!containsSource) return;
                                                                window.open(res.source, '_blank', 'noopener, noreferrer');
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
                                                                                    {element.tag === 'code' && <CodeIcon className="element-icon" />}
                                                                                    {(element.tag === 'bulletList' || element.tag === 'numberedList') && <ListBulletIcon className="element-icon" />}
                                                                                    {element.tag === 'text' && <TextAlignLeftIcon className="element-icon" />}
                                                                                    {element.tag === 'heading' && <HeadingIcon className="element-icon" />}
                                                                                    {element.tag === 'blockquote' && <QuoteIcon className="element-icon" />}
                                                                                </IconTitleWrapper>
                                                                                <div
                                                                                    style={{ flex: 1 }}
                                                                                    dangerouslySetInnerHTML={{
                                                                                        __html: DOMPurify.sanitize(element.content),
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
                        )
                    }
                    {
                        isTouch ?

                            <Toolkit
                                onClick={() => {
                                    setIsWidgetOpen(true)
                                }}
                                title={"Tap to Ask the AI"}>
                                Tap
                            </Toolkit>
                            :
                            <Toolkit
                                title={getKeyboardInstruction() === "Enter" ? "Press Enter to Ask AI" : ""}>
                                {getKeyboardInstruction()}
                            </Toolkit>
                    }
                </Container>
                <WidgetCore
                    theme={theme}
                    apiHost={apiHost}
                    apiKey={apiKey}
                    prefilledQuery={input}
                    isOpen={isWidgetOpen}
                    handleClose={handleClose} size={"large"}
                />
            </Main>
        </ThemeProvider>
    )
}

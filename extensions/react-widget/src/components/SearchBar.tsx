import React from 'react';
import styled, { ThemeProvider, createGlobalStyle } from 'styled-components';
import { WidgetCore } from './DocsGPTWidget';
import { SearchBarProps } from '@/types';
import { getSearchResults } from '../requests/searchAPI';
import { Result } from '@/types';
import MarkdownIt from 'markdown-it';
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
        bg: '#000',
        text: '#fff',
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
        bg: '#fff',
        text: '#000',
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
    color:#007EE6;
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
    color: ${props => props.theme.primary.text};
    outline: none;
    border: none;
    background-color: ${props => props.theme.secondary.bg};
    -webkit-appearance: none;
    -moz-appearance: none;
    appearance: none;
    transition: background-color 128ms linear;
    text-align: left;
    &:focus {
        outline: none;
        box-shadow: 
        0px 0px 0px 2px rgba(0, 109, 199), 
        0px 0px 6px rgb(0, 90, 163), 
        0px 2px 6px rgba(0, 0, 0, 0.1);
        background-color: ${props => props.theme.primary.bg};
    }
`

const Container = styled.div`
    position: relative;
    display: inline-block;
`
const SearchResults = styled.div`
    position: fixed;
    display: flex;
    flex-direction: column;
    background-color: ${props => props.theme.primary.bg};
    border: 1px solid ${props => props.theme.secondary.text};
    border-radius: 15px;
    padding: 8px 0px 8px 0px;
    width: 792px;
    max-width: 90vw;
    height: 415px;
    z-index: 100;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    color: ${props => props.theme.primary.text};
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1), 0 2px 4px rgba(0, 0, 0, 0.1);
    backdrop-filter: blur(16px);
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
    scrollbar-color: lab(48.438 0 0 / 0.4) rgba(0, 0, 0, 0);
    scrollbar-gutter: stable;
    scrollbar-width: thin;
    padding: 0 16px;
`;

const IconTitleWrapper = styled.div`
    display: flex;
    align-items: center;
    gap: 8px;
`;

const Title = styled.h3`
    font-size: 17.32px;
    font-weight: 400;
    color: ${props => props.theme.primary.text};
    margin: 0;
`;
const ContentWrapper = styled.div`
    display: flex;
    flex-direction: column;
    gap: 8px; 
`;
const Content = styled.div`
    display: flex;
    margin-left: 10px;
    flex-direction: column;
    gap: 8px;
    padding: 4px 0 0px 20px;
    font-size: 17.32px;
    color: ${props => props.theme.primary.text};
    line-height: 1.6;
    border-left: 2px solid #585858;
`
const ContentSegment = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding-right: 16px;
`
const TextContent = styled.div`
    display: flex;
    flex-direction: column;
    gap: 16px;
    flex: 1;
    padding-top: 3px;
`;

const ResultWrapper = styled.div`
    display: flex;
    align-items: flex-start;
    width: 100%;
    box-sizing: border-box;
    padding: 12px 16px 0 16px;
    cursor: pointer;
    margin-bottom: 8px;
    background-color: ${props => props.theme.primary.bg};
    font-family: 'Geist',sans-serif;
    transition: background-color 0.2s;

    &.contains-source:hover {
        background-color: rgba(0, 92, 197, 0.15);
        ${Title} {
            color: rgb(0, 126, 230);
        }
    }
`
const Markdown = styled.div`
line-height:20px;
font-size: 12px;
white-space: pre-wrap;
 pre {
      padding: 8px;
      width: 90%;
      font-size: 12px;
      border-radius: 6px;
      overflow-x: auto;
      background-color: #1B1C1F;
      color: #fff ;
    }

    h1,h2 {
      font-size: 16px;
      font-weight: 600;
      color: ${(props) => props.theme.text};
      opacity: 0.8;
    }


    h3 {
      font-size: 14px;
    }

    p {
      margin: 0px;
      line-height: 1.35rem;
      font-size: 12px;
    }

    code:not(pre code) {
      border-radius: 6px;
      padding: 2px 2px;
      margin: 2px;
      font-size: 10px;
      display: inline;
      background-color: #646464;
      color: #fff ;
    }
    img{
        max-width: 50%;
    }
    code {
      overflow-x: auto;
    }
    a{
        color: #007ee6;
    }
`
const Toolkit = styled.kbd`
    position: absolute;
    right: 4px;
    top: 4px;
    background-color: ${(props) => props.theme.primary.bg};
    color: ${(props) => props.theme.secondary.text};
    font-weight: 600;
    font-size: 10px;
    padding: 3px;
    border: 1px solid ${(props) => props.theme.secondary.text};
    border-radius: 4px;
`
const Loader = styled.div`
  margin: 2rem auto;
  border: 4px solid ${props => props.theme.secondary.text};
  border-top: 4px solid ${props => props.theme.primary.bg};
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
  font-size: 1rem;
  color: #888;
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
    border-radius: 6px;
    background-color: ${props => props.theme.secondary.bg};
    color: ${props => props.theme.bg === '#000' ? '#EDEDED' : props.theme.secondary.text};
    cursor: pointer;
    transition: background-color 0.2s, box-shadow 0.2s;
    font-size: 18px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);

    &:hover {
        opacity: 0.8;
    }
`
const SearchHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid ${props => props.theme.secondary.text};
`

const TextField = styled.input`
    width: calc(100% - 32px);
    margin: 0 16px;
    padding: 12px 16px;
    border: none;
    background-color: transparent;
    color: #EDEDED;
    font-size: 22px;
    font-weight: 400; 
    outline: none;

    &:focus {
        border-color: none;
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
    border: 1px solid ${props => props.theme.secondary.text};
    color: ${props => props.theme.secondary.text};
    font-size: 14px;
    font-family: 'Geist', sans-serif;
    white-space: nowrap;
    cursor: pointer;
    width: fit-content;
    &:hover {
        background-color: rgba(255, 255, 255, 0.1);
    }
`
export const SearchBar = ({
    apiKey = "74039c6d-bff7-44ce-ae55-2973cbf13837",
    apiHost = "https://gptcloud.arc53.com",
    theme = "dark",
    placeholder = "Search or Ask AI...",
    width = "256px"
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
                        Search here   
                    </SearchButton>
                    {
                        isResultVisible && (
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

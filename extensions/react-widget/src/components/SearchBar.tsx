import React from 'react'
import styled, { keyframes, createGlobalStyle, ThemeProvider } from 'styled-components';
import { WidgetCore } from './DocsGPTWidget';
import { SearchBarProps } from '@/types';
import { getSearchResults } from '../requests/searchAPI'
import { Result } from '@/types';
import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';

const themes = {
    dark: {
        bg: '#222327',
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

const Main = styled.div`
    all:initial;

    font-family: sans-serif;
`
const TextField = styled.input<{ inputWidth: string }>`
    padding:  6px 6px;
    width: ${({ inputWidth }) => inputWidth};
    border-radius: 8px;
    display: inline;
    color: ${props => props.theme.primary.text};
    outline: none;
    border: none;
    background-color: ${props => props.theme.secondary.bg};
    transition: background-color 128ms linear;
    &:focus {
     outline: none;
     box-shadow: 
    rgb(0, 109, 199) 0px 0px 3px, 
    rgb(0, 90, 163) 0px 0px 6px, 
    rgba(0, 0, 0, 0.25) 0px 2px 6px;
     background-color: ${props => props.theme.primary.bg};
  }
`

const Container = styled.div`
    position: relative;
    display: inline-block;
`
const SearchResults = styled.div`
    position: absolute;
    display: block;
    background-color: ${props => props.theme.primary.bg};
    opacity: 90%;
    border: 1px solid rgba(0, 0, 0, .1);
    border-radius: 12px;
    padding: 8px;
    width: 576px;
    min-width: 96%;
    z-index: 100;
    height: 25vh;
    overflow-y: auto;
    top: 45px;
    color: ${props => props.theme.primary.text};
    scrollbar-color: lab(48.438 0 0 / 0.4) rgba(0, 0, 0, 0);
    scrollbar-gutter: stable;
    scrollbar-width: thin;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), 0 2px 4px rgba(0, 0, 0, 0.1);
    backdrop-filter: blur(16px);
    @media only screen and (max-width: 768px) {
      max-height: 100vh;
      max-width: 80vw;
      overflow: auto;
    }
`
const Title = styled.h3`
    font-size: 14px;
    color: ${props => props.theme.primary.text};
    opacity: 0.8;
    padding-bottom: 6px;
    font-weight: 600;
    text-transform: uppercase;
    border-bottom: 1px solid ${(props) => props.theme.secondary.text};
`
const Content = styled.div`
    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
`
const ResultWrapper = styled.div`
    padding: 4px 8px 4px 8px;
    border-radius: 8px;
    cursor: pointer;
    &.contains-source:hover{
        background-color: rgba(0, 92, 197, 0.15);
        ${Title} {
        color: rgb(0, 126, 230);
       }
    }
`
const Markdown = styled.div`
line-height:20px;
font-size: 12px;
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
      padding: 4px 4px;
      font-size: 12px;
      display: inline-block;
      background-color: #646464;
      color: #fff ;
    }

    code {
      white-space: pre-wrap ;
      overflow-wrap: break-word;
      word-break: break-all;
    }
    a{
        color: #007ee6;
    }
`
const Toolkit = styled.kbd`
    position: absolute;
    right: 12px;
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
  border: 4px solid #f3f3f3;
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
export const SearchBar = ({
    apiKey = "74039c6d-bff7-44ce-ae55-2973cbf13837",
    apiHost = "https://gptcloud.arc53.com",
    theme = "dark",
    placeholder = "Search or Ask AI...",
    width = "240px"
}: SearchBarProps) => {
    const [input, setInput] = React.useState<string>("");
    const [loading, setLoading] = React.useState<boolean>(false)
    const [isWidgetOpen, setIsWidgetOpen] = React.useState<boolean>(false);
    const inputRef = React.useRef<HTMLInputElement>(null);
    const resultsRef = React.useRef<HTMLInputElement>(null);
    const [isResultVisible, setIsResultVisible] = React.useState<boolean>(true);
    const [results, setResults] = React.useState<Result[]>([]);
    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (
                resultsRef.current &&
                !resultsRef.current.contains(event.target as Node)
            ) {
                setIsResultVisible(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            resultsRef.current && (resultsRef.current.style.display = 'block')
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [])
    React.useEffect(() => {
        input.length > 0 ?
            (() => {
                setLoading(true)
                getSearchResults(input, apiKey, apiHost)
                .then((data) => {
                    setResults(data)
                    setLoading(false)
                })
                .catch((err) => console.log(err))
            })()
            :
            setResults([])
    }, [input])

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.ctrlKey && event.key === 'k') {
            event.preventDefault();
            setIsWidgetOpen(true);
        }
    };
    const handleClose = () => {
        setIsWidgetOpen(false);
    }
    const md = new MarkdownIt();
    return (
        <ThemeProvider theme={{ ...themes[theme] }}>
            <Main>
                <Container>
                    <TextField
                        spellCheck={false}
                        inputWidth={width}
                        onFocus={() => setIsResultVisible(true)}
                        ref={inputRef}
                        onKeyDown={(e) => handleKeyDown(e)}
                        placeholder={placeholder}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                    />
                    {
                        input.length > 0 && isResultVisible && (
                            <SearchResults ref={resultsRef}>
                                {!loading ?
                                    (results.length > 0 ?
                                        results.map((res) => {
                                            const containsSource = res.source !== 'local';
                                            return (
                                                <ResultWrapper
                                                    onClick={() => {
                                                        if (!containsSource) return;
                                                        window.open(res.source, '_blank', 'noopener, noreferrer')
                                                    }}
                                                    className={containsSource ? "contains-source" : ""}>
                                                    <Title>{res.title}</Title>
                                                    <Content>
                                                        <Markdown
                                                            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(md.render((res.text + "...").substring(0, 256) + "...")) }}
                                                        />
                                                    </Content>
                                                </ResultWrapper>
                                            )
                                        })
                                        :
                                        <NoResults>No results</NoResults>
                                    )
                                    :
                                    <Loader />
                                }
                            </SearchResults>
                        )
                    }
                    <Toolkit title='Press Ctrl + K to Ask AI'>Ctrl K</Toolkit>
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
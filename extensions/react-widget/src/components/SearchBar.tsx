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
const TextField = styled.input`
    padding:  6px 6px;
    border-radius: 8px;
    display: inline;
    color: ${props => props.theme.primary.text};
    outline: none;
    border: none;
    background-color: ${props => props.theme.secondary.bg};
    width: 240px;
    &:focus {
    outline: none;
    box-shadow: 0px 0px 0px 2px rgba(0, 109, 199);
    background-color: ${props => props.theme.primary.bg};
  }
`

const Container = styled.div`
    position: relative;
    display: inline-block;
`
const SearchResults = styled.div`
    position: absolute;
    background-color: ${props => props.theme.primary.bg};
    opacity: 90%;
    border: 1px solid rgba(0, 0, 0, .1);
    border-radius: 12px;
    padding: 15px;
    width: 576px;
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
`
const Title = styled.h3`
    font-size: 14px;
    color: rgb(107, 114, 128);
    padding-bottom: 6px;
    font-weight: 600;
    text-transform: uppercase;
    border-bottom: 1px solid ${(props) => props.theme.secondary.text};
`
const Content = styled.div`
    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
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
      color: rgb(31, 41, 55);
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
export const SearchBar = ({
    apiKey = "79bcbf0e-3dd1-4ac3-b893-e41b3d40ec8d",
    apiHost = "http://127.0.0.1:7091",
    theme = "light",
    placeholder = "Search or Ask AI"
}: SearchBarProps) => {
    const [input, setInput] = React.useState("")
    const [isWidgetOpen, setIsWidgetOpen] = React.useState<boolean>(false);
    const inputRef = React.useRef<HTMLInputElement>(null)
    const widgetRef = React.useRef<HTMLInputElement>(null)
    const [results, setResults] = React.useState<Result[]>([])
    React.useEffect(() => {
        input.length > 0 ?
            getSearchResults(input, apiKey, apiHost)
                .then((data) => setResults(data))
                .catch((err) => console.log(err))
            :
            setResults([])
    }, [input])

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Enter') {
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
                        ref={inputRef}
                        onKeyDown={(e) => handleKeyDown(e)}
                        placeholder={placeholder}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                    />
                    {
                        input.length > 0 && results.length > 0 && (
                            <SearchResults>
                                {results.map((res) => (
                                    <div>
                                        <Title>{res.title}</Title>
                                        <Content>
                                            <Markdown
                                                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(md.render(res.text)) }}
                                            />
                                        </Content>
                                    </div>
                                ))
                                }
                            </SearchResults>
                        )
                    }
                </Container>
                <WidgetCore
                    theme={theme}
                    apiHost={apiHost}
                    apiKey={apiKey}
                    prefilledQuery={input}
                    isOpen={isWidgetOpen}
                    handleClose={handleClose} size={'large'}
                />
            </Main>
        </ThemeProvider>
    )
}
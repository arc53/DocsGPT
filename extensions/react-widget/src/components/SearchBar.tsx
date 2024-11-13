import React from 'react'
import styled, { keyframes, createGlobalStyle } from 'styled-components';
import { WidgetCore } from './DocsGPTWidget';
import { SearchBarProps } from '@/types';
import { getSearchResults } from '../requests/searchAPI'
import { Result } from '@/types';
import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
const Main = styled.div`
    font-family: sans-serif;
`
const TextField = styled.input`
    padding: 8px;
    border-radius: 8px;
    display: inline;
    color: rgb(107 114 128);
    outline: none;
    border: 2px solid transparent;
    background-color: rgba(0, 0, 0, .05);;
    &:focus {
    outline: #467f95; /* remove default outline */
    border:2px solid skyblue; /* change border color on focus */
    box-shadow: 0px 0px 2px skyblue; /* add a red box shadow on focus */
  }
`

const Container = styled.div`
    position: relative;
    display: inline-block;
`
const SearchResults = styled.div`
    position: absolute;
    background-color: white;
    opacity: 90%;
    border: 1px solid rgba(0, 0, 0, .1);
    border-radius: 12px;
    padding: 20px;
    width: 576px;
    z-index: 100;
    height: 25vh;
    overflow-y: auto;
    top: 45px;
   scrollbar-color: lab(48.438 0 0 / 0.4) rgba(0, 0, 0, 0);
   scrollbar-gutter: stable;
   scrollbar-width: thin;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), 0 2px 4px rgba(0, 0, 0, 0.1);
    backdrop-filter: blur(16px);
`
const Title = styled.h3`
    font-size: 12px;
    color: rgb(107, 114, 128);
    padding-bottom: 4px;
    font-weight: 600;
    text-transform: uppercase;
    border-bottom: 1px solid rgba(0, 0, 0, 0.1);

`

const Content = styled.div`
    font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
`
const Markdown = styled.div`

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

    ul{
      padding:0px;
      list-style-position: inside;
    }
`
export const SearchBar = ({
    apiKey = "79bcbf0e-3dd1-4ac3-b893-e41b3d40ec8d",
    apiHost = "http://127.0.0.1:7091",
    theme = "dark"
}: SearchBarProps) => {
    const [input, setInput] = React.useState("")
    const [isWidgetOpen, setIsWidgetOpen] = React.useState<boolean>(false);
    const inputRef = React.useRef<HTMLInputElement>(null)
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
        <Main>
            <Container>
                <TextField
                    ref={inputRef}
                    onKeyDown={(e) => handleKeyDown(e)}
                    placeholder='Search here or Ask DocsGPT'
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                />
                {
                    results.length > 0 && (
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
    )
}
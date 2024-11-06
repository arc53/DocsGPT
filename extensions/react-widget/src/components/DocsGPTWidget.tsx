"use client";
import React, { useRef } from 'react'
import DOMPurify from 'dompurify';
import styled, { keyframes, createGlobalStyle } from 'styled-components';
import { PaperPlaneIcon, RocketIcon, ExclamationTriangleIcon, Cross2Icon } from '@radix-ui/react-icons';
import { FEEDBACK, MESSAGE_TYPE, Query, Status, WidgetProps } from '../types/index';
import { fetchAnswerStreaming, sendFeedback } from '../requests/streamingApi';
import { ThemeProvider } from 'styled-components';
import Like from "../assets/like.svg"
import Dislike from "../assets/dislike.svg"
import MarkdownIt from 'markdown-it';

const themes = {
  dark: {
    bg: '#222327',
    text: '#fff',
    primary: {
      text: "#FAFAFA",
      bg: '#222327'
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

const sizesConfig = {
  small: { size: 'small', width: '320px', height: '400px' },
  medium: { size: 'medium', width: '400px', height: '80vh' },
  large: { size: 'large', width: '666px', height: '75vh' },
  getCustom: (custom: { width: string; height: string; maxWidth?: string; maxHeight?: string }) => ({
    size: 'custom',
    width: custom.width,
    height: custom.height,
    maxWidth: custom.maxWidth || '968px',
    maxHeight: custom.maxHeight || '70vh',
  }),
};

const Overlay = styled.div`
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(0, 0, 0, 0.5);
  z-index: 999;
  transition: opacity 0.5s;
`
const WidgetContainer = styled.div<{ modal?: boolean }>`
    all: initial;
    position: fixed;
    right: ${props => props.modal ? '50%' : '10px'};
    bottom: ${props => props.modal ? '50%' : '10px'};
    z-index: 1000;
    display: block;
    ${props => props.modal &&
    "transform : translate(50%,50%);"
  }
    align-items: center;
    text-align: left;
`;
const StyledContainer = styled.div`
    all: initial;
    max-height: ${(props) => props.theme.dimensions.maxHeight};
    max-width: ${(props) => props.theme.dimensions.maxWidth};
    height: ${(props) => props.theme.dimensions.height} ;
    width: ${(props) => props.theme.dimensions.width} ;
    display: flex;
    position: relative;
    flex-direction: column;
    justify-content: space-between;
    bottom: 0;
    left: 0;
    border-radius: 12px;
    background-color: ${props => props.theme.primary.bg};
    font-family: sans-serif;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), 0 2px 4px rgba(0, 0, 0, 0.1);
    transition: visibility 0.3s, opacity 0.3s;
    padding: 26px 26px 0px 26px ;
    @media only screen and (max-width: 768px) {
    max-height: 100vh ;
    max-width: 80vw;
    overflow: auto;
    }
`;
const FloatingButton = styled.div<{ bgcolor: string }>`
    position: fixed;
    display: flex;
    z-index: 500;
    justify-content: center;
    align-items: center;
    bottom: 16px;
    right: 16px;
    width: 80px;
    height: 80px;
    border-radius: 9999px;
    background: ${props => props.bgcolor};
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    cursor: pointer;
    &:hover {
        transform: scale(1.1);
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
    gap:2px; 
    margin-left: 8px;
`;

const Title = styled.h3`
    font-size: 14px;
    font-weight: normal;
    color: ${props => props.theme.primary.text};
    margin: 0;
`;

const Description = styled.p`
    font-size: 13.75px;
    color: ${props => props.theme.secondary.text};
    margin: 0 ;
    padding: 0 ;
`;

const Conversation = styled.div`
  height: 70%;
  border-radius: 6px;
  text-align: left;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #4a4a4a transparent; /* thumb color track color */
`;
const Feedback = styled.div`
  background-color: transparent;
  font-weight: normal;
  gap: 12px;
  display: flex;
  padding: 6px;
  clear: both;
`;
const MessageBubble = styled.div<{ type: MESSAGE_TYPE }>`
    display: block;
    font-size: 16px;
    position: relative;
    width: 100%;;
    float: right;
    margin: 0px;
    &:hover ${Feedback} * {
    visibility: visible ;
  }
`;
const Message = styled.div<{ type: MESSAGE_TYPE }>`
    background: ${props => props.type === 'QUESTION' ?
    'linear-gradient(to bottom right, #8860DB, #6D42C5)' :
    props.theme.secondary.bg};
    color: ${props => props.type === 'ANSWER' ? props.theme.primary.text : '#fff'};
    border: none;
    float: ${props => props.type === 'QUESTION' ? 'right' : 'left'};
    max-width: ${props => props.type === 'ANSWER' ? '100%' : '80'};
    overflow: auto;
    margin: 4px;
    display: block;
    line-height: 1.5;
    padding: 12px;
    border-radius: 6px;
`;
const Markdown = styled.div`
 pre {
      padding: 8px;
      width: 90%;
      font-size: 12px;
      border-radius: 6px;
      overflow-x: auto;
      background-color: #1B1C1F;
      color: #fff ;
    }

    h1 {
      font-size: 16px;
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
const ErrorAlert = styled.div`
  color: #b91c1c;
  border:0.1px solid #b91c1c;
  display: flex;
  padding:4px;
  margin:11.2px;
  opacity: 90%;
  max-width: 70%;
  font-weight: 400;
  border-radius: 6px;
  justify-content: space-evenly;
`
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
const Delay = styled(DotAnimation) <{ delay: number }>`
  animation-delay: ${props => props.delay + 'ms'};
`;
const PromptContainer = styled.form`
  background-color: transparent;
  height: ${props => props.theme.dimensions.size == 'large' ? '60px' : '40px'};
  display: flex;
  justify-content: space-evenly;
`;
const StyledInput = styled.input`
  width: 100%;
  border: 1px solid #686877;
  padding-left: 12px;
  background-color: transparent;
  font-size: 16px;
  border-radius: 6px;
  color: ${props => props.theme.text};
  outline: none;
`;
const StyledButton = styled.button`
  display: flex;
  justify-content: center;
  align-items: center;
  background-image: linear-gradient(to bottom right, #5AF0EC, #E80D9D);
  background-color: rgba(0, 0, 0, 0.3);
  border-radius: 6px;
  min-width: ${props => props.theme.dimensions.size === 'large' ? '60px' : '40px'};
  height: ${props => props.theme.dimensions.size === 'large' ? '60px' : '40px'};
  margin-left:8px;
  padding: 0px;
  
  border: none;
  cursor: pointer;
  outline: none;
  &:hover{
    opacity: 90%;
  }
  &:disabled {
    background-image: linear-gradient(to bottom right, #2d938f, #b31877);
  }`;
const HeroContainer = styled.div`
  position: relative;
  width: 90%;
  max-width: 500px;
  background-image: linear-gradient(to bottom right, #5AF0EC, #ff1bf4);
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
  background-color: ${props => props.theme.primary.bg};
  border-radius: 10px; 
  font-weight: normal;
  padding: 12px;
`
const HeroTitle = styled.h3`
  color: ${props => props.theme.text};
  font-size: 16px;
  margin:0px ;
  padding: 0px;
`;
const HeroDescription = styled.p`
  color: ${props => props.theme.text};
  font-size: 12px;
  line-height: 1.5;
  margin: 0px;
  padding: 0px;
`;
const Hyperlink = styled.a`
  color: #9971EC;
  text-decoration: none;
`;
const Tagline = styled.div`
  text-align: center;
  display: block;
  color: ${props => props.theme.secondary.text};
  padding: 12px ;
  font-size: 12px;
`;



const Hero = ({ title, description, theme }: { title: string, description: string, theme: string }) => {
  return (
    <HeroContainer>
      <HeroWrapper>
        <RocketIcon color={theme === 'light' ? 'black' : 'white'} width={24} height={24} />
        <HeroTitle>{title}</HeroTitle>
        <HeroDescription>{description}</HeroDescription>
      </HeroWrapper>
    </HeroContainer>
  );
};
export const DocsGPTWidget = ({
  apiHost = 'https://gptcloud.arc53.com',
  apiKey = '82962c9a-aa77-4152-94e5-a4f84fd44c6a',
  avatar = 'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png',
  title = 'Get AI assistance',
  description = 'DocsGPT\'s AI Chatbot is here to help',
  heroTitle = 'Welcome to DocsGPT !',
  heroDescription = 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.',
  size = 'small',
  theme = 'dark',
  buttonIcon = 'https://d3dg1063dc54p9.cloudfront.net/widget/message.svg',
  buttonBg = 'linear-gradient(to bottom right, #5AF0EC, #E80D9D)',
  collectFeedback = true,
  deafultOpen = false
}: WidgetProps) => {
  const [prompt, setPrompt] = React.useState('');
  const [status, setStatus] = React.useState<Status>('idle');
  const [queries, setQueries] = React.useState<Query[]>([])
  const [conversationId, setConversationId] = React.useState<string | null>(null)
  const [open, setOpen] = React.useState<boolean>(deafultOpen)
  const [eventInterrupt, setEventInterrupt] = React.useState<boolean>(false); //click or scroll by user while autoScrolling
  const isBubbleHovered = useRef<boolean>(false)
  const endMessageRef = React.useRef<HTMLDivElement | null>(null);
  const md = new MarkdownIt();

  const handleUserInterrupt = () => {
    (status === 'loading') && setEventInterrupt(true);
  }
  const scrollToBottom = (element: Element | null) => {
    //recursive function to scroll to the last child of the last child ...
    // to get to the bottom most element
    if (!element) return;
    if (element?.children.length === 0) {
      element?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    }
    const lastChild = element?.children?.[element.children.length - 1]
    lastChild && scrollToBottom(lastChild)
  };
  React.useEffect(() => {
    !eventInterrupt && scrollToBottom(endMessageRef.current);
  }, [queries.length, queries[queries.length - 1]?.response]);

  async function handleFeedback(feedback: FEEDBACK, index: number) {
    let query = queries[index]
    if (!query.response)
      return;
    if (query.feedback != feedback) {
      sendFeedback({
        question: query.prompt,
        answer: query.response,
        feedback: feedback,
        apikey: apiKey
      }, apiHost)
        .then(res => {
          if (res.status == 200) {
            query.feedback = feedback;
            setQueries((prev: Query[]) => {
              return prev.map((q, i) => (i === index ? query : q));
            });
          }
        })
        .catch(err => console.log("Connection failed", err))
    }
    else {
      delete query.feedback;
      setQueries((prev: Query[]) => {
        return prev.map((q, i) => (i === index ? query : q));
      });

    }
  }

  async function stream(question: string) {
    setStatus('loading')
    try {
      await fetchAnswerStreaming(
        {
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
            }
            else if (data.type === 'id') {
              setConversationId(data.id)
            }
            else if (data.type === 'error') {
              const updatedQueries = [...queries];
              updatedQueries[updatedQueries.length - 1].error = data.error;
              setQueries(updatedQueries);
              setStatus('idle')
            }
            else if (data.type === 'source') {
              // handle the case where data type === 'source'
            }
            else {
              const result = data.answer ? data.answer : ''; //Fallback to an empty string if data.answer is undefined
              const streamingResponse = queries[queries.length - 1].response ? queries[queries.length - 1].response : '';
              const updatedQueries = [...queries];
              updatedQueries[updatedQueries.length - 1].response = streamingResponse + result;
              setQueries(updatedQueries);
            }
          }
        }
      );
    } catch (error) {
      const updatedQueries = [...queries];
      updatedQueries[updatedQueries.length - 1].error = 'Something went wrong !'
      setQueries(updatedQueries);
      setStatus('idle')
      //setEventInterrupt(false)
    }

  }
  // submit handler
  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setEventInterrupt(false);
    queries.push({ prompt })
    setPrompt('')
    await stream(prompt)
  }
  const handleImageError = (event: React.SyntheticEvent<HTMLImageElement, Event>) => {
    event.currentTarget.src = "https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png";
  };

  const dimensions =
    typeof size === 'object' && 'custom' in size
      ? sizesConfig.getCustom(size.custom)
      : sizesConfig[size];
  return (
    <ThemeProvider theme={{ ...themes[theme], dimensions }}>
      {open && size === 'large' &&
        <Overlay onClick={() => {
          setOpen(false)
        }} />
      }
      <FloatingButton bgcolor={buttonBg} onClick={() => setOpen(!open)} hidden={open}>
        <img style={{ maxHeight: '64px', maxWidth: '64px' }} src={buttonIcon} />
      </FloatingButton>
      <WidgetContainer modal={size == 'large'}>
        {open && <StyledContainer>
          <div>
            <CancelButton onClick={() => setOpen(false)}>
              <Cross2Icon width={24} height={24} color={theme === 'light' ? 'black' : 'white'} />
            </CancelButton>
            <Header>
              <img style={{ transform: 'translateY(-5px)', maxWidth: "42px", maxHeight: "42px" }} onError={handleImageError} src={avatar} alt='docs-gpt' />
              <ContentWrapper>
                <Title>{title}</Title>
                <Description>{description}</Description>
              </ContentWrapper>
            </Header>
          </div>
          <Conversation onWheel={handleUserInterrupt} onTouchMove={handleUserInterrupt}>
            {
              queries.length > 0 ? queries?.map((query, index) => {
                return (
                  <React.Fragment key={index}>
                    {
                      query.prompt && <MessageBubble type='QUESTION'>
                        <Message
                          type='QUESTION'
                          ref={(!(query.response || query.error) && index === queries.length - 1) ? endMessageRef : null}>
                          {query.prompt}
                        </Message>
                      </MessageBubble>
                    }
                    {
                      query.response ? <MessageBubble onMouseOver={() => { isBubbleHovered.current = true }} type='ANSWER'>
                        <Message
                          type='ANSWER'
                          ref={(index === queries.length - 1) ? endMessageRef : null}
                        >
                          <Markdown
                            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(md.render(query.response)) }}
                          />
                        </Message>

                        {collectFeedback &&
                          <Feedback>
                            <Like
                              style={{
                                stroke: query.feedback == 'LIKE' ? '#8860DB' : '#c0c0c0',
                                visibility: query.feedback == 'LIKE' ? 'visible' : 'hidden'
                              }}
                              fill='none'
                              onClick={() => handleFeedback("LIKE", index)} />
                            <Dislike
                              style={{
                                stroke: query.feedback == 'DISLIKE' ? '#ed8085' : '#c0c0c0',
                                visibility: query.feedback == 'DISLIKE' ? 'visible' : 'hidden'
                              }}
                              fill='none'
                              onClick={() => handleFeedback("DISLIKE", index)} />
                          </Feedback>}
                      </MessageBubble>
                        : <div>
                          {
                            query.error ? <ErrorAlert>

                              <ExclamationTriangleIcon width={22} height={22} color='#b91c1c' />
                              <div>
                                <h5 style={{ margin: 2 }}>Network Error</h5>
                                <span style={{ margin: 2, fontSize: '13px' }}>{query.error}</span>
                              </div>
                            </ErrorAlert>
                              : <MessageBubble type='ANSWER'>
                                <Message type='ANSWER' style={{ fontWeight: 600 }}>
                                  <DotAnimation>.</DotAnimation>
                                  <Delay delay={200}>.</Delay>
                                  <Delay delay={400}>.</Delay>
                                </Message>
                              </MessageBubble>
                          }
                        </div>
                    }
                  </React.Fragment>)
              })
                : <Hero title={heroTitle} description={heroDescription} theme={theme} />
            }
          </Conversation>
          <div>
            <PromptContainer
              onSubmit={handleSubmit}>
              <StyledInput
                value={prompt} onChange={(event) => setPrompt(event.target.value)}
                type='text' placeholder="Ask your question" />
              <StyledButton
                disabled={prompt.trim().length == 0 || status !== 'idle'}>
                <PaperPlaneIcon width={18} height={18} color='white' />
              </StyledButton>
            </PromptContainer>
            <Tagline>
              Powered by&nbsp;
              <Hyperlink target='_blank' href='https://github.com/arc53/DocsGPT'>DocsGPT</Hyperlink>
            </Tagline>
          </div>
        </StyledContainer>}
      </WidgetContainer>
    </ThemeProvider>
  )
}
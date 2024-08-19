"use client";
import React from 'react'
import DOMPurify from 'dompurify';
import snarkdown from '@bpmn-io/snarkdown';
import styled, { keyframes, createGlobalStyle } from 'styled-components';
import { PaperPlaneIcon, RocketIcon, ExclamationTriangleIcon, Cross2Icon } from '@radix-ui/react-icons';
import MessageIcon from '../assets/message.svg';
import { MESSAGE_TYPE, Query, Status, WidgetProps } from '../types/index';
import { fetchAnswerStreaming } from '../requests/streamingApi';

const GlobalStyles = createGlobalStyle`
.response pre {
    padding: 8px;
    width: 90%;
    font-size: 12px;
    border-radius: 6px;
    overflow-x: auto;
    background-color: #1B1C1F;
}
.response h1{
  font-size: 20px;
}
.response h2{
  font-size: 18px;
}
.response h3{
  font-size: 16px;
}
.response code:not(pre code){
  border-radius: 6px;
  padding: 1px 3px 1px 3px;
  font-size: 12px;
  display: inline-block;
  background-color: #646464;
}
`;
const WidgetContainer = styled.div`
    display: block;
    position: fixed;
    right: 10px;
    bottom: 10px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: left;
`;
const StyledContainer = styled.div`
    display: flex;
    position: relative;
    flex-direction: column;
    justify-content: center;
    bottom: 0;
    left: 0;
    border-radius: 0.75rem;
    background-color: #222327;
    font-family: sans-serif;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), 0 2px 4px rgba(0, 0, 0, 0.1);
    transition: visibility 0.3s, opacity 0.3s;
`;
const FloatingButton = styled.div`
    position: fixed;
    display: flex;
    z-index: 500;
    justify-content: center;
    align-items: center;
    bottom: 1rem;
    right: 1rem;
    width: 5rem;
    height: 5rem;
    border-radius: 9999px;
    background-image: linear-gradient(to bottom right, #5AF0EC, #E80D9D);
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
    margin: 0.5rem;
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
    align-items: center;
    padding-inline: 0.75rem;
    padding-top: 1rem;
    padding-bottom: 0.5rem;
`;

const IconWrapper = styled.div`
    padding: 0.5rem;
`;

const ContentWrapper = styled.div`
    flex: 1;
    margin-left: 0.5rem;
`;

const Title = styled.h3`
    font-size: 1rem;
    font-weight: normal;
    color: #FAFAFA;
    margin-top: 0;
    margin-bottom: 0.25rem;
`;

const Description = styled.p`
    font-size: 0.85rem;
    color: #A1A1AA;
    margin-top: 0;
`;
const Conversation = styled.div<{ size: string }>`
    min-height: 300px;
    height: ${props => props.size === 'medium' ? '70vh' : '320px'};
    width: ${props => props.size === 'medium' ? '28vw' : '400px'};
    padding-inline: 0.5rem;
    border-radius: 0.375rem;
    text-align: left;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: #4a4a4a transparent; /* thumb color track color */
    @media only screen and (max-width: 768px) {
    width: 90vw !important;
    }
    @media only screen and (min-width:768px ) and (max-width: 1023px) {
    width:${props => props.size === 'medium' ? '400px' : '60vw'} !important;
    }
    
`;

const MessageBubble = styled.div<{ type: MESSAGE_TYPE }>`
    display: flex;
    font-size: 16px;
    justify-content: ${props => props.type === 'QUESTION' ? 'flex-end' : 'flex-start'};
    margin: 0.5rem;
`;
const Message = styled.p<{ type: MESSAGE_TYPE }>`
    background: ${props => props.type === 'QUESTION' ?
    'linear-gradient(to bottom right, #8860DB, #6D42C5)' :
    '#38383b'};
    color: #ffff;
    border: none;
    max-width: 80%;
    overflow: auto;
    margin: 4px;
    display: block;
    line-height: 1.5;
    padding: 0.75rem;
    border-radius: 0.375rem;
`;
const ErrorAlert = styled.div`
  color: #b91c1c;
  border:0.1px solid #b91c1c;
  display: flex;
  padding:4px;
  margin:0.7rem;
  opacity: 90%;
  max-width: 70%;
  font-weight: 400;
  border-radius: 0.375rem;
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
  height: 40px;
  margin: 16px;
  display: flex;
  justify-content: space-evenly;
`;
const StyledInput = styled.input`
  width: 100%;
  height: 36px;
  border: 1px solid #686877;
  padding-left: 12px;
  background-color: transparent;
  font-size: 16px;
  border-radius: 6px;
  color: #ffff;
  outline: none;
`;
const StyledButton = styled.button`
  display: flex;
  justify-content: center;
  align-items: center;
  background-image: linear-gradient(to bottom right, #5AF0EC, #E80D9D);
  border-radius: 6px;
  width: 36px;
  height: 36px;
  margin-left:8px;
  padding: 0px;
  border: none;
  cursor: pointer;
  outline: none;
  &:hover{
    opacity: 90%;
  }
  &:disabled {
    opacity: 60%;
  }`;
const HeroContainer = styled.div`
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  justify-content: center;
  align-items: middle;
  transform: translate(-50%, -50%);
  width: 80%;
  background-image: linear-gradient(to bottom right, #5AF0EC, #ff1bf4);
  border-radius: 10px;
  margin: 0 auto;
  padding: 2px;
`;
const HeroWrapper = styled.div`
  background-color: #222327;
  border-radius: 10px; 
  font-weight: normal;
  padding: 6px;
  display: flex;
  justify-content: space-between;
`
const HeroTitle = styled.h3`
  color: #fff;
  font-size: 17px;
  margin-bottom: 5px;
  padding: 2px;
`;
const HeroDescription = styled.p`
  color: #fff;
  font-size: 14px;
  line-height: 1.5;
`;
const Hero = ({ title, description }: { title: string, description: string }) => {
  return (
    <>
      <HeroContainer>
        <HeroWrapper>
          <IconWrapper style={{ marginTop: '8px' }}>
            <RocketIcon color='white' width={20} height={20} />
          </IconWrapper>
          <div>
            <HeroTitle>{title}</HeroTitle>
            <HeroDescription>
              {description}
            </HeroDescription>
          </div>
        </HeroWrapper>
      </HeroContainer>
    </>
  );
};
export const DocsGPTWidget = ({
  apiHost = 'https://gptcloud.arc53.com',
  selectDocs = 'default',
  apiKey = '82962c9a-aa77-4152-94e5-a4f84fd44c6a',
  avatar = 'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png',
  title = 'Get AI assistance',
  description = 'DocsGPT\'s AI Chatbot is here to help',
  heroTitle = 'Welcome to DocsGPT !',
  heroDescription = 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.',
  size = 'small'
}: WidgetProps) => {
  const [prompt, setPrompt] = React.useState('');
  const [status, setStatus] = React.useState<Status>('idle');
  const [queries, setQueries] = React.useState<Query[]>([])
  const [conversationId, setConversationId] = React.useState<string | null>(null)
  const [open, setOpen] = React.useState<boolean>(false)
  const [eventInterrupt, setEventInterrupt] = React.useState<boolean>(false); //click or scroll by user while autoScrolling
  const endMessageRef = React.useRef<HTMLDivElement | null>(null);
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

  async function stream(question: string) {
    setStatus('loading')
    try {
      await fetchAnswerStreaming(
        {
          question: question,
          apiKey: apiKey,
          apiHost: apiHost,
          selectedDocs: selectDocs,
          history: queries,
          conversationId: conversationId,
          onEvent: (event: MessageEvent) => {
            const data = JSON.parse(event.data);
            // check if the 'end' event has been received
            if (data.type === 'end') {
              // set status to 'idle'
              setStatus('idle');

            } else if (data.type === 'id') {
              setConversationId(data.id)
            } else {
              const result = data.answer;
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
      updatedQueries[updatedQueries.length - 1].error = 'error'
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
  return (
    <>
      <WidgetContainer>
        <GlobalStyles />
        {!open && <FloatingButton onClick={() => setOpen(true)} hidden={open}>
          <MessageIcon style={{ marginTop: '8px' }} />
        </FloatingButton>}
        {open && <StyledContainer>
          <div>
            <CancelButton onClick={() => setOpen(false)}>
              <Cross2Icon width={24} height={24} color='white' />
            </CancelButton>
            <Header>
              <IconWrapper>
                <img style={{ maxWidth: "42px", maxHeight: "42px" }} onError={handleImageError} src={avatar} alt='docs-gpt' />
              </IconWrapper>
              <ContentWrapper>
                <Title>{title}</Title>
                <Description>{description}</Description>
              </ContentWrapper>
            </Header>
          </div>
          <Conversation size={size} onWheel={handleUserInterrupt} onTouchMove={handleUserInterrupt}>
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
                      query.response ? <MessageBubble type='ANSWER'>
                        <Message
                          type='ANSWER'
                          ref={(index === queries.length - 1) ? endMessageRef : null}
                        >
                          <div className="response" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(snarkdown(query.response)) }} />
                        </Message>
                      </MessageBubble>
                        : <div>
                          {
                            query.error ? <ErrorAlert>
                              <IconWrapper>
                                <ExclamationTriangleIcon style={{ marginTop: '4px' }} width={22} height={22} color='#b91c1c' />
                              </IconWrapper>
                              <div>
                                <h5 style={{ margin: 2 }}>Network Error</h5>
                                <span style={{ margin: 2, fontSize: '13px' }}>Something went wrong !</span>
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
                : <Hero title={heroTitle} description={heroDescription} />
            }
          </Conversation>

          <PromptContainer
            onSubmit={handleSubmit}>
            <StyledInput
              value={prompt} onChange={(event) => setPrompt(event.target.value)}
              type='text' placeholder="What do you want to do?" />
            <StyledButton
              disabled={prompt.length == 0 || status !== 'idle'}>
              <PaperPlaneIcon width={15} height={15} color='white' />
            </StyledButton>
          </PromptContainer>
        </StyledContainer>}
      </WidgetContainer>
    </>
  )
}
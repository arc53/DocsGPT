"use client";
import { Fragment, useEffect, useRef, useState } from 'react'
import { PaperPlaneIcon, RocketIcon, ExclamationTriangleIcon } from '@radix-ui/react-icons';
import { Input } from './ui/input';
import { Button } from './ui/button';
import { ScrollArea } from './ui/scroll-area'
import { Alert, AlertTitle, AlertDescription } from './ui/alert';
import Dragon from '../assets/cute-docsgpt.svg'
import MessageIcon from '../assets/message.svg'
import Cancel from '../assets/cancel.svg'
import { Query } from '@/models/customTypes';
import { fetchAnswerStreaming } from '@/requests/streamingApi';
import Response from './Response';

type Status = 'idle' | 'loading' | 'failed';

enum ChatStates {
  Init = 'init',
  Processing = 'processing',
  Typing = 'typing',
  Answer = 'answer',
  Minimized = 'minimized',
}

export const DocsGPTWidget = ({ apiHost = 'https://gptcloud.arc53.com', selectDocs = 'default', apiKey = 'docsgpt-public' }) => {
  // processing states
  const [chatState, setChatState] = useState<ChatStates>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('docsGPTChatState') as ChatStates || ChatStates.Init;
    }
    return ChatStates.Init;
  });
  const [prompt, setPrompt] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [queries, setQueries] = useState<Query[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const scrollToBottom = (element: Element | null) => {
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
  useEffect(() => {
    scrollToBottom(scrollRef.current);
  }, [queries.length, queries[queries.length - 1]?.response]);

  useEffect(() => {
    localStorage.setItem('docsGPTChatState', chatState);
  }, [chatState]);
  async function stream(question: string) {
    setStatus('loading');
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
              let streamingResponse = queries[queries.length - 1].response ? queries[queries.length - 1].response : '';
              let updatedQueries = [...queries];
              updatedQueries[updatedQueries.length - 1].response = streamingResponse + result;
              setQueries(updatedQueries);
            }
          }
        }
      );
    } catch (error) {
      console.log(error);

      let updatedQueries = [...queries];
      updatedQueries[updatedQueries.length - 1].error = 'error'
      setQueries(updatedQueries);
      setStatus('idle')
    }

  }
  // submit handler
  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    queries.push({ prompt })
    setPrompt('')
    setChatState(ChatStates.Processing)
    await stream(prompt)
    setChatState(ChatStates.Answer)

  }

  return (
    <>
      <div className="dark widget-container font-sans">
        <div onClick={() => setChatState(ChatStates.Init)}
          className={`${chatState !== 'minimized' ? 'hidden' : ''} cursor-pointer`}>
          <div className="mr-2 mb-2 bottom-2 right-2 absolute w-20 h-20 rounded-full overflow-hidden dark:divide-gray-700 border dark:border-gray-100 bg-gradient-to-br dark:from-[#5AF0EC] dark:to-[#E80D9D] from-gray-900/80  via-gray-900 to-gray-900 font-sans shadow backdrop-blur-sm flex items-center justify-center">
            <img
              src={MessageIcon}
              alt="DocsGPT"
              className="cursor-pointer hover:opacity-50 w-12"
            />
          </div>
        </div>
        <div className={` ${chatState !== 'minimized' ? '' : 'hidden'} absolute bottom-0 divide-y dark:divide-gray-700 rounded-md border dark:bg-[#222327] dark:border-gray-700  font-sans shadow backdrop-blur-sm w-full`} style={{ transform: 'translateY(0%) translateZ(0px)' }}>
          <div>
            <img
              src={Cancel}
              alt="Exit"
              className="cursor-pointer hover:opacity-50 absolute top-0 right-0 m-2 white-filter"
              onClick={(event) => {
                event.stopPropagation();
                setChatState(ChatStates.Minimized);
              }}
            />
            <div className="flex items-center gap-2 p-3">
              <div className={` flex justify-between`}>
                <img src={Dragon} />
                <div className='mx-2 w-full'>
                  <h3 className="text-sm font-normal text-gray-700 dark:text-[#FAFAFA] ">Get AI assistance</h3>
                  <p className="mt-1 text-xs text-gray-400 dark:text-[#A1A1AA]">DocsGPT's AI Chatbot is here to help</p>
                </div>
              </div>
            </div>
          </div>
          <div className="w-full">
            <button onClick={() => setChatState(ChatStates.Typing)}
              className={`flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 hover:bg-gray-100 rounded-b dark:hover:bg-gray-800/70 ${chatState !== 'init' ? 'hidden' : ''}`}>
              Ask DocsGPT
            </button>
            {(chatState === 'typing' || chatState === 'answer' || chatState === 'processing') && (
              <div className='h-full'>
                <ScrollArea className='h-72 p-2 rounded-md border'>
                  {
                    queries.length > 0 ? queries?.map((query, index) => {
                      return (
                        <Fragment key={index}>
                          {
                            query.prompt && <div className='flex justify-end m-2 '>
                              <p ref={(!(query.response || query.error) && index === queries.length - 1) ? scrollRef : null} className='bg-gradient-to-br dark:from-[#8860DB] dark:to-[#6D42C5] max-w-[80%] dark:text-white block px-3 py-2 rounded-lg '>
                                {query.prompt}
                              </p>
                            </div>
                          }
                          {
                            query.response ? <div className='flex justify-start m-2 '>
                              <div ref={(index === queries.length - 1) ? scrollRef : null} className='dark:bg-[#38383B] max-w-[80%] dark:text-white block px-3 py-2 rounded-lg'>
                                <Response message={query.response} />
                              </div>
                            </div>
                              : <div className='m-2'>
                                {
                                  query.error ? <Alert className='border-red-700 text-red-700 max-w-[80%]' variant="destructive">
                                    <ExclamationTriangleIcon color='red' className="h-4 w-4" />
                                    <AlertTitle>Network Error</AlertTitle>
                                    <AlertDescription>
                                      Something went wrong !
                                    </AlertDescription>
                                  </Alert>
                                    : <div className='flex justify-start m-2 '>
                                      <p className='dark:bg-[#38383B] text-xl max-w-[80%] font-extrabold dark:text-white block px-3 py-2 rounded-lg  justify-center text-gray-800  transition duration-300 rounded-b '>
                                        <span className="dot-animation">.</span>
                                        <span className="dot-animation delay-200">.</span>
                                        <span className="dot-animation delay-400">.</span>
                                      </p>
                                    </div>
                                }
                              </div>
                          }
                        </Fragment>)
                    })
                      : <div className='absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-5/6 bg-gradient-to-br dark:from-[#5AF0EC] dark:to-[#ff1bf4] rounded-lg mx-2 p-[1px]'>
                        <Alert className='dark:bg-[#222327] mx-0'>
                          <RocketIcon className="h-4 w-4" />
                          <AlertTitle>Welcome to DocsGPT !</AlertTitle>
                          <AlertDescription>
                            This is a chatbot that uses the GPT-3, Faiss and LangChain to answer questions.
                          </AlertDescription>
                        </Alert>
                      </div>
                  }
                </ScrollArea>
                <form
                  onSubmit={handleSubmit}
                  className="relative w-full m-0" style={{ opacity: 1 }}>
                  <div className='p-2 flex justify-between'>
                    <Input
                      value={prompt} onChange={(event) => setPrompt(event.target.value)}
                      type='text'
                      className="w-[85%] border border-[#686877] h-8 bg-transparent px-5 py-4  text-sm text-gray-700 dark:text-white focus:outline-none" placeholder="What do you want to do?" />
                    <Button className="text-gray-400 dark:text-gray-500 bg-gradient-to-br dark:from-[#5AF0EC] dark:to-[#E80D9D] disabled:bg-black  text-sm inset-y-0  px-2" type="submit" disabled={prompt.length == 0 || status !== 'idle'}>
                      <PaperPlaneIcon className='text-white' />
                    </Button>
                  </div>
                </form>
              </div>
            )}

          </div>
        </div>
      </div>

    </>
  )
}

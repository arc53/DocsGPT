"use client";
import {useEffect, useRef, useState} from 'react'
//import './style.css'

interface HistoryItem {
  prompt: string;
  response: string;
}

interface FetchAnswerStreamingProps {
  question?: string;
  apiKey?: string;
  selectedDocs?: string;
  history?: HistoryItem[];
  conversationId?: string | null;
  apiHost?: string;
  onEvent?: (event: MessageEvent) => void;
}


enum ChatStates {
  Init = 'init',
  Processing = 'processing',
  Typing = 'typing',
  Answer = 'answer',
  Minimized = 'minimized',
}

function fetchAnswerStreaming({
  question = '',
  apiKey = '',
  selectedDocs = '',
  history = [],
  conversationId = null,
  apiHost = '',
  onEvent = () => {console.log("Event triggered, but no handler provided.");}
}: FetchAnswerStreamingProps): Promise<void> {
  let docPath = 'default';
  if (selectedDocs) {
    docPath = selectedDocs;
  }

  return new Promise<void>((resolve, reject) => {
    const body = {
      question: question,
      api_key: apiKey,
      embeddings_key: apiKey,
      active_docs: docPath,
      history: JSON.stringify(history),
      conversation_id: conversationId,
      model: 'default'
    };

    fetch(apiHost + '/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
      .then((response) => {
        if (!response.body) throw Error('No response body');

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let counterrr = 0;
        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) {
            console.log(counterrr);
            resolve();
            return;
          }

          counterrr += 1;

          const chunk = decoder.decode(value);

          const lines = chunk.split('\n');

          for (let line of lines) {
            if (line.trim() == '') {
              continue;
            }
            if (line.startsWith('data:')) {
              line = line.substring(5);
            }

            const messageEvent = new MessageEvent('message', {
              data: line,
            });

            onEvent(messageEvent); // handle each message
          }

          reader.read().then(processStream).catch(reject);
        };

        reader.read().then(processStream).catch(reject);
      })
      .catch((error) => {
        console.error('Connection failed:', error);
        reject(error);
      });
  });
}

export const DocsGPTWidget = ({ apiHost = 'https://gptcloud.arc53.com', selectDocs = 'default', apiKey = 'docsgpt-public'}) => {
    // processing states
    const [chatState, setChatState] = useState<ChatStates>(() => {
        if (typeof window !== 'undefined') {
            return localStorage.getItem('docsGPTChatState') as ChatStates || ChatStates.Init;
        }
        return ChatStates.Init;
    });

    const [answer, setAnswer] = useState<string>('');

    //const selectDocs = 'local/1706.03762.pdf/'
    const answerRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (answerRef.current) {
            const element = answerRef.current;
            element.scrollTop = element.scrollHeight;
        }
    }, [answer]);

    useEffect(() => {
        if (chatState === ChatStates.Init || chatState === ChatStates.Minimized) {
            localStorage.setItem('docsGPTChatState', chatState);
        }
    }, [chatState]);



    // submit handler
    const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
        setAnswer('')
        e.preventDefault()
        // get question
        setChatState(ChatStates.Processing)
        setTimeout(() => {
            setChatState(ChatStates.Answer)
        }, 800)
        const inputElement = e.currentTarget[0] as HTMLInputElement;
        const questionValue = inputElement.value;

        fetchAnswerStreaming({
          question: questionValue,
          apiKey: apiKey,
          selectedDocs: selectDocs,
          history: [],
          conversationId: null,
          apiHost: apiHost,
          onEvent: (event) => {
            const data = JSON.parse(event.data);

            // check if the 'end' event has been received
            if (data.type === 'end') {
              setChatState(ChatStates.Answer)
            } else if (data.type === 'source') {
              // check if data.metadata exists
              let result;
              if (data.metadata && data.metadata.title) {
                const titleParts = data.metadata.title.split('/');
                result = {
                  title: titleParts[titleParts.length - 1],
                  text: data.doc,
                };
              } else {
                result = { title: data.doc, text: data.doc };
              }
              console.log(result)

            } else if (data.type === 'id') {
              console.log(data.id);
            } else {
              const result = data.answer;
              // set answer by appending answer
                setAnswer(prevAnswer => prevAnswer + result);
            }
          },
      });
    }

  return (
    <>
        <div className="dark widget-container">
            <div onClick={() => setChatState(ChatStates.Init)}
                 className={`${chatState !== 'minimized' ? 'hidden' : ''} cursor-pointer`}>
               <div className="mr-2 mb-2 w-20 h-20 rounded-full overflow-hidden dark:divide-gray-700 border dark:border-gray-700 bg-gradient-to-br from-gray-100/80 via-white to-white dark:from-gray-900/80 dark:via-gray-900 dark:to-gray-900 font-sans shadow backdrop-blur-sm flex items-center justify-center">
                        <img
                            src="https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png"
                            alt="DocsGPT"
                            className="cursor-pointer hover:opacity-50 h-14"
                        />
                    </div>
            </div>
      <div className={` ${chatState !== 'minimized' ? '' : 'hidden'} divide-y dark:divide-gray-700 rounded-md border dark:border-gray-700 bg-gradient-to-br from-gray-100/80 via-white to-white dark:from-gray-900/80 dark:via-gray-900 dark:to-gray-900 font-sans shadow backdrop-blur-sm`} style={{ width: '18rem', transform: 'translateY(0%) translateZ(0px)' }}>
        <div>
          <img
                        src="https://d3dg1063dc54p9.cloudfront.net/exit.svg"
                        alt="Exit"
                        className="cursor-pointer hover:opacity-50 h-3 absolute top-0 right-0 m-2 white-filter"
                        onClick={(event) => {
                          event.stopPropagation();
                          setChatState(ChatStates.Minimized);
                        }}
                      />
          <div className="flex items-center gap-2 p-3">
            <div  className={`${chatState === 'init' ? '' :
                                chatState === 'processing' ? '' : 
                                chatState === 'typing' ? '' :     
                               'hidden'} flex-1`}>
              <h3 className="text-sm font-bold text-gray-700 dark:text-gray-200">Looking for help with documentation?</h3>
              <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">DocsGPT AI assistant will help you with docs</p>
            </div>
            <div id="docsgpt-answer" ref={answerRef} className={`${chatState !== 'answer' ? 'hidden' : ''}`}>
                <p className="mt-1 text-sm text-gray-600 dark:text-white text-left">{answer}</p>
            </div>
          </div>
        </div>
        <div className="w-full">
          <button onClick={() => setChatState(ChatStates.Typing)}
                  className={`flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 hover:bg-gray-100 rounded-b dark:hover:bg-gray-800/70 ${chatState !== 'init' ? 'hidden' : ''}`}>
            Ask DocsGPT
          </button>
         { (chatState === 'typing' || chatState === 'answer') && (
            <form
                onSubmit={handleSubmit}
                className="relative w-full m-0" style={{ opacity: 1 }}>
              <input type="text"
                     className="w-full bg-transparent px-5 py-3 pr-8 text-sm text-gray-700 dark:text-white focus:outline-none" placeholder="What do you want to do?" />
              <button className="absolute text-gray-400 dark:text-gray-500 text-sm inset-y-0 right-2 -mx-2 px-2" type="submit" >Sumbit</button>
            </form>
          )}
          <p className={`${chatState !== 'processing' ? 'hidden' : ''} flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 rounded-b`}>
            Processing<span className="dot-animation">.</span><span className="dot-animation delay-200">.</span><span className="dot-animation delay-400">.</span>
          </p>
        </div>
      </div>
    </div>

    </>
  )
}
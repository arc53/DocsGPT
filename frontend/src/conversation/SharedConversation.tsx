import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useNavigate } from 'react-router-dom';
import { Query } from './conversationModels';
import ConversationBubble from './ConversationBubble';
import { Fragment } from 'react';
const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
const SharedConversation = () => {
  const params = useParams();
  const navigate = useNavigate();
  const { identifier } = params; //identifier is a uuid, not conversationId
  const [queries, setQueries] = useState<Query[]>([]);
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');

  function formatISODate(isoDateStr: string) {
    const date = new Date(isoDateStr);

    const monthNames = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'June',
      'July',
      'Aug',
      'Sept',
      'Oct',
      'Nov',
      'Dec',
    ];

    const month = monthNames[date.getMonth()];
    const day = date.getDate();
    const year = date.getFullYear();

    let hours = date.getHours();
    const minutes = date.getMinutes();
    const ampm = hours >= 12 ? 'PM' : 'AM';

    hours = hours % 12;
    hours = hours ? hours : 12;
    const minutesStr = minutes < 10 ? '0' + minutes : minutes;
    const formattedDate = `Published ${month} ${day}, ${year} at ${hours}:${minutesStr} ${ampm}`;
    return formattedDate;
  }
  const fetchQueris = () => {
    fetch(`${apiHost}/api/shared_conversation/${identifier}`)
      .then((res) => {
        if (res.status === 404 || res.status === 400) navigate('/pagenotfound');
        return res.json();
      })
      .then((data) => {
        if (data.success) {
          setQueries(data.queries);
          setTitle(data.title);
          setDate(formatISODate(data.timestamp));
        }
      });
  };

  const prepResponseView = (query: Query, index: number) => {
    let responseView;
    if (query.response) {
      responseView = (
        <ConversationBubble
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'}`}
          key={`${index}ANSWER`}
          message={query.response}
          type={'ANSWER'}
        ></ConversationBubble>
      );
    } else if (query.error) {
      responseView = (
        <ConversationBubble
          className={`${index === queries.length - 1 ? 'mb-32' : 'mb-7'} `}
          key={`${index}ERROR`}
          message={query.error}
          type="ERROR"
        ></ConversationBubble>
      );
    }
    return responseView;
  };
  useEffect(() => {
    fetchQueris();
  }, []);
  return (
    <div className="">
      <div className="flex h-screen flex-col items-center justify-between">
        {queries.length > 0 && (
          <div className="flex w-full justify-center overflow-auto">
            <div className="mt-0 w-11/12 md:w-6/12">
              <div className="w-full border-b pb-2">
                <h1 className="font-semi-bold text-4xl text-chinese-black dark:text-chinese-silver">
                  {title}
                </h1>
                <h2 className="font-semi-bold text-base text-chinese-black dark:text-chinese-silver">
                  Created with{' '}
                  <a href="/" className="text-[#007DFF]">
                    DocsGPT
                  </a>
                </h2>
                <h2 className="font-semi-bold text-base text-chinese-black dark:text-chinese-silver">
                  {date}
                </h2>
              </div>
              <div className="pt-2">
                {queries.map((query, index) => {
                  return (
                    <Fragment key={index}>
                      <ConversationBubble
                        className={'mb-1 last:mb-28 md:mb-7'}
                        key={`${index}QUESTION`}
                        message={query.prompt}
                        type="QUESTION"
                        sources={query.sources}
                      ></ConversationBubble>

                      {prepResponseView(query, index)}
                    </Fragment>
                  );
                })}
              </div>
            </div>
          </div>
        )}
        <div className=" flex flex-col items-center gap-4 p-4">
          <button
            onClick={() => navigate('/')}
            className="w-fit rounded-full bg-purple-30 p-4 text-white shadow-xl transition-colors duration-200 hover:bg-purple-taupe"
          >
            Get Started with DocsGPT
          </button>
          <span className="hidden text-xs text-dark-charcoal dark:text-silver sm:inline">
            This is a chatbot that uses the GPT-3, Faiss and LangChain to answer
            questions.
          </span>
        </div>
      </div>
    </div>
  );
};

export default SharedConversation;

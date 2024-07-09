import { forwardRef, useState } from 'react';
import Avatar from '../components/Avatar';
import CoppyButton from '../components/CopyButton';
import remarkGfm from 'remark-gfm';
import { FEEDBACK, MESSAGE_TYPE } from './conversationModels';
import classes from './ConversationBubble.module.css';
import Alert from './../assets/alert.svg';
import Like from './../assets/like.svg?react';
import Dislike from './../assets/dislike.svg?react';

import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
const DisableSourceFE = import.meta.env.VITE_DISABLE_SOURCE_FE || false;

const ConversationBubble = forwardRef<
  HTMLDivElement,
  {
    message: string;
    type: MESSAGE_TYPE;
    className?: string;
    feedback?: FEEDBACK;
    handleFeedback?: (feedback: FEEDBACK) => void;
    sources?: { title: string; text: string; source: string }[];
    retryBtn?: React.ReactElement;
  }
>(function ConversationBubble(
  { message, type, className, feedback, handleFeedback, sources, retryBtn },
  ref,
) {
  const [openSource, setOpenSource] = useState<number | null>(null);

  const [isLikeHovered, setIsLikeHovered] = useState(false);
  const [isDislikeHovered, setIsDislikeHovered] = useState(false);
  const [isLikeClicked, setIsLikeClicked] = useState(false);
  const [isDislikeClicked, setIsDislikeClicked] = useState(false);

  let bubble;

  if (type === 'QUESTION') {
    bubble = (
      <div ref={ref} className={`flex flex-row-reverse self-end ${className}`}>
        <Avatar className="mt-2 text-2xl" avatar="🧑‍💻"></Avatar>
        <div className="ml-10 mr-2 flex items-center rounded-[28px] bg-purple-30 py-[14px] px-[19px] text-white">
          <ReactMarkdown className="whitespace-pre-wrap break-normal leading-normal">
            {message}
          </ReactMarkdown>
        </div>
      </div>
    );
  } else {
    bubble = (
      <div
        ref={ref}
        className={`flex flex-wrap self-start ${className} group flex-col  dark:text-bright-gray`}
      >
        <div className="flex flex-wrap self-start lg:flex-nowrap">
          <Avatar
            className="mt-2 h-12 w-12 text-2xl"
            avatar={
              <img
                src={DocsGPT3}
                alt="DocsGPT"
                className="h-full w-full object-cover"
              />
            }
          />

          <div
            className={`ml-2 mr-5 flex max-w-[90vw] rounded-[28px] bg-gray-1000 py-[14px] px-7 dark:bg-gun-metal md:max-w-[70vw] lg:max-w-[50vw] ${
              type === 'ERROR'
                ? 'relative flex-row items-center rounded-full border border-transparent bg-[#FFE7E7] p-2 py-5 text-sm font-normal text-red-3000  dark:border-red-2000 dark:text-white'
                : 'flex-col rounded-3xl'
            }`}
          >
            {type === 'ERROR' && (
              <>
                <img src={Alert} alt="alert" className="mr-2 inline" />
                <div className="absolute -right-32 top-1/2 -translate-y-1/2">
                  {retryBtn}
                </div>
              </>
            )}
            <ReactMarkdown
              className="whitespace-pre-wrap break-normal leading-normal"
              remarkPlugins={[remarkGfm]}
              components={{
                code({ node, inline, className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '');

                  return !inline && match ? (
                    <div className="group relative">
                      <SyntaxHighlighter
                        PreTag="div"
                        language={match[1]}
                        {...props}
                        style={vscDarkPlus}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                      <div
                        className={`absolute right-3 top-3 lg:invisible 
                        ${type !== 'ERROR' ? 'group-hover:lg:visible' : ''} `}
                      >
                        <CoppyButton
                          text={String(children).replace(/\n$/, '')}
                        />
                      </div>
                    </div>
                  ) : (
                    <code className={className ? className : ''} {...props}>
                      {children}
                    </code>
                  );
                },
                ul({ children }) {
                  return (
                    <ul
                      className={`list-inside list-disc whitespace-normal pl-4 ${classes.list}`}
                    >
                      {children}
                    </ul>
                  );
                },
                ol({ children }) {
                  return (
                    <ol
                      className={`list-inside list-decimal whitespace-normal pl-4 ${classes.list}`}
                    >
                      {children}
                    </ol>
                  );
                },
                table({ children }) {
                  return (
                    <div className="relative overflow-x-auto rounded-lg border">
                      <table className="w-full text-left text-sm text-gray-700">
                        {children}
                      </table>
                    </div>
                  );
                },
                thead({ children }) {
                  return (
                    <thead className="text-xs uppercase text-gray-900 [&>.table-row]:bg-gray-50">
                      {children}
                    </thead>
                  );
                },
                tr({ children }) {
                  return (
                    <tr className="table-row border-b odd:bg-white even:bg-gray-50">
                      {children}
                    </tr>
                  );
                },
                td({ children }) {
                  return <td className="px-6 py-3">{children}</td>;
                },
                th({ children }) {
                  return <th className="px-6 py-3">{children}</th>;
                },
              }}
            >
              {message}
            </ReactMarkdown>
            {DisableSourceFE ||
            type === 'ERROR' ||
            !sources ||
            sources.length === 0 ? null : (
              <>
                <span className="mt-3 h-px w-full bg-[#DEDEDE]"></span>
                <div className="mt-3 flex w-full flex-row flex-wrap items-center justify-start gap-2">
                  <div className="py-1 text-base font-semibold">Sources:</div>
                  <div className="flex flex-row flex-wrap items-center justify-start gap-2">
                    {sources?.map((source, index) => (
                      <div
                        key={index}
                        className={`max-w-xs cursor-pointer rounded-[28px] px-4 py-1 sm:max-w-sm md:max-w-md ${
                          openSource === index
                            ? 'bg-[#007DFF]'
                            : 'bg-[#D7EBFD] hover:bg-[#BFE1FF]'
                        }`}
                        onClick={() =>
                          source.source !== 'local'
                            ? window.open(
                                source.source,
                                '_blank',
                                'noopener, noreferrer',
                              )
                            : setOpenSource(openSource === index ? null : index)
                        }
                      >
                        <p
                          className={`truncate text-center text-base font-medium ${
                            openSource === index
                              ? 'text-white'
                              : 'text-[#007DFF]'
                          }`}
                        >
                          {index + 1}. {source.title.substring(0, 45)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
        <div className="my-2 flex justify-start lg:ml-12">
          <div
            className={`relative mr-5  block items-center justify-center lg:invisible 
            ${type !== 'ERROR' ? 'group-hover:lg:visible' : ''}`}
          >
            <div>
              <CoppyButton text={message} />
            </div>
          </div>
          <div
            className={`relative mr-5 flex items-center justify-center ${
              !isLikeClicked ? 'lg:invisible' : ''
            } ${
              feedback === 'LIKE' || type !== 'ERROR'
                ? 'group-hover:lg:visible'
                : ''
            }`}
          >
            <div>
              <div
                className={`flex items-center justify-center rounded-full p-2 dark:bg-transparent ${
                  isLikeHovered
                    ? 'bg-[#EEEEEE] dark:bg-purple-taupe'
                    : 'bg-[#ffffff] dark:bg-transparent'
                }`}
              >
                <Like
                  className={`cursor-pointer 
                  ${
                    isLikeClicked || feedback === 'LIKE'
                      ? 'fill-white-3000 stroke-purple-30 dark:fill-transparent'
                      : 'fill-none  stroke-gray-4000'
                  }`}
                  onClick={() => {
                    handleFeedback?.('LIKE');
                    setIsLikeClicked(true);
                    setIsDislikeClicked(false);
                  }}
                  onMouseEnter={() => setIsLikeHovered(true)}
                  onMouseLeave={() => setIsLikeHovered(false)}
                ></Like>
              </div>
            </div>
          </div>
          <div
            className={`mr-13 relative flex items-center justify-center ${
              !isDislikeClicked ? 'lg:invisible' : ''
            } ${
              feedback === 'DISLIKE' || type !== 'ERROR'
                ? 'group-hover:lg:visible'
                : ''
            }`}
          >
            <div>
              <div
                className={`flex items-center justify-center rounded-full p-2 ${
                  isDislikeHovered
                    ? 'bg-[#EEEEEE] dark:bg-purple-taupe'
                    : 'bg-[#ffffff] dark:bg-transparent'
                }`}
              >
                <Dislike
                  className={`cursor-pointer ${
                    isDislikeClicked || feedback === 'DISLIKE'
                      ? 'fill-white-3000 stroke-red-2000 dark:fill-transparent'
                      : 'fill-none  stroke-gray-4000'
                  }`}
                  onClick={() => {
                    handleFeedback?.('DISLIKE');
                    setIsDislikeClicked(true);
                    setIsLikeClicked(false);
                  }}
                  onMouseEnter={() => setIsDislikeHovered(true)}
                  onMouseLeave={() => setIsDislikeHovered(false)}
                ></Dislike>
              </div>
            </div>
          </div>
        </div>

        {sources && openSource !== null && sources[openSource] && (
          <div className="ml-10 mt-12 max-w-[300px] break-words rounded-xl bg-blue-200 p-2 dark:bg-gun-metal sm:max-w-[800px] lg:mt-2">
            <p className="m-1 w-3/4 truncate text-xs text-gray-500 dark:text-bright-gray">
              Source: {sources[openSource].title}
            </p>

            <div className="m-2 rounded-xl border-2 border-gray-200 bg-white p-2 dark:border-chinese-silver dark:bg-dark-charcoal">
              <p className="text-break text-black dark:text-bright-gray">
                {sources[openSource].text}
              </p>
            </div>
          </div>
        )}
      </div>
    );
  }
  return bubble;
});

export default ConversationBubble;

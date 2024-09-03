import { forwardRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { useSelector } from 'react-redux';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import remarkGfm from 'remark-gfm';

import Alert from '../assets/alert.svg';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import Dislike from '../assets/dislike.svg?react';
import Document from '../assets/document.svg';
import Like from '../assets/like.svg?react';
import Link from '../assets/link.svg';
import Sources from '../assets/sources.svg';
import Avatar from '../components/Avatar';
import CopyButton from '../components/CopyButton';
import Sidebar from '../components/Sidebar';
import {
  selectChunks,
  selectSelectedDocs,
} from '../preferences/preferenceSlice';
import classes from './ConversationBubble.module.css';
import { FEEDBACK, MESSAGE_TYPE } from './conversationModels';

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
  const chunks = useSelector(selectChunks);
  const selectedDocs = useSelector(selectSelectedDocs);
  const [isLikeHovered, setIsLikeHovered] = useState(false);
  const [isDislikeHovered, setIsDislikeHovered] = useState(false);
  const [isLikeClicked, setIsLikeClicked] = useState(false);
  const [isDislikeClicked, setIsDislikeClicked] = useState(false);
  const [activeTooltip, setActiveTooltip] = useState<number | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);

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
        {DisableSourceFE ||
        type === 'ERROR' ||
        sources?.length === 0 ||
        sources?.some((source) => source.source === 'None') ? null : !sources &&
          chunks !== '0' &&
          selectedDocs ? (
          <div className="mb-4 flex flex-col flex-wrap items-start self-start lg:flex-nowrap">
            <div className="my-2 flex flex-row items-center justify-center gap-3">
              <Avatar
                className="h-[26px] w-[30px] text-xl"
                avatar={
                  <img
                    src={Sources}
                    alt="Sources"
                    className="h-full w-full object-fill"
                  />
                }
              />
              <p className="text-base font-semibold">Sources</p>
            </div>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <div
                  key={index}
                  className="flex h-28 cursor-pointer flex-col items-start gap-1 rounded-[20px] bg-gray-1000 p-4 text-purple-30 hover:bg-[#F1F1F1] hover:text-[#6D3ECC] dark:bg-gun-metal dark:hover:bg-[#2C2E3C] dark:hover:text-[#8C67D7]"
                >
                  <span className="h-px w-10 animate-pulse cursor-pointer rounded-[20px] bg-[#B2B2B2] p-1"></span>
                  <span className="h-px w-24 animate-pulse cursor-pointer rounded-[20px] bg-[#B2B2B2] p-1"></span>
                  <span className="h-px w-16 animate-pulse cursor-pointer rounded-[20px] bg-[#B2B2B2] p-1"></span>
                  <span className="h-px w-32 animate-pulse cursor-pointer rounded-[20px] bg-[#B2B2B2] p-1"></span>
                  <span className="h-px w-24 animate-pulse cursor-pointer rounded-[20px] bg-[#B2B2B2] p-1"></span>
                  <span className="h-px w-20 animate-pulse cursor-pointer rounded-[20px] bg-[#B2B2B2] p-1"></span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          sources && (
            <div className="mb-4 flex flex-col flex-wrap items-start self-start lg:flex-nowrap">
              <div className="my-2 flex flex-row items-center justify-center gap-3">
                <Avatar
                  className="h-[26px] w-[30px] text-xl"
                  avatar={
                    <img
                      src={Sources}
                      alt="Sources"
                      className="h-full w-full object-fill"
                    />
                  }
                />
                <p className="text-base font-semibold">Sources</p>
              </div>
              <div className="ml-3 mr-5 max-w-[90vw] md:max-w-[70vw] lg:max-w-[50vw]">
                <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                  {sources?.slice(0, 3)?.map((source, index) => (
                    <div key={index} className="relative">
                      <div
                        className="h-28 cursor-pointer rounded-[20px] bg-gray-1000 p-4 hover:bg-[#F1F1F1] dark:bg-gun-metal dark:hover:bg-[#2C2E3C]"
                        onMouseOver={() => setActiveTooltip(index)}
                        onMouseOut={() => setActiveTooltip(null)}
                      >
                        <p className="ellipsis-text h-12 break-words text-xs">
                          {source.text}
                        </p>
                        <div
                          className={`mt-[14px] flex flex-row items-center gap-[6px] underline-offset-2 ${
                            source.source && source.source !== 'local'
                              ? 'hover:text-[#007DFF] hover:underline dark:hover:text-[#48A0FF]'
                              : ''
                          }`}
                          onClick={() =>
                            source.source && source.source !== 'local'
                              ? window.open(
                                  source.source,
                                  '_blank',
                                  'noopener, noreferrer',
                                )
                              : null
                          }
                        >
                          <img
                            src={Document}
                            alt="Document"
                            className="h-[17px] w-[17px] object-fill"
                          />
                          <p
                            className="mt-[2px] truncate text-xs"
                            title={
                              source.source && source.source !== 'local'
                                ? source.source
                                : source.title
                            }
                          >
                            {source.source && source.source !== 'local'
                              ? source.source
                              : source.title}
                          </p>
                        </div>
                      </div>
                      {activeTooltip === index && (
                        <div
                          className={`absolute left-1/2 z-30 max-h-48 w-40 translate-x-[-50%] translate-y-[3px] rounded-xl bg-[#FBFBFB] p-4 text-black shadow-xl dark:bg-chinese-black dark:text-chinese-silver sm:w-56`}
                          onMouseOver={() => setActiveTooltip(index)}
                          onMouseOut={() => setActiveTooltip(null)}
                        >
                          <p className="max-h-[164px] overflow-y-auto break-words rounded-md text-sm">
                            {source.text}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                  {(sources?.length ?? 0) > 3 && (
                    <div
                      className="flex h-24 cursor-pointer flex-col-reverse rounded-[20px] bg-gray-1000 p-4 text-purple-30 hover:bg-[#F1F1F1] hover:text-[#6D3ECC] dark:bg-gun-metal dark:hover:bg-[#2C2E3C] dark:hover:text-[#8C67D7]"
                      onClick={() => setIsSidebarOpen(true)}
                    >
                      <p className="ellipsis-text h-22 text-xs">{`View ${
                        sources?.length ? sources.length - 3 : 0
                      } more`}</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        )}
        <div className="flex flex-col flex-wrap items-start self-start lg:flex-nowrap">
          <div className="my-2 flex flex-row items-center justify-center gap-3">
            <Avatar
              className="h-[34px] w-[34px] text-2xl"
              avatar={
                <img
                  src={DocsGPT3}
                  alt="DocsGPT"
                  className="h-full w-full object-cover"
                />
              }
            />
            <p className="text-base font-semibold">Answer</p>
          </div>
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
                code(props) {
                  const { children, className, node, ref, ...rest } = props;
                  const match = /language-(\w+)/.exec(className || '');

                  return match ? (
                    <div className="group relative">
                      <SyntaxHighlighter
                        {...rest}
                        PreTag="div"
                        language={match[1]}
                        style={vscDarkPlus}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                      <div
                        className={`absolute right-3 top-3 lg:invisible 
                        ${type !== 'ERROR' ? 'group-hover:lg:visible' : ''} `}
                      >
                        <CopyButton
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
          </div>
        </div>
        <div className="my-2 ml-2 flex justify-start">
          <div
            className={`relative mr-5  block items-center justify-center lg:invisible 
            ${type !== 'ERROR' ? 'group-hover:lg:visible' : ''}`}
          >
            <div>
              <CopyButton text={message} />
            </div>
          </div>
          {handleFeedback && (
            <>
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
            </>
          )}
        </div>
        {sources && (
          <Sidebar
            isOpen={isSidebarOpen}
            toggleState={(state: boolean) => {
              setIsSidebarOpen(state);
            }}
          >
            <AllSources sources={sources} />
          </Sidebar>
        )}
      </div>
    );
  }
  return bubble;
});

type AllSourcesProps = {
  sources: { title: string; text: string; source: string }[];
};

function AllSources(sources: AllSourcesProps) {
  return (
    <div className="h-full w-full">
      <div className="w-full">
        <p className="text-left text-xl">{`${sources.sources.length} Sources`}</p>
        <div className="mx-1 mt-2 h-[0.8px] w-full rounded-full bg-[#C4C4C4]/40 lg:w-[95%] "></div>
      </div>
      <div className="mt-6 flex h-[90%] w-60 flex-col items-center gap-4 overflow-y-auto sm:w-80">
        {sources.sources.map((source, index) => (
          <div
            key={index}
            className="min-h-32 w-full rounded-[20px] bg-gray-1000 p-4 dark:bg-[#28292E]"
          >
            <span className="flex flex-row">
              <p
                title={source.title}
                className="ellipsis-text break-words text-left text-sm font-semibold"
              >
                {`${index + 1}. ${source.title}`}
              </p>
              {source.source && source.source !== 'local' ? (
                <img
                  src={Link}
                  alt="Link"
                  className="h-3 w-3 cursor-pointer object-fill"
                  onClick={() =>
                    window.open(source.source, '_blank', 'noopener, noreferrer')
                  }
                ></img>
              ) : null}
            </span>
            <p className="mt-3 max-h-24 overflow-y-auto break-words rounded-md text-left text-xs text-black dark:text-chinese-silver">
              {source.text}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ConversationBubble;

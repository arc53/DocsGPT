import { forwardRef, useState, useEffect } from 'react';
import 'katex/dist/katex.min.css';
import ReactMarkdown from 'react-markdown';
import { useSelector } from 'react-redux';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import Dislike from '../assets/dislike.svg?react';
import Document from '../assets/document.svg';
import Like from '../assets/like.svg?react';
import Link from '../assets/link.svg';
import Sources from '../assets/sources.svg';
import Avatar from '../components/Avatar';
import CopyButton from '../components/CopyButton';
import Sidebar from '../components/Sidebar';
import { selectChunks, selectSelectedDocs } from '../preferences/preferenceSlice';
import SpeakButton from '../components/TextToSpeechButton';
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
  // const bubbleRef = useRef<HTMLDivElement | null>(null);
  const chunks = useSelector(selectChunks);
  const selectedDocs = useSelector(selectSelectedDocs);
  const [isLikeHovered, setIsLikeHovered] = useState(false);
  const [isDislikeHovered, setIsDislikeHovered] = useState(false);
  const [isLikeClicked, setIsLikeClicked] = useState(false);
  const [isDislikeClicked, setIsDislikeClicked] = useState(false);
  const [activeTooltip, setActiveTooltip] = useState<number | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);

  // State to track feedback submission
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);

  // Load feedback submission state from localStorage on mount
  useEffect(() => {
    const isFeedbackSubmitted = localStorage.getItem('feedbackSubmitted') === 'true';
    setFeedbackSubmitted(isFeedbackSubmitted);
  }, []);

  // Handler for Like feedback
  const handleLikeClick = () => {
    if (!feedbackSubmitted) {
      handleFeedback?.('LIKE');
      localStorage.setItem('feedbackSubmitted', 'true');
      setFeedbackSubmitted(true);
      setIsLikeClicked(true);
      setIsDislikeClicked(false);
    }
  };

  // Handler for Dislike feedback
  const handleDislikeClick = () => {
    if (!feedbackSubmitted) {
      handleFeedback?.('DISLIKE');
      localStorage.setItem('feedbackSubmitted', 'true');
      setFeedbackSubmitted(true);
      setIsDislikeClicked(true);
      setIsLikeClicked(false);
    }
  };

  let bubble;
  if (type === 'QUESTION') {
    bubble = (
      <div
        ref={ref}
        className={`flex flex-row-reverse self-end flex-wrap ${className}`}
      >
        <Avatar className="mt-2 text-2xl" avatar="🧑‍💻"></Avatar>
        <div
          style={{ wordBreak: 'break-word' }}
          className="ml-10 mr-2 flex items-center rounded-[28px] bg-purple-30 py-[14px] px-[19px] text-white max-w-full whitespace-pre-wrap leading-normal"
        >
          {message}
        </div>
      </div>
    );
  } else {
    const preprocessLaTeX = (content: string) => {
      const blockProcessedContent = content.replace(
        /\\

\[(.*?)\\\]

/gs,
        (_, equation) => `$$${equation}$$`
      );
      const inlineProcessedContent = blockProcessedContent.replace(
        /\\\((.*?)\\\)/gs,
        (_, equation) => `$${equation}$`
      );
      return inlineProcessedContent;
    };

    bubble = (
      <div ref={ref} className={`group flex self-start flex-wrap ${className}`}>
        <Avatar className="mt-2 text-2xl" avatar="🤖"></Avatar>
        <div className="ml-2 flex flex-col">
          <div
            style={{ wordBreak: 'break-word' }}
            className="relative min-w-[150px] rounded-[28px] bg-gray-1000 p-4 text-gray-900 dark:bg-purple-20 dark:text-white"
          >
            <ReactMarkdown
              className="fade-in whitespace-pre-wrap break-normal leading-normal"
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                code({ node, inline, className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '');
                  return !inline && match ? (
                    <SyntaxHighlighter
                      style={vscDarkPlus}
                      language={match[1]}
                      PreTag="div"
                      {...props}
                    >
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                },
                ul({ children }) {
                  return (
                    <ul className={`list-inside list-disc whitespace-normal pl-4 ${classes.list}`}>
                      {children}
                    </ul>
                  );
                },
                ol({ children }) {
                  return (
                    <ol className={`list-inside list-decimal whitespace-normal pl-4 ${classes.list}`}>
                      {children}
                    </ol>
                  );
                },
                table({ children }) {
                  return (
                    <table className="min-w-full divide-y divide-gray-300">
                      {children}
                    </table>
                  );
                },
                thead({ children }) {
                  return (
                    <thead className="bg-gray-50">
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
              {preprocessLaTeX(message)}
            </ReactMarkdown>
          </div>
        </div>
        <div className="my-2 ml-2 flex justify-start">
          <div
            className={`relative mr-5 block items-center justify-center lg:invisible ${type !== 'ERROR' ? 'group-hover:lg:visible' : 'hidden'}`}
          >
            <div>
              <CopyButton text={message} />
            </div>
          </div>
          <div
            className={`relative mr-5 block items-center justify-center lg:invisible ${type !== 'ERROR' ? 'group-hover:lg:visible' : 'hidden'}`}
          >
            <div>
              <SpeakButton text={message} /> {/* Add SpeakButton here */}
            </div>
          </div>
          {type === 'ERROR' && (
            <div className="relative mr-5 block items-center justify-center">
              <div>{retryBtn}</div>
            </div>
          )}
          {handleFeedback && (
            <>
              <div
                className={`relative mr-5 flex items-center justify-center ${!isLikeClicked ? 'lg:invisible' : ''} ${feedback === 'LIKE' || type !== 'ERROR' ? 'group-hover:lg:visible' : ''}`}
              >
                <div>
                  <div className={`flex items-center justify-center rounded-full p-2 ${isLikeHovered ? 'bg-[#EEEEEE] dark:bg-purple-taupe' : 'bg-[#ffffff] dark:bg-transparent'}`}>
                    <Like
                      className={`cursor-pointer ${isLikeClicked || feedback === 'LIKE' ? 'fill-white-3000 stroke-purple-30 dark:fill-transparent' : 'fill-none  stroke-gray-4000'}`}
                      onClick={handleLikeClick}
                      onMouseEnter={() => setIsLikeHovered(true)}
                      onMouseLeave={() => setIsLikeHovered(false)}
                    ></Like>
                  </div>
                </div>
              </div>
              <div
                className={`mr-13 relative flex items-center justify-center ${!isDislikeClicked ? 'lg:invisible' : ''} ${feedback === 'DISLIKE' || type !== 'ERROR' ? 'group-hover:lg:visible' : ''}`}
              >
                <div>
                  <div className={`flex items-center justify-center rounded-full p-2 ${isDislikeHovered ? 'bg-[#EEEEEE] dark:bg-purple-taupe' : 'bg-[#ffffff] dark:bg-transparent'}`}>
                    <Dislike
                      className={`cursor-pointer ${isDislikeClicked || feedback === 'DISLIKE' ? 'fill-white-3000 stroke-red-2000 dark:fill-transparent' : 'fill-none  stroke-gray-4000'}`}
                      onClick={handleDislikeClick}
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
            toggleState={(state) => setIsSidebarOpen(state)}
          >
            <AllSources sources={sources} />
          </Sidebar>
        )}
      </div>
    );
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
              components={{
                code({ node, inline, className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '');
                  return !inline && match ? (
                    <SyntaxHighlighter
                      children={String(children).replace(/\n$/, '')}
                      style={vscDarkPlus}
                      language={match[1]}
                      PreTag="div"
                      {...props}
                    />
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                },
                ul({ children }) {
                  return (
                    <ul className={`list-inside list-disc whitespace-normal pl-4 ${classes.list}`}>
                      {children}
                    </ul>
                  );
                },
                ol({ children }) {
                  return (
                    <ol className={`list-inside list-decimal whitespace-normal pl-4 ${classes.list}`}>
                      {children}
                    </ol>
                  );
                },
                table({ children }) {
                  return (
                    <table className="min-w-full divide-y divide-gray-300">
                      {children}
                    </table>
                  );
                },
                thead({ children }) {
                  return (
                    <thead className="bg-gray-50">
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
              {preprocessLaTeX(message)}
            </ReactMarkdown>
          </div>
        </div>
        <div className="my-2 ml-2 flex justify-start">
         <div
  className={`relative mr-5 block items-center justify-center lg:invisible 
  ${type !== 'ERROR' ? 'group-hover:lg:visible' : 'hidden'}`}
>
  <div>
    <CopyButton text={message} />
  </div>
</div>
<div
  className={`relative mr-5 block items-center justify-center lg:invisible 
  ${type !== 'ERROR' ? 'group-hover:lg:visible' : 'hidden'}`}
>
  <div>
    <SpeakButton text={message} /> {/* Add SpeakButton here */}
  </div>
</div>
{type === 'ERROR' && (
  <div className="relative mr-5 block items-center justify-center">
    <div>{retryBtn}</div>
  </div>
)}
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
          className={`flex items-center justify-center rounded-full p-2 ${
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
            onClick={handleLikeClick}
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
            onClick={handleDislikeClick}
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
        <p className="mt-3 max-h-16 overflow-y-auto break-words rounded-md text-left text-xs text-black dark:text-chinese-silver">
          {source.text}
        </p>
      </div>
    ))}
  </div>
</div>
);
}

export default ConversationBubble;

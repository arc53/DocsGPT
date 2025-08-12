import { useState, useEffect } from 'react';

interface SkeletonLoaderProps {
  count?: number;
  component?:
    | 'default'
    | 'analysis'
    | 'logs'
    | 'table'
    | 'chatbot'
    | 'dropdown'
    | 'chunkCards'
    | 'sourceCards';
}

const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({
  count = 1,
  component = 'default',
}) => {
  const [skeletonCount, setSkeletonCount] = useState(count);

  useEffect(() => {
    const handleResize = () => {
      const windowWidth = window.innerWidth;

      if (windowWidth > 1024) {
        setSkeletonCount(1);
      } else if (windowWidth > 768) {
        setSkeletonCount(count);
      } else {
        setSkeletonCount(Math.min(count, 2));
      }
    };

    handleResize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, [count]);

  const renderTable = () => (
    <>
      {[...Array(4)].map((_, idx) => (
        <tr key={idx} className="animate-pulse">
          <td className="w-[45%] px-4 py-4">
            <div className="h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
          <td className="w-[20%] px-4 py-4">
            <div className="h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
          <td className="w-[25%] px-4 py-4">
            <div className="h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
          <td className="w-[10%] px-4 py-4">
            <div className="h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
        </tr>
      ))}
    </>
  );

  const renderChatbot = () => (
    <>
      {[...Array(4)].map((_, idx) => (
        <tr key={idx} className="animate-pulse">
          <td className="p-2">
            <div className="mx-auto h-4 w-3/4 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
          <td className="p-2">
            <div className="mx-auto h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
          <td className="p-2">
            <div className="mx-auto h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
          <td className="p-2">
            <div className="mx-auto h-4 w-8 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </td>
        </tr>
      ))}
    </>
  );

  const renderDropdown = () => (
    <div className="animate-pulse">
      <div className="mb-2 h-4 w-24 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
      <div className="flex h-14 w-[360px] items-center justify-between rounded-3xl bg-gray-300 px-4 dark:bg-gray-600">
        <div className="h-3 w-24 rounded-sm bg-gray-400 dark:bg-gray-700"></div>
        <div className="h-3 w-3 rounded-sm bg-gray-400 dark:bg-gray-700"></div>
      </div>
    </div>
  );

  const renderLogs = () => (
    <div className="w-full animate-pulse space-y-px">
      {[...Array(8)].map((_, idx) => (
        <div
          key={idx}
          className="dark:hover:bg-dark-charcoal flex w-full items-start p-2 hover:bg-[#F9F9F9]"
        >
          <div className="flex w-full items-center gap-2">
            <div className="h-3 w-3 rounded-lg bg-gray-300 dark:bg-gray-600"></div>
            <div className="flex w-full flex-row items-center gap-2">
              <div className="h-3 w-[30%] rounded-lg bg-gray-300 lg:w-52 dark:bg-gray-600"></div>
              <div className="h-3 w-[16%] rounded-lg bg-gray-300 lg:w-28 dark:bg-gray-600"></div>
              <div className="h-3 w-[40%] rounded-lg bg-gray-300 lg:w-64 dark:bg-gray-600"></div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );

  const renderDefault = () => (
    <>
      {[...Array(skeletonCount)].map((_, idx) => (
        <div
          key={idx}
          className={`p-6 ${
            skeletonCount === 1 ? 'w-full' : 'w-60'
          } dark:bg-raisin-black animate-pulse rounded-3xl`}
        >
          <div className="space-y-4">
            <div>
              <div className="mb-2 h-4 w-3/4 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-5/6 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-1/2 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-3/4 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
            </div>
            <div className="my-4 border-t border-gray-400 dark:border-gray-700"></div>
            <div>
              <div className="mb-2 h-4 w-2/3 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-1/4 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
            </div>
            <div className="my-4 border-t border-gray-400 dark:border-gray-700"></div>
            <div>
              <div className="mb-2 h-4 w-5/6 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-1/3 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-2/3 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="mb-2 h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
            </div>
            <div className="my-4 border-t border-gray-400 dark:border-gray-700"></div>
            <div className="mb-2 h-4 w-3/4 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
            <div className="mb-2 h-4 w-5/6 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
          </div>
        </div>
      ))}
    </>
  );

  const renderAnalysis = () => (
    <>
      {[...Array(skeletonCount)].map((_, idx) => (
        <div
          key={idx}
          className="dark:bg-raisin-black w-full animate-pulse rounded-3xl p-6"
        >
          <div className="space-y-6">
            <div className="space-y-2">
              <div className="mb-4 h-4 w-1/3 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="grid grid-cols-6 items-end gap-2">
                <div className="h-32 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
                <div className="h-24 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
                <div className="h-40 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
                <div className="h-28 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
                <div className="h-36 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
                <div className="h-20 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="mb-4 h-4 w-1/4 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="h-32 rounded-sm bg-gray-300 dark:bg-gray-600"></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
              <div className="h-4 w-full rounded-sm bg-gray-300 dark:bg-gray-600"></div>
            </div>
          </div>
        </div>
      ))}
    </>
  );

  const renderChunkCards = () => (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={`chunk-skel-${index}`}
          className="relative flex h-[197px] flex-col rounded-[5.86px] border border-[#D1D9E0] dark:border-[#6A6A6A] overflow-hidden w-full max-w-[487px] animate-pulse"
        >
          <div className="w-full">
            <div className="flex w-full items-center justify-between border-b border-[#D1D9E0] bg-[#F6F8FA] dark:bg-[#27282D] dark:border-[#6A6A6A] px-4 py-3">
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-20"></div>
            </div>
            <div className="px-4 pt-4 pb-6 space-y-3">
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-full"></div>
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-11/12"></div>
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-5/6"></div>
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-4/5"></div>
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-3/4"></div>
              <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-2/3"></div>
            </div>
          </div>
        </div>
      ))}
    </>
  );

  const renderSourceCards = () => (
    <>
      {Array.from({ length: count }).map((_, idx) => (
        <div
          key={`source-skel-${idx}`}
          className="flex h-[130px] w-full flex-col rounded-2xl bg-[#F9F9F9] dark:bg-[#383838] p-3 animate-pulse"
        >
          <div className="w-full flex-1">
            <div className="flex w-full items-center justify-between gap-2">
              <div className="flex-1">
                <div className="h-[13px] w-full rounded bg-gray-200 dark:bg-gray-700"></div>
              </div>
              <div className="w-6 h-6 rounded bg-gray-200 dark:bg-gray-700"></div>
            </div>
          </div>

          <div className="flex flex-col items-start justify-start gap-1 pt-3">
            <div className="flex items-center gap-2 mb-1">
              <div className="w-3 h-3 rounded bg-gray-200 dark:bg-gray-700"></div>
              <div className="h-[12px] w-20 rounded bg-gray-200 dark:bg-gray-700"></div>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded bg-gray-200 dark:bg-gray-700"></div>
              <div className="h-[12px] w-16 rounded bg-gray-200 dark:bg-gray-700"></div>
            </div>
          </div>
        </div>
      ))}
    </>
  );

  const componentMap = {
    table: renderTable,
    chatbot: renderChatbot,
    dropdown: renderDropdown,
    logs: renderLogs,
    default: renderDefault,
    analysis: renderAnalysis,
    chunkCards: renderChunkCards,
    sourceCards: renderSourceCards,
  };


  const render = componentMap[component] || componentMap.default;

  return <>{render()}</>;
};

export default SkeletonLoader;

import { useState, useEffect } from 'react';

interface SkeletonLoaderProps {
  count?: number;
  component?:
    | 'default'
    | 'analysis'
    | 'logs'
    | 'fileTable'
    | 'chatbot'
    | 'dropdown'
    | 'chunkCards'
    | 'sourceCards'
    | 'toolCards'
    | 'addToolCards'
    | 'connectedState'
    | 'filesSection';
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
          <td className="w-[40%] px-4 py-4">
            <div className="bg-muted h-4 w-full rounded-sm"></div>
          </td>
          <td className="w-[30%] px-4 py-4">
            <div className="bg-muted h-4 w-full rounded-sm"></div>
          </td>
          <td className="w-[20%] px-4 py-4">
            <div className="bg-muted h-4 w-full rounded-sm"></div>
          </td>
          <td className="w-[10%] px-4 py-4">
            <div className="bg-muted h-4 w-full rounded-sm"></div>
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
            <div className="bg-muted mx-auto h-4 w-3/4 rounded-sm"></div>
          </td>
          <td className="p-2">
            <div className="bg-muted mx-auto h-4 w-full rounded-sm"></div>
          </td>
          <td className="p-2">
            <div className="bg-muted mx-auto h-4 w-full rounded-sm"></div>
          </td>
          <td className="p-2">
            <div className="bg-muted mx-auto h-4 w-8 rounded-sm"></div>
          </td>
        </tr>
      ))}
    </>
  );

  const renderDropdown = () => (
    <div className="animate-pulse">
      <div className="bg-muted mb-2 h-4 w-24 rounded-sm"></div>
      <div className="bg-muted flex h-14 w-[360px] items-center justify-between rounded-3xl px-4">
        <div className="bg-muted-foreground/20 h-3 w-24 rounded-sm"></div>
        <div className="bg-muted-foreground/20 h-3 w-3 rounded-sm"></div>
      </div>
    </div>
  );

  const renderLogs = () => (
    <div className="w-full animate-pulse space-y-px">
      {[...Array(8)].map((_, idx) => (
        <div
          key={idx}
          className="dark:hover:bg-accent hover:bg-muted flex w-full items-start p-2"
        >
          <div className="flex w-full items-center gap-2">
            <div className="bg-muted h-3 w-3 rounded-lg"></div>
            <div className="flex w-full flex-row items-center gap-2">
              <div className="bg-muted h-3 w-[30%] rounded-lg lg:w-52"></div>
              <div className="bg-muted h-3 w-[16%] rounded-lg lg:w-28"></div>
              <div className="bg-muted h-3 w-[40%] rounded-lg lg:w-64"></div>
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
          } animate-pulse rounded-3xl`}
        >
          <div className="space-y-4">
            <div>
              <div className="bg-muted mb-2 h-4 w-3/4 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-5/6 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-1/2 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-3/4 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-full rounded-sm"></div>
            </div>
            <div className="border-border my-4 border-t"></div>
            <div>
              <div className="bg-muted mb-2 h-4 w-2/3 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-1/4 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-full rounded-sm"></div>
            </div>
            <div className="border-border my-4 border-t"></div>
            <div>
              <div className="bg-muted mb-2 h-4 w-5/6 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-1/3 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-2/3 rounded-sm"></div>
              <div className="bg-muted mb-2 h-4 w-full rounded-sm"></div>
            </div>
            <div className="border-border my-4 border-t"></div>
            <div className="bg-muted mb-2 h-4 w-3/4 rounded-sm"></div>
            <div className="bg-muted mb-2 h-4 w-5/6 rounded-sm"></div>
          </div>
        </div>
      ))}
    </>
  );

  const renderAnalysis = () => (
    <>
      {[...Array(skeletonCount)].map((_, idx) => (
        <div key={idx} className="bg-card w-full animate-pulse rounded-3xl p-6">
          <div className="space-y-6">
            <div className="space-y-2">
              <div className="bg-muted mb-4 h-4 w-1/3 rounded-sm"></div>
              <div className="grid grid-cols-6 items-end gap-2">
                <div className="bg-muted h-32 rounded-sm"></div>
                <div className="bg-muted h-24 rounded-sm"></div>
                <div className="bg-muted h-40 rounded-sm"></div>
                <div className="bg-muted h-28 rounded-sm"></div>
                <div className="bg-muted h-36 rounded-sm"></div>
                <div className="bg-muted h-20 rounded-sm"></div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="bg-muted mb-4 h-4 w-1/4 rounded-sm"></div>
              <div className="bg-muted h-32 rounded-sm"></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-muted h-4 w-full rounded-sm"></div>
              <div className="bg-muted h-4 w-full rounded-sm"></div>
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
          className="border-border dark:border-border relative flex h-[197px] w-full max-w-[487px] animate-pulse flex-col overflow-hidden rounded-md border"
        >
          <div className="w-full">
            <div className="border-border bg-muted dark:border-border dark:bg-card flex w-full items-center justify-between border-b px-4 py-3">
              <div className="bg-muted-foreground/20 h-4 w-20 rounded"></div>
            </div>
            <div className="space-y-3 px-4 pt-4 pb-6">
              <div className="bg-muted h-3 w-full rounded"></div>
              <div className="bg-muted h-3 w-11/12 rounded"></div>
              <div className="bg-muted h-3 w-5/6 rounded"></div>
              <div className="bg-muted h-3 w-4/5 rounded"></div>
              <div className="bg-muted h-3 w-3/4 rounded"></div>
              <div className="bg-muted h-3 w-2/3 rounded"></div>
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
          className="bg-muted dark:bg-accent flex h-[130px] w-full animate-pulse flex-col rounded-2xl p-3"
        >
          <div className="w-full flex-1">
            <div className="flex w-full items-center justify-between gap-2">
              <div className="flex-1">
                <div className="bg-muted-foreground/20 h-[13px] w-full rounded"></div>
              </div>
              <div className="bg-muted-foreground/20 h-6 w-6 rounded"></div>
            </div>
          </div>

          <div className="flex flex-col items-start justify-start gap-1 pt-3">
            <div className="mb-1 flex items-center gap-2">
              <div className="bg-muted-foreground/20 h-3 w-3 rounded"></div>
              <div className="bg-muted-foreground/20 h-[12px] w-20 rounded"></div>
            </div>
            <div className="flex items-center gap-2">
              <div className="bg-muted-foreground/20 h-3 w-3 rounded"></div>
              <div className="bg-muted-foreground/20 h-[12px] w-16 rounded"></div>
            </div>
          </div>
        </div>
      ))}
    </>
  );

  const renderAddToolCards = () => (
    <>
      {Array.from({ length: count }).map((_, idx) => (
        <div
          key={`add-tool-skel-${idx}`}
          className="border-border flex h-52 w-full animate-pulse flex-col justify-between rounded-2xl border p-6"
        >
          <div className="w-full">
            <div className="flex w-full items-center justify-between px-1">
              <div className="bg-muted h-6 w-6 rounded"></div>
            </div>
            <div className="mt-[9px] space-y-2 px-1">
              <div className="bg-muted h-4 w-2/3 rounded"></div>
              <div className="bg-muted h-3 w-full rounded"></div>
              <div className="bg-muted h-3 w-5/6 rounded"></div>
              <div className="bg-muted h-3 w-3/4 rounded"></div>
            </div>
          </div>
        </div>
      ))}
    </>
  );

  const renderToolCards = () => (
    <>
      {Array.from({ length: count }).map((_, idx) => (
        <div
          key={`tool-skel-${idx}`}
          className="bg-muted flex h-52 w-[300px] animate-pulse flex-col justify-between rounded-2xl p-6"
        >
          <div className="w-full">
            <div className="flex items-center gap-2 px-1">
              <div className="bg-muted-foreground/20 h-6 w-6 rounded"></div>
            </div>
            <div className="mt-[9px] space-y-2 px-1">
              <div className="bg-muted-foreground/20 h-4 w-2/3 rounded"></div>
              <div className="bg-muted-foreground/20 h-3 w-full rounded"></div>
              <div className="bg-muted-foreground/20 h-3 w-5/6 rounded"></div>
              <div className="bg-muted-foreground/20 h-3 w-3/4 rounded"></div>
            </div>
          </div>
          <div className="flex justify-end">
            <div className="bg-muted-foreground/20 h-5 w-9 rounded-full"></div>
          </div>
        </div>
      ))}
    </>
  );

  const renderConnectedState = () => (
    <div className="mb-4">
      <div className="bg-muted flex w-full animate-pulse items-center justify-between rounded-lg px-4 py-2">
        <div className="flex items-center gap-2">
          <div className="bg-muted-foreground/20 h-4 w-4 rounded"></div>
          <div className="bg-muted-foreground/20 h-4 w-32 rounded"></div>
        </div>
        <div className="bg-muted-foreground/20 h-4 w-16 rounded"></div>
      </div>
    </div>
  );

  const renderFilesSection = () => (
    <div className="border-border dark:border-border rounded-lg border">
      <div className="p-4">
        <div className="mb-4 flex items-center justify-between">
          <div className="bg-muted h-5 w-24 animate-pulse rounded"></div>
          <div className="bg-muted h-8 w-24 animate-pulse rounded"></div>
        </div>
        <div className="bg-muted h-4 w-40 animate-pulse rounded"></div>
      </div>
    </div>
  );

  const componentMap = {
    fileTable: renderTable,
    chatbot: renderChatbot,
    dropdown: renderDropdown,
    logs: renderLogs,
    default: renderDefault,
    analysis: renderAnalysis,
    chunkCards: renderChunkCards,
    sourceCards: renderSourceCards,
    toolCards: renderToolCards,
    addToolCards: renderAddToolCards,
    connectedState: renderConnectedState,
    filesSection: renderFilesSection,
  };

  const render = componentMap[component] || componentMap.default;

  return <>{render()}</>;
};

export default SkeletonLoader;

import { useTranslation } from 'react-i18next';

import { Card } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { useMediaQuery } from '@/hooks';
import { cn } from '@/lib/utils';

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
    | 'agentCards'
    | 'connectedState'
    | 'filesSection';
}

const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({
  count = 1,
  component = 'default',
}) => {
  const { t } = useTranslation();
  const { isDesktop } = useMediaQuery();
  // One placeholder beside the desktop shell, at most two below it.
  const skeletonCount = isDesktop ? 1 : Math.min(count, 2);

  const renderTable = () => (
    <>
      {[...Array(4)].map((_, idx) => (
        <tr key={idx}>
          <td className="w-[40%] px-4 py-4">
            <Skeleton className="h-4 w-full" />
          </td>
          <td className="w-[30%] px-4 py-4">
            <Skeleton className="h-4 w-full" />
          </td>
          <td className="w-[20%] px-4 py-4">
            <Skeleton className="h-4 w-full" />
          </td>
          <td className="w-[10%] px-4 py-4">
            <Skeleton className="h-4 w-full" />
          </td>
        </tr>
      ))}
    </>
  );

  const renderChatbot = () => (
    <>
      {[...Array(4)].map((_, idx) => (
        <tr key={idx}>
          <td className="p-2">
            <Skeleton className="mx-auto h-4 w-3/4" />
          </td>
          <td className="p-2">
            <Skeleton className="mx-auto h-4 w-full" />
          </td>
          <td className="p-2">
            <Skeleton className="mx-auto h-4 w-full" />
          </td>
          <td className="p-2">
            <Skeleton className="mx-auto h-4 w-8" />
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
        <div className="bg-muted-foreground/20 size-3 rounded-sm"></div>
      </div>
    </div>
  );

  const renderLogs = () => (
    <div className="flex w-full flex-col gap-px">
      {[...Array(8)].map((_, idx) => (
        <div key={idx} className="hover:bg-accent flex w-full items-start p-2">
          <div className="flex w-full items-center gap-2">
            <Skeleton className="size-3" />
            <div className="flex w-full flex-row items-center gap-2">
              <Skeleton className="h-3 w-[30%] lg:w-52" />
              <Skeleton className="h-3 w-[16%] lg:w-28" />
              <Skeleton className="h-3 w-[40%] lg:w-64" />
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
          className={cn(
            'rounded-3xl p-6',
            skeletonCount === 1 ? 'w-full' : 'w-60',
          )}
        >
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-full" />
            </div>
            <Separator />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-4 w-1/4" />
              <Skeleton className="h-4 w-full" />
            </div>
            <Separator />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-4 w-full" />
            </div>
            <Separator />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          </div>
        </div>
      ))}
    </>
  );

  const renderAnalysis = () => (
    <>
      {[...Array(skeletonCount)].map((_, idx) => (
        <div key={idx} className="bg-card w-full animate-pulse rounded-3xl p-6">
          <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-4">
              <div className="bg-muted h-4 w-1/3 rounded-sm"></div>
              <div className="grid grid-cols-6 items-end gap-2">
                <div className="bg-muted h-32 rounded-sm"></div>
                <div className="bg-muted h-24 rounded-sm"></div>
                <div className="bg-muted h-40 rounded-sm"></div>
                <div className="bg-muted h-28 rounded-sm"></div>
                <div className="bg-muted h-36 rounded-sm"></div>
                <div className="bg-muted h-20 rounded-sm"></div>
              </div>
            </div>
            <div className="flex flex-col gap-4">
              <div className="bg-muted h-4 w-1/4 rounded-sm"></div>
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
          className="border-border relative flex h-[197px] w-full max-w-[487px] animate-pulse flex-col overflow-hidden rounded-2xl border"
        >
          <div className="w-full">
            <div className="border-border bg-muted flex w-full items-center justify-between border-b px-4 py-3">
              <div className="bg-muted-foreground/20 h-4 w-20 rounded"></div>
            </div>
            <div className="flex flex-col gap-3 px-4 pt-4 pb-6">
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
        <Card
          key={`source-skel-${idx}`}
          variant="filled"
          padding="lg"
          className="min-h-[130px]"
        >
          <div className="w-full flex-1">
            <div className="flex w-full items-center justify-between gap-2">
              <Skeleton surface="muted" className="h-4 min-w-0 flex-1" />
              <Skeleton surface="muted" className="size-7 shrink-0" />
            </div>
          </div>
          <div className="flex flex-col items-start justify-start gap-1">
            <div className="mt-auto flex flex-col items-start gap-1">
              <div className="flex items-center gap-2">
                <Skeleton surface="muted" className="size-3.5" />
                <Skeleton surface="muted" className="h-3 w-20" />
              </div>
              <div className="flex items-center gap-2">
                <Skeleton surface="muted" className="size-3.5" />
                <Skeleton surface="muted" className="h-3 w-16" />
              </div>
            </div>
          </div>
        </Card>
      ))}
    </>
  );

  const renderAddToolCards = () => (
    <>
      {Array.from({ length: count }).map((_, idx) => (
        <Card
          key={`add-tool-skel-${idx}`}
          variant="outline"
          padding="lg"
          className="h-52 w-full justify-between"
        >
          <div className="w-full">
            <div className="flex w-full items-center justify-between px-1">
              <Skeleton className="size-6" />
            </div>
            <div className="mt-[9px] flex flex-col gap-2 px-1">
              <Skeleton className="h-4 w-2/3" />
              <div className="mt-1 flex flex-col gap-2">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-5/6" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </div>
          </div>
        </Card>
      ))}
    </>
  );

  const renderAgentCards = () => (
    <>
      {Array.from({ length: count }).map((_, idx) => (
        <Card
          key={`agent-skel-${idx}`}
          variant="filled"
          padding="lg"
          className="relative h-44 justify-between"
        >
          <div className="w-full">
            <div className="flex w-full items-center gap-1 px-1">
              <Skeleton surface="muted" className="size-7 rounded-full" />
            </div>
            <div className="mt-2 flex flex-col gap-2 px-1">
              <Skeleton surface="muted" className="h-4 w-2/3" />
              <div className="mt-1 flex flex-col gap-2">
                <Skeleton surface="muted" className="h-3 w-full" />
                <Skeleton surface="muted" className="h-3 w-full" />
                <Skeleton surface="muted" className="h-3 w-3/5" />
              </div>
            </div>
          </div>
        </Card>
      ))}
    </>
  );

  const renderToolCards = () => (
    <>
      {Array.from({ length: count }).map((_, idx) => (
        <Card
          key={`tool-skel-${idx}`}
          variant="filled"
          padding="lg"
          className="relative h-52 justify-between overflow-hidden"
        >
          <div className="w-full">
            <div className="flex w-full items-center gap-2 px-1">
              <Skeleton surface="muted" className="size-6" />
            </div>
            <div className="mt-[9px] flex flex-col gap-2 px-1">
              <Skeleton surface="muted" className="h-4 w-2/3" />
              <div className="mt-1 flex flex-col gap-2">
                <Skeleton surface="muted" className="h-3 w-full" />
                <Skeleton surface="muted" className="h-3 w-5/6" />
                <Skeleton surface="muted" className="h-3 w-full" />
                <Skeleton surface="muted" className="h-3 w-3/4" />
              </div>
            </div>
          </div>
          <Skeleton
            surface="muted"
            className="absolute right-4 bottom-4 h-6 w-11 rounded-full"
          />
        </Card>
      ))}
    </>
  );

  const renderConnectedState = () => (
    <div className="mb-4">
      <div className="bg-muted flex w-full animate-pulse items-center justify-between rounded-lg px-4 py-2">
        <div className="flex items-center gap-2">
          <div className="bg-muted-foreground/20 size-4 rounded"></div>
          <div className="bg-muted-foreground/20 h-4 w-32 rounded"></div>
        </div>
        <div className="bg-muted-foreground/20 h-4 w-16 rounded"></div>
      </div>
    </div>
  );

  const renderFilesSection = () => (
    <div className="border-border rounded-lg border">
      <div className="p-4">
        <div className="mb-4 flex items-center justify-between">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-8 w-24" />
        </div>
        <Skeleton className="h-4 w-40" />
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
    agentCards: renderAgentCards,
    connectedState: renderConnectedState,
    filesSection: renderFilesSection,
  };

  const render = componentMap[component] || componentMap.default;

  // The Spinner this replaces carried role="status"; without it a screen
  // reader gets no signal at all while a section loads. Absolutely
  // positioned by `sr-only`, so it never becomes a flex/grid item.
  return (
    <>
      <span className="sr-only" role="status">
        {t('loading')}
      </span>
      {render()}
    </>
  );
};

export default SkeletonLoader;

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
    | 'chunkCards'
    | 'sourceCards'
    | 'toolCards'
    | 'addToolCards'
    | 'agentCards';
}

const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({
  count = 1,
  component = 'default',
}) => {
  const { t } = useTranslation();
  const { isDesktop } = useMediaQuery();
  // One placeholder beside the desktop shell, at most two below it.
  const skeletonCount = isDesktop ? 1 : Math.min(count, 2);

  // The Spinner this replaces carried role="status"; without it a screen
  // reader gets no signal at all while a section loads. Absolutely
  // positioned by `sr-only`, so it never becomes a flex/grid item.
  const status = (
    <span className="sr-only" role="status">
      {t('loading')}
    </span>
  );

  // Rendered inside a <tbody>, so the status lives in the first cell.
  const renderTable = () => (
    <>
      {[...Array(4)].map((_, idx) => (
        <tr key={idx}>
          <td className="w-[40%] px-4 py-4">
            {idx === 0 && status}
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

  const renderLogs = () => (
    <div className="flex w-full flex-col gap-px">
      {[...Array(8)].map((_, idx) => (
        <div key={idx} className="flex w-full items-start p-2">
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

  // Renders inside a chart panel's 245px chart box: the panel is the Card,
  // so only chart-shaped bars (tallest h-44 plus the x-axis, no wrapper).
  const renderAnalysis = () => (
    <div className="flex h-full flex-col justify-end gap-3">
      <div className="grid grid-cols-8 items-end gap-3">
        <Skeleton className="h-20" />
        <Skeleton className="h-32" />
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
        <Skeleton className="h-28" />
        <Skeleton className="h-36" />
        <Skeleton className="h-16" />
        <Skeleton className="h-44" />
      </div>
      <Skeleton className="h-3 w-full" />
    </div>
  );

  // Mirrors the chunk tile: a filled Card with text lines, then the token
  // count in the footer.
  const renderChunkCards = () => (
    <>
      {Array.from({ length: count }).map((_, index) => (
        <Card
          key={`chunk-skel-${index}`}
          variant="filled"
          padding="lg"
          className="h-50 w-full justify-between"
        >
          <div className="flex flex-col gap-3">
            <Skeleton surface="muted" className="h-3 w-full" />
            <Skeleton surface="muted" className="h-3 w-11/12" />
            <Skeleton surface="muted" className="h-3 w-5/6" />
            <Skeleton surface="muted" className="h-3 w-4/5" />
            <Skeleton surface="muted" className="h-3 w-2/3" />
          </div>
          <Skeleton surface="muted" className="h-3 w-20" />
        </Card>
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

  const componentMap = {
    fileTable: renderTable,
    logs: renderLogs,
    default: renderDefault,
    analysis: renderAnalysis,
    chunkCards: renderChunkCards,
    sourceCards: renderSourceCards,
    toolCards: renderToolCards,
    addToolCards: renderAddToolCards,
    agentCards: renderAgentCards,
  };

  const render = componentMap[component] || componentMap.default;

  if (component === 'fileTable') return render();

  return (
    <>
      {status}
      {render()}
    </>
  );
};

export default SkeletonLoader;

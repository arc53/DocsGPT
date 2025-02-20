import { useState, useEffect } from 'react';

interface SkeletonLoaderProps {
  count?: number;
  component?:
    | 'default'
    | 'analysis'
    | 'logs'
    | 'table'
    | 'chatbot'
    | 'dropdown';
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
          <td className="py-4 px-4 w-[45%]">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full"></div>
          </td>
          <td className="py-4 px-4 w-[20%]">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full"></div>
          </td>
          <td className="py-4 px-4 w-[25%]">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full"></div>
          </td>
          <td className="py-4 px-4 w-[10%]">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full"></div>
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
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-3/4 mx-auto"></div>
          </td>
          <td className="p-2">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full mx-auto"></div>
          </td>
          <td className="p-2">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full mx-auto"></div>
          </td>
          <td className="p-2">
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-8 mx-auto"></div>
          </td>
        </tr>
      ))}
    </>
  );

  const renderDropdown = () => (
    <div className="animate-pulse">
      <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-24 mb-2"></div>
      <div className="w-[360px] h-14 bg-gray-300 dark:bg-gray-600 rounded-3xl flex items-center justify-between px-4">
        <div className="h-3 bg-gray-400 dark:bg-gray-700 rounded w-24"></div>
        <div className="h-3 w-3 bg-gray-400 dark:bg-gray-700 rounded"></div>
      </div>
    </div>
  );

  const renderLogs = () => (
    <div className="w-full animate-pulse space-y-px">
      {[...Array(8)].map((_, idx) => (
        <div
          key={idx}
          className="w-full flex items-start p-2 hover:bg-[#F9F9F9] hover:dark:bg-dark-charcoal"
        >
          <div className="w-full flex items-center gap-2">
            <div className="w-3 h-3 bg-gray-300 dark:bg-gray-600 rounded-lg"></div>
            <div className="w-full flex flex-row items-center gap-2">
              <div className="h-3 bg-gray-300 dark:bg-gray-600 rounded-lg w-[30%] lg:w-52"></div>
              <div className="h-3 bg-gray-300 dark:bg-gray-600 rounded-lg w-[16%] lg:w-28"></div>
              <div className="h-3 bg-gray-300 dark:bg-gray-600 rounded-lg w-[40%] lg:w-64"></div>
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
          } dark:bg-raisin-black rounded-3xl animate-pulse`}
        >
          <div className="space-y-4">
            <div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-3/4"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-5/6"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-1/2"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-3/4"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-full"></div>
            </div>
            <div className="border-t border-gray-400 dark:border-gray-700 my-4"></div>
            <div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-2/3"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-1/4"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-full"></div>
            </div>
            <div className="border-t border-gray-400 dark:border-gray-700 my-4"></div>
            <div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-5/6"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-1/3"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-2/3"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded mb-2 w-full"></div>
            </div>
            <div className="border-t border-gray-400 dark:border-gray-700 my-4"></div>
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-3/4 mb-2"></div>
            <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-5/6 mb-2"></div>
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
          className="p-6 w-full dark:bg-raisin-black rounded-3xl animate-pulse"
        >
          <div className="space-y-6">
            <div className="space-y-2">
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-1/3 mb-4"></div>
              <div className="grid grid-cols-6 gap-2 items-end">
                <div className="h-32 bg-gray-300 dark:bg-gray-600 rounded"></div>
                <div className="h-24 bg-gray-300 dark:bg-gray-600 rounded"></div>
                <div className="h-40 bg-gray-300 dark:bg-gray-600 rounded"></div>
                <div className="h-28 bg-gray-300 dark:bg-gray-600 rounded"></div>
                <div className="h-36 bg-gray-300 dark:bg-gray-600 rounded"></div>
                <div className="h-20 bg-gray-300 dark:bg-gray-600 rounded"></div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-1/4 mb-4"></div>
              <div className="h-32 bg-gray-300 dark:bg-gray-600 rounded"></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full"></div>
              <div className="h-4 bg-gray-300 dark:bg-gray-600 rounded w-full"></div>
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
  };

  const render = componentMap[component] || componentMap.default;

  return <>{render()}</>;
};

export default SkeletonLoader;

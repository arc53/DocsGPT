import React, { useState, useEffect } from 'react';

interface SkeletonLoaderProps {
  count?: number;
  component?: 'default' | 'analysis' | 'chatbot' | 'logs';
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

  return (
    <div className="flex flex-col space-y-4">
      {component === 'default'
        ? [...Array(skeletonCount)].map((_, idx) => (
            <div
              key={idx}
              className={`p-6 ${skeletonCount === 1 ? 'w-full' : 'w-60'} dark:bg-raisin-black rounded-3xl animate-pulse`}
            >
              <div className="space-y-4">
                <div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-3/4"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-5/6"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-1/2"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-3/4"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-full"></div>
                </div>
                <div className="border-t border-gray-600 my-4"></div>
                <div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-2/3"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-1/4"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-full"></div>
                </div>
                <div className="border-t border-gray-600 my-4"></div>
                <div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-5/6"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-1/3"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-2/3"></div>
                  <div className="h-4 bg-gray-600 rounded mb-2 w-full"></div>
                </div>
                <div className="border-t border-gray-600 my-4"></div>
                <div className="h-4 bg-gray-600 rounded w-3/4 mb-2"></div>
                <div className="h-4 bg-gray-600 rounded w-5/6 mb-2"></div>
              </div>
            </div>
          ))
        : component === 'analysis'
          ? [...Array(skeletonCount)].map((_, idx) => (
              <div
                key={idx}
                className="p-6 w-full dark:bg-raisin-black rounded-3xl animate-pulse"
              >
                <div className="space-y-6">
                  <div className="space-y-2">
                    <div className="h-4 bg-gray-600 rounded w-1/3 mb-4"></div>
                    <div className="grid grid-cols-6 gap-2 items-end">
                      <div className="h-32 bg-gray-600 rounded"></div>
                      <div className="h-24 bg-gray-600 rounded"></div>
                      <div className="h-40 bg-gray-600 rounded"></div>
                      <div className="h-28 bg-gray-600 rounded"></div>
                      <div className="h-36 bg-gray-600 rounded"></div>
                      <div className="h-20 bg-gray-600 rounded"></div>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="h-4 bg-gray-600 rounded w-1/4 mb-4"></div>
                    <div className="h-32 bg-gray-600 rounded"></div>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="h-4 bg-gray-600 rounded w-full"></div>
                    <div className="h-4 bg-gray-600 rounded w-full"></div>
                  </div>
                </div>
              </div>
            ))
          : component === 'chatbot'
            ? [...Array(skeletonCount)].map((_, idx) => (
                <div
                  key={idx}
                  className="p-4 w-full max-w-sm mx-auto animate-pulse"
                >
                  <div className="flex items-start space-x-2">
                    <div className="w-8 h-8 bg-gray-600 rounded-full"></div>
                    <div className="flex-1 space-y-2">
                      <div className="p-3 rounded-lg bg-gray-600">
                        <div className="h-4 bg-gray-500 rounded w-3/4 mb-2"></div>
                        <div className="h-4 bg-gray-500 rounded w-2/4"></div>
                      </div>
                      <div className="p-3 rounded-lg bg-gray-600">
                        <div className="h-4 bg-gray-500 rounded w-5/6 mb-2"></div>
                        <div className="h-4 bg-gray-500 rounded w-3/4"></div>
                      </div>
                      <div className="flex space-x-1">
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                      </div>
                    </div>
                  </div>
                </div>
              ))
            : [...Array(skeletonCount)].map((_, idx) => (
                <div
                  key={idx}
                  className="p-6 w-full dark:bg-raisin-black rounded-3xl animate-pulse"
                >
                  <div className="space-y-4">
                    <div className="h-4 bg-gray-600 rounded w-1/2"></div>
                    <div className="h-4 bg-gray-600 rounded w-5/6"></div>
                    <div className="h-4 bg-gray-600 rounded w-3/4"></div>
                    <div className="h-4 bg-gray-600 rounded w-2/3"></div>
                    <div className="h-4 bg-gray-600 rounded w-1/4"></div>
                  </div>
                </div>
              ))}
    </div>
  );
};

export default SkeletonLoader;

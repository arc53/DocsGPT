import React, { useState, useEffect } from 'react';

interface SkeletonLoaderProps {
  count?: number;
}

const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({ count = 1 }) => {
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
      {[...Array(skeletonCount)].map((_, idx) => (
        <div
          key={idx}
          className={`p-6 ${skeletonCount === 1 ? 'w-full' : 'w-60'} bg-gray-800 rounded-3xl animate-pulse`}
        >
          <div className="space-y-4">
            <div>
              <div className="h-4 bg-gray-500 rounded mb-2 w-3/4"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-5/6"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-1/2"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-3/4"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-full"></div>{' '}
            </div>
            <div className="border-t border-gray-600 my-4"></div>{' '}
            <div>
              <div className="h-4 bg-gray-500 rounded mb-2 w-2/3"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-1/4"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-full"></div>{' '}
            </div>
            <div className="border-t border-gray-600 my-4"></div>{' '}
            <div>
              <div className="h-4 bg-gray-500 rounded mb-2 w-5/6"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-1/3"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-2/3"></div>{' '}
              <div className="h-4 bg-gray-500 rounded mb-2 w-full"></div>{' '}
            </div>
            <div className="border-t border-gray-600 my-4"></div>{' '}
            <div className="h-4 bg-gray-500 rounded w-3/4 mb-2"></div>{' '}
            <div className="h-4 bg-gray-500 rounded w-5/6 mb-2"></div>{' '}
          </div>
        </div>
      ))}
    </div>
  );
};

export default SkeletonLoader;

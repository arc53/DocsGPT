import React from 'react';

interface SkeletonLoaderProps {
  count?: number; // Optional prop to define the number of skeleton loaders
}

const SkeletonLoader: React.FC<SkeletonLoaderProps> = ({ count = 1 }) => {
  return (
    <div className="flex space-x-4">
      {[...Array(count)].map((_, idx) => (
        <div
          key={idx}
          className="p-6 w-60 h-32 bg-gray-800 rounded-3xl animate-pulse"
        >
          <div className="space-y-4">
            <div className="w-3/4 h-4 bg-gray-500 rounded"></div>
            <div className="w-full h-4 bg-gray-500 rounded"></div>
            <div className="w-5/6 h-4 bg-gray-500 rounded"></div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default SkeletonLoader;

// calling function should be pass --- no. of sketeton cards
// eg .   ----------->>>    <SkeletonLoader count={4}   />

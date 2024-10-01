import React from 'react';

const Loader: React.FC = () => {
  return (
    <div className="flex justify-center items-center min-h-screen bg-gray-900">
      <div className="relative w-20 h-20">
        <div className="absolute top-0 left-0 w-16 h-16 border-t-4 border-blue-500 rounded-full animate-spin"></div>
        <div className="absolute top-0 left-0 w-16 h-16 border-t-4 border-pink-500 rounded-full animate-spin delay-150"></div>
        <div className="absolute top-0 left-0 w-16 h-16 border-t-4 border-green-500 rounded-full animate-spin delay-300"></div>
      </div>
    </div>
  );
};

export default Loader;

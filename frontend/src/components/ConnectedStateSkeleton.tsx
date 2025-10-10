const ConnectedStateSkeleton = () => (
  <div className="mb-4">
    <div className="flex w-full animate-pulse items-center justify-between rounded-[10px] bg-gray-200 px-4 py-2 dark:bg-gray-700">
      <div className="flex items-center gap-2">
        <div className="h-4 w-4 rounded bg-gray-300 dark:bg-gray-600"></div>
        <div className="h-4 w-32 rounded bg-gray-300 dark:bg-gray-600"></div>
      </div>
      <div className="h-4 w-16 rounded bg-gray-300 dark:bg-gray-600"></div>
    </div>
  </div>
);

export default ConnectedStateSkeleton;

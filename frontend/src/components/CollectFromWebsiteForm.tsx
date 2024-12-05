import React, { useState } from 'react';
import { FiLoader } from 'react-icons/fi';

const CollectFromWebsiteForm: React.FC = () => {
  const [isFetching, setIsFetching] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    link: '',
  });
  const [selectedOption, setSelectedOption] = useState('From URL');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData({
      ...formData,
      [name]: value,
    });
  };

  const handleLinkPaste = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { value } = e.target;
    setFormData({
      ...formData,
      link: value,
    });

    // Simulate fetching animation for link paste
    setIsFetching(true);
    setTimeout(() => {
      setIsFetching(false);
      // Handle link fetching logic here (API call, etc.)
    }, 2000);
  };

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedOption(e.target.value);
  };

  return (
    <div className="bg-white dark:bg-gray-800 p-8 rounded-xl shadow-xl w-full max-w-md lg:max-w-lg 2xl:max-w-xl mx-auto opacity-0 animate-fadeInSlideUp">
      <h2 className="text-gray-700 dark:text-gray-200 text-xl font-semibold mb-6">
        Collect from a website
      </h2>

      <div className="space-y-6">
        {/* Custom styled dropdown */}
        <div className="relative">
          <select
            value={selectedOption}
            onChange={handleSelectChange}
            className="w-full appearance-none bg-transparent border border-gray-200 dark:border-gray-600 rounded-full px-4 py-3 text-gray-600 dark:text-gray-300 focus:outline-none focus:border-blue-500 dark:focus:border-blue-400"
          >
            <option value="From URL" className="dark:bg-gray-800">
              From URL
            </option>
            <option value="From API" className="dark:bg-gray-800">
              From API
            </option>
            <option value="From HTML" className="dark:bg-gray-800">
              From HTML
            </option>
          </select>
          {/* Custom dropdown arrow */}
          <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none">
            <svg
              className="w-4 h-4 text-gray-400"
              fill="none"
              strokeWidth="2"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>

        {/* Name input */}
        <div className="relative">
          <label className="absolute -top-2.5 left-4 bg-white dark:bg-gray-800 px-1 text-xs text-gray-500 dark:text-gray-400">
            Name
          </label>
          <input
            type="text"
            name="name"
            value={formData.name}
            onChange={handleChange}
            placeholder="Enter name"
            className="w-full px-4 py-3 rounded-full border border-gray-200 dark:border-gray-600 focus:outline-none focus:border-blue-500 dark:focus:border-blue-400 bg-transparent text-gray-700 dark:text-gray-300 placeholder-gray-400 dark:placeholder-gray-500"
          />
        </div>

        {/* Link input */}
        <div className="relative">
          <label className="absolute -top-2.5 left-4 bg-white dark:bg-gray-800 px-1 text-xs text-gray-500 dark:text-gray-400">
            Link
          </label>
          <input
            type="text"
            name="link"
            value={formData.link}
            onChange={handleLinkPaste}
            placeholder="URL Link"
            className="w-full px-4 py-3 rounded-full border border-gray-200 dark:border-gray-600 focus:outline-none focus:border-blue-500 dark:focus:border-blue-400 bg-transparent text-gray-700 dark:text-gray-300 placeholder-gray-400 dark:placeholder-gray-500"
          />
        </div>

        {/* Fetching status */}
        {/* Fetching status */}
        <div className="flex items-center justify-end space-x-2">
          <div className="flex items-center gap-3">
            {isFetching ? (
              <>
                <span className="text-gray-500 dark:text-gray-400 text-md">
                  Fetching
                </span>
                <div className="w-6 h-6 border-2 border-gray-500 border-t-transparent rounded-full animate-spin"></div>
              </>
            ) : (
              <>
                <span className="invisible text-md">Fetching</span>
                <FiLoader className="invisible w-4 h-4" />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default CollectFromWebsiteForm;

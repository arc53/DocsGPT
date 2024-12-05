import { useState } from 'react';

interface UploadFromDeviceForm {
  language: string;
  level: number;
  selectedCard: number | null;
  isLoading: boolean;
  progress: number;
  isFinalPage: boolean;
}

export default function UploadFromDeviceForm() {
  const [uploadedFiles, setUploadedFiles] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files ? e.target.files[0] : null;
    if (file && file.size <= 25 * 1024 * 1024) {
      setIsLoading(true);
      await new Promise((resolve) => setTimeout(resolve, 2000));
      setUploadedFiles([...uploadedFiles, file.name]);
      setIsLoading(false);
    } else {
      alert('File size exceeds 25MB or invalid file format');
    }
  };

  return (
    <div className="flex flex-col items-start bg-white dark:bg-gray-800 p-8 rounded-2xl shadow-lg w-full max-w-lg mx-auto opacity-0 animate-fadeInSlideUp">
      <h1 className="font-semibold text-2xl text-gray-900 dark:text-white mb-8">
        Upload from device
      </h1>
      <div className="flex - flex-col items-start gap-4">
        {/* Name Input with better styling */}
        <div className="w-full relative">
          <label className="absolute -top-2.5 left-4 px-1 text-sm text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-800">
            Name
          </label>
          <input
            type="text"
            className="w-full px-4 py-3 border-2 border-gray-200 dark:border-gray-600 rounded-full bg-transparent text-gray-700 dark:text-gray-300 focus:outline-none focus:border-purple-500 dark:focus:border-purple-400"
            placeholder="Enter name"
          />
        </div>

        {/* File Upload Button */}
        <div>
          <label className="w-full mb-3">
            <input
              type="file"
              className="hidden"
              accept=".pdf,.txt,.rst,.docx,.md,.zip"
              onChange={handleFileUpload}
            />
            <div className="w-fit mx-auto px-8 py-2.5 bg-white dark:bg-transparent border-2 border-purple-500 dark:border-purple-400 text-purple-600 dark:text-purple-400 font-medium rounded-full cursor-pointer hover:bg-purple-50 dark:hover:bg-purple-900/20 transition-colors">
              Choose file
            </div>
          </label>
        </div>

        {/* File type information */}
        <div>
          <p className="text-gray-500 dark:text-gray-400 text-sm text-center italic ml-3">
            Please upload .pdf, .txt, .rst, .docx, .md, .zip limited to 25mb
          </p>
        </div>
      </div>

      {/* Uploaded Files Section */}
      <div className="w-full mt-8">
        <div className="flex justify-between items-center mb-2">
          <h3 className="font-medium text-gray-900 dark:text-white">
            Uploaded Files
          </h3>
          <div className="flex items-center gap-3">
            {isLoading ? (
              <>
                <span className="text-gray-500 dark:text-gray-400 text-md">
                  Fetching
                </span>
                <div className="w-6 h-6  border-2 border-gray-500 border-t-transparent rounded-full animate-spin"></div>
              </>
            ) : (
              <>
                <span className="invisible text-md">Fetching</span>
                <div className="w-6 h-6 invisible"></div>
              </>
            )}
          </div>
        </div>

        {!isLoading && uploadedFiles.length === 0 ? (
          <p className="text-gray-500 dark:text-gray-400">None</p>
        ) : (
          <ul className="space-y-2">
            {uploadedFiles.map((file, index) => (
              <li key={index} className="text-gray-700 dark:text-gray-300">
                {file}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

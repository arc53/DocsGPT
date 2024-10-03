import { useState } from 'react';
import { FaEnvelope, FaQuestionCircle } from 'react-icons/fa'; // Import icons for dropdown

export default function HelpMenu() {
  const [isOpen, setIsOpen] = useState(false);

  const toggleDropdown = () => {
    setIsOpen(!isOpen);
  };

  return (
    <div className="mx-5 grid min-h-screen md:mx-36">
      <div className="relative">
        <button
          onClick={toggleDropdown}
          className="flex items-center text-xl text-blue-500 hover:text-blue-700"
        >
          <FaQuestionCircle className="mr-2" /> Help
        </button>

        {isOpen && (
          <div className="absolute mt-2 w-48 rounded-md shadow-lg bg-white dark:bg-gray-800 z-10">
            <ul className="py-1">
              <li>
                <a
                  href="mailto:contact@arc53.com"
                  className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  <FaEnvelope className="mr-2 inline-block" />
                  Email Us
                </a>
              </li>
              <li>
                <a
                  href="https://docs.docsgpt.cloud/"
                  target="_blank"
                  rel="noreferrer"
                  className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  Documentation
                </a>
              </li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

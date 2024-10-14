import React, { useState, useRef, useEffect } from 'react';
import InfoDark from '../assets/info-dark.svg';
import PageIcon from '../assets/documentation.svg'; // Ensure this path is correct
import EmailIcon from '../assets/envelope.svg'; // Replace with your actual email icon path

const Help = () => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const toggleDropdown = () => {
    setIsOpen((prev) => !prev);
  };

  const handleClickOutside = (event: MouseEvent) => {
    if (
      dropdownRef.current &&
      !dropdownRef.current.contains(event.target as Node) &&
      buttonRef.current &&
      !buttonRef.current.contains(event.target as Node)
    ) {
      setIsOpen(false);
    }
  };

  useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const dropdownPosition = () => {
    if (!buttonRef.current) return { top: '100%', left: '0' };

    const rect = buttonRef.current.getBoundingClientRect();
    const dropdownHeight = 80; // Adjust based on the content height
    const spaceBelow = window.innerHeight - rect.bottom;

    const dropdownWidth = 192; // Adjust to fit your design
    const spaceRight = window.innerWidth - rect.right;

    let leftPosition = 0; // Default to align with the button

    if (spaceRight < dropdownWidth) {
      leftPosition = dropdownWidth - rect.width;
    }

    if (spaceBelow >= dropdownHeight) {
      return { top: '100%', left: `${leftPosition}px` }; // Open downward
    } else {
      return { top: `${-dropdownHeight}px`, left: `${leftPosition}px` }; // Open upward
    }
  };

  return (
    <div className="relative inline-block" ref={dropdownRef}>
      <button
        ref={buttonRef}
        onClick={toggleDropdown}
        className="flex items-center rounded-full hover:bg-gray-100 dark:hover:bg-[#28292E] px-3 py-1"
      >
        <img
          src={InfoDark}
          alt="icon"
          className="m-2 w-6 self-center text-sm filter dark:invert"
        />
        Help
      </button>
      {isOpen && (
        <div
          className={`absolute mt-2 w-48 shadow-lg bg-white dark:bg-gray-800`}
          style={{ ...dropdownPosition(), borderRadius: '0.5rem' }}
        >
          <a
            href="https://docs.docsgpt.cloud/"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center px-4 py-2 text-black dark:text-white hover:bg-gray-200 dark:hover:bg-gray-700"
          >
            <img src={PageIcon} alt="Documentation" className="mr-2 w-4 h-4" />
            Documentation
          </a>
          <a
            href="mailto:contact@arc53.com"
            className="flex items-center px-4 py-2 text-black dark:text-white hover:bg-gray-200 dark:hover:bg-gray-700"
          >
            <img src={EmailIcon} alt="Email Us" className="mr-2 w-4 h-4" />
            Email Us
          </a>
        </div>
      )}
    </div>
  );
};

export default Help;

import React, { useState } from 'react';
import SingleArrowLeft from '../assets/single-left-arrow.svg';
import SingleArrowRight from '../assets/single-right-arrow.svg';
import DoubleArrowLeft from '../assets/double-arrow-left.svg';
import DoubleArrowRight from '../assets/double-arrow-right.svg';

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  rowsPerPage: number;
  onPageChange: (page: number) => void;
  onRowsPerPageChange: (rows: number) => void;
}

const Pagination: React.FC<PaginationProps> = ({
  currentPage,
  totalPages,
  rowsPerPage,
  onPageChange,
  onRowsPerPageChange,
}) => {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const rowsPerPageOptions = [5, 10, 20, 50];

  const toggleDropdown = () => setIsDropdownOpen((prev) => !prev);

  const handlePreviousPage = () => {
    if (currentPage > 1) {
      onPageChange(currentPage - 1);
    }
  };

  const handleNextPage = () => {
    if (currentPage < totalPages) {
      onPageChange(currentPage + 1);
    }
  };

  const handleFirstPage = () => {
    onPageChange(1);
  };

  const handleLastPage = () => {
    onPageChange(totalPages);
  };

  const handleSelectRowsPerPage = (rows: number) => {
    setIsDropdownOpen(false);
    onRowsPerPageChange(rows);
  };

  return (
    <div className="flex items-center text-xs justify-end gap-4 mt-2 p-2 border-gray-200">
      {/* Rows per page dropdown */}
      <div className="flex items-center gap-2 relative">
        <span className="text-gray-900 dark:text-gray-50">Rows per page:</span>
        <div className="relative">
          <button
            onClick={toggleDropdown}
            className="px-3 py-1 border rounded dark:bg-dark-charcoal dark:text-light-gray hover:bg-gray-200 dark:hover:bg-neutral-700"
          >
            {rowsPerPage}
          </button>
          <div
            className={`absolute z-50 right-0 mt-1 w-28 transform  bg-white shadow-lg ring-1 ring-black ring-opacity-5 transition-all duration-200 ease-in-out ${
              isDropdownOpen
                ? 'scale-100 opacity-100 visible'
                : 'scale-95 opacity-0 invisible'
            }`}
          >
            {rowsPerPageOptions.map((option) => (
              <div
                key={option}
                onClick={() => handleSelectRowsPerPage(option)}
                className={`cursor-pointer px-4 py-2 text-xs hover:bg-gray-100 dark:hover:bg-neutral-700 ${
                  rowsPerPage === option
                    ? 'bg-gray-100 dark:bg-neutral-700 dark:text-light-gray'
                    : 'bg-white dark:bg-dark-charcoal dark:text-light-gray'
                }`}
              >
                {option}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Pagination controls */}
      <div className="text-gray-900 dark:text-gray-50">
        Page {currentPage} of {totalPages}
      </div>
      <div className="flex items-center gap-2 text-gray-900 dark:text-gray-50">
        <button
          onClick={handleFirstPage}
          disabled={currentPage === 1}
          className="px-2 py-1 border rounded disabled:opacity-50"
        >
          <img
            src={DoubleArrowLeft}
            alt="First page"
            className="dark:invert dark:sepia dark:brightness-200"
          />
        </button>
        <button
          onClick={handlePreviousPage}
          disabled={currentPage === 1}
          className="px-2 py-1 border rounded disabled:opacity-50"
        >
          <img
            src={SingleArrowLeft}
            alt="Previous page"
            className="dark:invert dark:sepia dark:brightness-200"
          />
        </button>
        <button
          onClick={handleNextPage}
          disabled={currentPage === totalPages}
          className="px-2 py-1 border rounded disabled:opacity-50"
        >
          <img
            src={SingleArrowRight}
            alt="Next page"
            className="dark:invert dark:sepia dark:brightness-200"
          />
        </button>
        <button
          onClick={handleLastPage}
          disabled={currentPage === totalPages}
          className="px-2 py-1 border rounded disabled:opacity-50"
        >
          <img
            src={DoubleArrowRight}
            alt="Last page"
            className="dark:invert dark:sepia dark:brightness-200"
          />
        </button>
      </div>
    </div>
  );
};

export default Pagination;

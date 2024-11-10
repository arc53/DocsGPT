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
  const [rowsPerPageOptions] = useState([5, 10, 15, 20]);

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

  return (
    <div className="flex items-center text-xs justify-end gap-4 mt-2 p-2 border-gray-200">
      <div className="flex items-center gap-2 ">
        <span className="text-gray-900 dark:text-gray-50">Rows per page:</span>
        <select
          value={rowsPerPage}
          onChange={(e) => onRowsPerPageChange(Number(e.target.value))}
          className="border border-gray-300 rounded px-2 py-1 dark:bg-dark-charcoal dark:text-gray-50"
        >
          {rowsPerPageOptions.map((option) => (
            <option
              className="bg-white dark:bg-dark-charcoal dark:text-gray-50"
              key={option}
              value={option}
            >
              {option}
            </option>
          ))}
        </select>
      </div>

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
            alt="arrow"
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
            alt="arrow"
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
            alt="arrow"
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
            alt="arrow"
            className="dark:invert dark:sepia dark:brightness-200"
          />
        </button>
      </div>
    </div>
  );
};

export default Pagination;

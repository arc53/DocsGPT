import React from 'react';
import { useTranslation } from 'react-i18next';
import SingleArrowLeft from '../assets/single-left-arrow.svg';
import SingleArrowRight from '../assets/single-right-arrow.svg';
import DoubleArrowLeft from '../assets/double-arrow-left.svg';
import DoubleArrowRight from '../assets/double-arrow-right.svg';
import { Button } from './ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';

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
  const { t } = useTranslation();
  const rowsPerPageOptions = [5, 10, 20, 50];

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
    onRowsPerPageChange(rows);
  };

  return (
    <div className="mt-2 flex items-center justify-end gap-4 p-2 text-xs">
      {/* Rows per page dropdown */}
      <div className="relative flex items-center gap-2">
        <span className="text-foreground">{t('pagination.rowsPerPage')}:</span>
        <Select
          value={String(rowsPerPage)}
          onValueChange={(value) => handleSelectRowsPerPage(Number(value))}
        >
          <SelectTrigger size="sm" aria-label={t('pagination.rowsPerPage')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {rowsPerPageOptions.map((option) => (
              <SelectItem key={option} value={String(option)}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Pagination controls */}
      <div className="text-foreground">
        {t('pagination.pageOf', { currentPage, totalPages })}
      </div>
      <div className="text-foreground flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          onClick={handleFirstPage}
          disabled={currentPage === 1}
        >
          <img
            src={DoubleArrowLeft}
            alt={t('pagination.firstPage')}
            className="dark:brightness-200 dark:invert dark:sepia"
          />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          onClick={handlePreviousPage}
          disabled={currentPage === 1}
        >
          <img
            src={SingleArrowLeft}
            alt={t('pagination.previousPage')}
            className="dark:brightness-200 dark:invert dark:sepia"
          />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          onClick={handleNextPage}
          disabled={currentPage === totalPages}
        >
          <img
            src={SingleArrowRight}
            alt={t('pagination.nextPage')}
            className="dark:brightness-200 dark:invert dark:sepia"
          />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          onClick={handleLastPage}
          disabled={currentPage === totalPages}
        >
          <img
            src={DoubleArrowRight}
            alt={t('pagination.lastPage')}
            className="dark:brightness-200 dark:invert dark:sepia"
          />
        </Button>
      </div>
    </div>
  );
};

export default Pagination;

import React, { useState, useEffect, useRef } from 'react';
import { useSelector } from 'react-redux';
import { useTranslation } from 'react-i18next';
import { selectToken } from '../preferences/preferenceSlice';
import { useDarkTheme, useLoaderState, useMediaQuery } from '../hooks';
import userService from '../api/services/userService';
import { ActiveState } from '../models/misc';
import { ChunkType } from '../settings/types';

// ✅ LineNumberedTextarea Component
interface LineNumberedTextareaProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  editable?: boolean;
  onDoubleClick?: () => void;
}

const LineNumberedTextarea: React.FC<LineNumberedTextareaProps> = ({
  value,
  onChange,
  placeholder,
  ariaLabel,
  className = '',
  editable = true,
  onDoubleClick,
}) => {
  const { isMobile } = useMediaQuery();

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value);
  };

  const lineHeight = 19.93;
  const contentLines = value.split('\n').length;
  const heightOffset = isMobile ? 200 : 300;
  const minLinesForDisplay = Math.ceil(
    (typeof window !== 'undefined' ? window.innerHeight - heightOffset : 600) /
      lineHeight,
  );
  const totalLines = Math.max(contentLines, minLinesForDisplay);

  return (
    <div className={`relative w-full ${className}`}>
      <div
        className="pointer-events-none absolute top-0 left-0 w-8 pr-2 text-right font-mono text-xs leading-[19.93px] text-gray-500 select-none lg:w-12 lg:pr-3 lg:text-sm dark:text-gray-400"
        style={{
          height: `${totalLines * lineHeight}px`,
        }}
      >
        {Array.from({ length: totalLines }, (_, i) => (
          <div
            key={i + 1}
            className="flex h-[19.93px] items-center justify-end leading-[19.93px]"
          >
            {i + 1}
          </div>
        ))}
      </div>
      <textarea
        className={`w-full resize-none overflow-hidden border-none bg-transparent pl-8 font-['Inter'] text-[13.68px] leading-[19.93px] text-[#18181B] outline-none lg:pl-12 dark:text-white ${
          isMobile ? 'min-h-[calc(100vh-200px)]' : 'min-h-[calc(100vh-300px)]'
        } ${!editable ? 'select-none' : ''}`}
        value={value}
        onChange={editable ? handleChange : undefined}
        onDoubleClick={onDoubleClick}
        placeholder={placeholder}
        aria-label={ariaLabel}
        rows={totalLines}
        readOnly={!editable}
        style={{
          height: `${totalLines * lineHeight}px`,
        }}
      />
    </div>
  );
};

// ✅ Main Chunks Component
interface SearchResult {
  path: string;
  isFile: boolean;
}

interface ChunksProps {
  documentId: string;
  documentName?: string;
  handleGoBack: () => void;
  path?: string;
  onFileSearch?: (query: string) => SearchResult[];
  onFileSelect?: (path: string) => void;
}

const Chunks: React.FC<ChunksProps> = ({
  documentId,
  documentName,
  handleGoBack,
  path,
  onFileSearch,
  onFileSelect,
}) => {
  const [fileSearchQuery, setFileSearchQuery] = useState('');
  const [fileSearchResults, setFileSearchResults] = useState<SearchResult[]>(
    [],
  );
  const searchDropdownRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const [paginatedChunks, setPaginatedChunks] = useState<ChunkType[]>([]);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(5);
  const [totalChunks, setTotalChunks] = useState(0);
  const [loading, setLoading] = useLoaderState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [editingChunk, setEditingChunk] = useState<ChunkType | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [editingText, setEditingText] = useState('');
  const [isAddingChunk, setIsAddingChunk] = useState(false);
  const [deleteModalState, setDeleteModalState] =
    useState<ActiveState>('INACTIVE');
  const [chunkToDelete, setChunkToDelete] = useState<ChunkType | null>(null);
  const [isEditing, setIsEditing] = useState(false);

  const pathParts = path ? path.split('/') : [];

  // 🧠 Fetch chunks data
  const fetchChunks = async () => {
    setLoading(true);
    try {
      const response = await userService.getDocumentChunks(
        documentId,
        page,
        perPage,
        token,
        path,
        searchTerm,
      );
      if (!response.ok) throw new Error('Failed to fetch chunks');
      const data = await response.json();
      setPage(data.page);
      setPerPage(data.per_page);
      setTotalChunks(data.total);
      setPaginatedChunks(data.chunks);
    } catch (error) {
      console.error(error);
      setPaginatedChunks([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChunks();
  }, [page, perPage, path, searchTerm]);

  return (
    <div className="flex flex-col">
      {/* Render content here */}
      <h2 className="mb-4 text-lg font-semibold text-purple-500">
        {documentName || 'Document Chunks'}
      </h2>

      {loading ? (
        <p>Loading chunks...</p>
      ) : paginatedChunks.length === 0 ? (
        <p>No chunks found.</p>
      ) : (
        <div className="grid gap-3">
          {paginatedChunks.map((chunk, idx) => (
            <div
              key={idx}
              className="rounded-lg border p-3 shadow-sm transition hover:shadow-md"
            >
              <p className="text-sm text-gray-700 dark:text-gray-200">
                {chunk.text}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default Chunks;

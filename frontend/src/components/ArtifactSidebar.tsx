import React, { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import Exit from '../assets/exit.svg';
import { selectToken } from '../preferences/preferenceSlice';
import userService from '../api/services/userService';
import Spinner from './Spinner';

type TodoItem = {
  todo_id: number;
  title: string;
  status: 'open' | 'completed';
  created_at: string | null;
  updated_at: string | null;
};

type TodoArtifactData = {
  items: TodoItem[];
  total_count: number;
  open_count: number;
  completed_count: number;
};

type NoteArtifactData = {
  content: string;
  line_count: number;
  updated_at: string | null;
};

type ArtifactData =
  | { artifact_type: 'todo_list'; data: TodoArtifactData }
  | { artifact_type: 'note'; data: NoteArtifactData }
  | { artifact_type: 'memory'; data: Record<string, unknown> };

type ArtifactSidebarProps = {
  isOpen: boolean;
  onClose: () => void;
  artifactId: string | null;
  toolName?: string;
};

function TodoListView({ data }: { data: TodoArtifactData }) {
  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold dark:text-white">Todo List</h3>
        <div className="flex gap-2 text-xs">
          <span className="rounded-full bg-green-100 px-2 py-1 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            {data.completed_count} done
          </span>
          <span className="rounded-full bg-blue-100 px-2 py-1 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
            {data.open_count} open
          </span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {data.items.length === 0 ? (
          <p className="text-center text-sm text-gray-500 dark:text-gray-400">
            No todos yet
          </p>
        ) : (
          <ul className="space-y-2">
            {data.items.map((item) => (
              <li
                key={item.todo_id}
                className={`flex items-start gap-3 rounded-lg border p-3 ${
                  item.status === 'completed'
                    ? 'border-green-200 bg-green-50 dark:border-green-900/50 dark:bg-green-900/20'
                    : 'border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800'
                }`}
              >
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 ${
                    item.status === 'completed'
                      ? 'border-green-500 bg-green-500 text-white'
                      : 'border-gray-300 dark:border-gray-600'
                  }`}
                >
                  {item.status === 'completed' && (
                    <svg
                      className="h-3 w-3"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={3}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  )}
                </span>
                <div className="flex-1">
                  <p
                    className={`text-sm ${
                      item.status === 'completed'
                        ? 'text-gray-500 line-through dark:text-gray-400'
                        : 'text-gray-900 dark:text-white'
                    }`}
                  >
                    {item.title}
                  </p>
                  <p className="mt-1 text-xs text-gray-400">#{item.todo_id}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function NoteView({ data }: { data: NoteArtifactData }) {
  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold dark:text-white">Note</h3>
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {data.line_count} lines
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        <pre className="whitespace-pre-wrap rounded-lg bg-gray-50 p-4 font-mono text-sm text-gray-800 dark:bg-gray-800 dark:text-gray-200">
          {data.content || 'Empty note'}
        </pre>
      </div>
    </div>
  );
}

export default function ArtifactSidebar({
  isOpen,
  onClose,
  artifactId,
  toolName,
}: ArtifactSidebarProps) {
  const sidebarRef = React.useRef<HTMLDivElement>(null);
  const token = useSelector(selectToken);
  const [artifact, setArtifact] = useState<ArtifactData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !artifactId) {
      setArtifact(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    userService
      .getArtifact(artifactId, token)
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.artifact) {
          setArtifact(data.artifact);
        } else {
          setError(data.message || 'Failed to load artifact');
        }
      })
      .catch(() => setError('Failed to fetch artifact'))
      .finally(() => setLoading(false));
  }, [isOpen, artifactId, token]);

  const handleClickOutside = (event: MouseEvent) => {
    if (
      sidebarRef.current &&
      !sidebarRef.current.contains(event.target as Node)
    ) {
      onClose();
    }
  };

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  const renderContent = () => {
    if (loading) {
      return (
        <div className="flex h-full items-center justify-center">
          <Spinner />
        </div>
      );
    }
    if (error) {
      return (
        <div className="flex h-full items-center justify-center">
          <p className="text-sm text-red-500">{error}</p>
        </div>
      );
    }
    if (!artifact) return null;
    switch (artifact.artifact_type) {
      case 'todo_list':
        return <TodoListView data={artifact.data} />;
      case 'note':
        return <NoteView data={artifact.data} />;
      default:
        return (
          <pre className="text-xs text-gray-600 dark:text-gray-400">
            {JSON.stringify(artifact, null, 2)}
          </pre>
        );
    }
  };

  return (
    <div ref={sidebarRef} className="h-vh relative">
      <div
        className={`dark:bg-chinese-black fixed top-0 right-0 z-50 flex h-full w-80 transform flex-col bg-white shadow-xl transition-all duration-300 sm:w-96 ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        } border-l border-[#9ca3af]/10`}
      >
        <div className="flex w-full items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <span className="text-sm font-medium text-gray-600 dark:text-gray-300">
            {toolName || 'Artifact'}
          </span>
          <button
            className="hover:bg-gray-1000 dark:hover:bg-gun-metal rounded-full p-2"
            onClick={onClose}
          >
            <img className="h-4 w-4 filter dark:invert" src={Exit} alt="Close" />
          </button>
        </div>
        <div className="flex-1 overflow-hidden p-4">{renderContent()}</div>
      </div>
    </div>
  );
}


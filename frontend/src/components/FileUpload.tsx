import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { twMerge } from 'tailwind-merge';

import Cross from '../assets/cross.svg';
import ImagesIcon from '../assets/images.svg';

interface FileUploadProps {
  onUpload: (files: File[]) => void;
  onRemove?: (file: File) => void;
  multiple?: boolean;
  maxFiles?: number;
  maxSize?: number; // in bytes
  accept?: Record<string, string[]>; // e.g. { 'image/*': ['.png', '.jpg'] }
  showPreview?: boolean;
  previewSize?: number;

  children?: React.ReactNode;
  className?: string;
  activeClassName?: string;
  acceptClassName?: string;
  rejectClassName?: string;

  uploadText?: string | { text: string; colorClass?: string }[];
  dragActiveText?: string;
  fileTypeText?: string;
  sizeLimitText?: string;

  disabled?: boolean;
  validator?: (file: File) => { isValid: boolean; error?: string };
}

export const FileUpload = ({
  onUpload,
  onRemove,
  multiple = false,
  maxFiles = 1,
  maxSize = 5 * 1024 * 1024,
  accept = { 'image/*': ['.jpeg', '.png', '.jpg'] },
  showPreview = false,
  previewSize = 80,
  children,
  className = 'border-2 border-dashed rounded-3xl p-6 text-center cursor-pointer transition-colors border-silver dark:border-[#7E7E7E]',
  activeClassName = 'border-blue-500 bg-blue-50',
  acceptClassName = 'border-green-500 dark:border-green-500 bg-green-50 dark:bg-green-50/10',
  rejectClassName = 'border-red-500 bg-red-50 dark:bg-red-500/10 dark:border-red-500',
  uploadText = 'Click to upload or drag and drop',
  dragActiveText = 'Drop the files here',
  fileTypeText = 'PNG, JPG, JPEG up to',
  sizeLimitText = 'MB',
  disabled = false,
  validator,
}: FileUploadProps) => {
  const [errors, setErrors] = useState<string[]>([]);
  const [preview, setPreview] = useState<string | null>(null);
  const [currentFile, setCurrentFile] = useState<File | null>(null);

  const validateFile = (file: File) => {
    const defaultValidation = {
      isValid: true,
      error: '',
    };

    if (validator) {
      const customValidation = validator(file);
      if (!customValidation.isValid) {
        return customValidation;
      }
    }

    if (file.size > maxSize) {
      return {
        isValid: false,
        error: `File exceeds ${maxSize / 1024 / 1024}MB limit`,
      };
    }

    return defaultValidation;
  };

  const onDrop = useCallback(
    (acceptedFiles: File[], fileRejections: any[]) => {
      setErrors([]);

      if (fileRejections.length > 0) {
        const newErrors = fileRejections
          .map(({ errors }) => errors.map((e: any) => e.message))
          .flat();
        setErrors(newErrors);
        return;
      }

      const validationResults = acceptedFiles.map(validateFile);
      const invalidFiles = validationResults.filter((r) => !r.isValid);

      if (invalidFiles.length > 0) {
        setErrors(invalidFiles.map((f) => f.error!));
        return;
      }

      const filesToUpload = multiple ? acceptedFiles : [acceptedFiles[0]];
      onUpload(filesToUpload);

      const file = multiple ? acceptedFiles[0] : acceptedFiles[0];
      setCurrentFile(file);

      if (showPreview && file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = () => setPreview(reader.result as string);
        reader.readAsDataURL(file);
      }
    },
    [onUpload, multiple, maxSize, validator],
  );

  const {
    getRootProps,
    getInputProps,
    isDragActive,
    isDragAccept,
    isDragReject,
  } = useDropzone({
    onDrop,
    multiple,
    maxFiles,
    maxSize,
    accept,
    disabled,
  });

  const currentClassName = twMerge(
    'border-2 border-dashed rounded-3xl p-8 text-center cursor-pointer transition-colors border-silver dark:border-[#7E7E7E]',
    className,
    isDragActive && activeClassName,
    isDragAccept && acceptClassName,
    isDragReject && rejectClassName,
    disabled && 'opacity-50 cursor-not-allowed',
  );

  const handleRemove = () => {
    setPreview(null);
    setCurrentFile(null);
    if (onRemove && currentFile) onRemove(currentFile);
  };

  const renderPreview = () => (
    <div
      className="relative"
      style={{ width: previewSize, height: previewSize }}
    >
      <img
        src={preview ?? undefined}
        alt="preview"
        className="h-full w-full rounded-md object-cover"
      />
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          handleRemove();
        }}
        className="absolute -right-2 -top-2 rounded-full bg-[#7D54D1] p-1 transition-colors hover:bg-[#714cbc]"
      >
        <img src={Cross} alt="remove" className="h-3 w-3" />
      </button>
    </div>
  );

  const renderUploadText = () => {
    if (Array.isArray(uploadText)) {
      return (
        <p className="text-sm font-semibold">
          {uploadText.map((segment, i) => (
            <span key={i} className={segment.colorClass || ''}>
              {segment.text}
            </span>
          ))}
        </p>
      );
    }
    return <p className="text-sm font-semibold">{uploadText}</p>;
  };

  const defaultContent = (
    <div className="flex flex-col items-center gap-2">
      {showPreview && preview ? (
        renderPreview()
      ) : (
        <div
          style={{ width: previewSize, height: previewSize }}
          className="flex items-center justify-center"
        >
          <img src={ImagesIcon} className="h-10 w-10" />
        </div>
      )}
      <div className="text-center">
        <div className="text-sm font-medium">
          {isDragActive ? (
            <p className="text-sm font-semibold">{dragActiveText}</p>
          ) : (
            renderUploadText()
          )}
        </div>
        <p className="mt-1 text-xs text-[#A3A3A3]">
          {fileTypeText} {maxSize / 1024 / 1024}
          {sizeLimitText}
        </p>
      </div>
    </div>
  );

  return (
    <div className="relative">
      <div {...getRootProps({ className: currentClassName })}>
        <input {...getInputProps()} />
        {children || defaultContent}
        {errors.length > 0 && (
          <div className="absolute left-0 right-0 mt-[2px] px-4 text-xs text-red-600">
            {errors.map((error, i) => (
              <p key={i} className="truncate">
                {error}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

import React, { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { FileRejection } from 'react-dropzone';
import { ImageUp, X } from 'lucide-react';

import { Dropzone } from '@/components/ui/dropzone';

type UploadTextSegment = {
  text: string;
  /** Renders the segment in the brand colour; others are muted. */
  highlight?: boolean;
};

interface FileUploadProps {
  onUpload: (files: File[]) => void;
  onRemove?: (file: File) => void;
  multiple?: boolean;
  maxFiles?: number;
  maxSize?: number; // in bytes
  accept?: Record<string, string[]>; // e.g. { 'image/*': ['.png', '.jpg'] }
  showPreview?: boolean;
  previewSize?: number;
  /** `compact` is a one-row target for forms and panels. */
  size?: 'default' | 'compact';

  children?: React.ReactNode;
  /** Layout classes only; the Dropzone owns colours, border and radius. */
  className?: string;

  uploadText?: string | UploadTextSegment[];
  dragActiveText?: string;
  fileTypeText?: string;
  sizeLimitText?: string;

  disabled?: boolean;
  validator?: (file: File) => { isValid: boolean; error?: string };
}

/**
 * Image/file picker built on `ui/dropzone`. Adds size and custom validation,
 * an optional image preview with a remove button, and translated prompts.
 *
 * @param props - See `FileUploadProps`.
 * @returns The dropzone with its preview and validation errors.
 */
export const FileUpload = ({
  onUpload,
  onRemove,
  multiple = false,
  maxFiles = 1,
  maxSize = 5 * 1024 * 1024,
  accept = { 'image/*': ['.jpeg', '.png', '.jpg'] },
  showPreview = false,
  previewSize = 80,
  size = 'default',
  children,
  className,
  uploadText,
  dragActiveText,
  fileTypeText,
  sizeLimitText,
  disabled = false,
  validator,
}: FileUploadProps) => {
  const { t } = useTranslation();
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
        error: t('components.fileUpload.fileSizeError', {
          size: maxSize / 1024 / 1024,
        }),
      };
    }

    return defaultValidation;
  };

  const onDrop = useCallback(
    (acceptedFiles: File[], fileRejections: FileRejection[]) => {
      setErrors([]);

      if (fileRejections.length > 0) {
        const newErrors = fileRejections
          .map(({ errors }) => errors.map((e) => e.message))
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

      const file = acceptedFiles[0];
      setCurrentFile(file);

      if (showPreview && file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = () => setPreview(reader.result as string);
        reader.readAsDataURL(file);
      }
    },
    [onUpload, multiple, maxSize, validator],
  );

  const handleRemove = () => {
    setPreview(null);
    setCurrentFile(null);
    if (onRemove && currentFile) onRemove(currentFile);
  };

  // Callers size the preview box at runtime; a custom property keeps the
  // dimension out of the style's width/height and in the classes.
  const previewSizeStyle = {
    '--preview-size': `${previewSize}px`,
  } as React.CSSProperties;

  const renderPreview = () => (
    <div
      className="relative size-(--preview-size) shrink-0"
      style={previewSizeStyle}
    >
      <img
        src={preview ?? undefined}
        alt={t('components.fileUpload.preview')}
        className="h-full w-full rounded-md object-cover"
      />
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          handleRemove();
        }}
        className="bg-primary hover:bg-primary/90 absolute -top-2 -right-2 rounded-full p-1 transition-colors"
        aria-label={t('components.fileUpload.remove')}
      >
        <X className="text-primary-foreground size-3" />
      </button>
    </div>
  );

  const uploadPrompt = Array.isArray(uploadText)
    ? uploadText.map((segment, i) => (
        <span
          key={i}
          className={
            segment.highlight ? 'text-primary' : 'text-muted-foreground'
          }
        >
          {segment.text}
        </span>
      ))
    : uploadText || t('components.fileUpload.clickToUpload');

  // The Dropzone owns the drag state; its data attribute swaps the prompt.
  const title = (
    <>
      <span className="in-data-[drag-active]:hidden">{uploadPrompt}</span>
      <span className="hidden in-data-[drag-active]:inline">
        {dragActiveText || t('components.fileUpload.dropFiles')}
      </span>
    </>
  );

  const description = (
    <>
      {fileTypeText || t('components.fileUpload.fileTypes')}{' '}
      {maxSize / 1024 / 1024}
      {sizeLimitText || t('components.fileUpload.sizeLimitUnit')}
    </>
  );

  // With a preview, the image takes the icon's place; the text block mirrors
  // the Dropzone's own title/description layout.
  const previewContent =
    showPreview && preview ? (
      <>
        {renderPreview()}
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-sm font-medium">{title}</span>
          <span className="text-muted-foreground text-xs">{description}</span>
        </span>
      </>
    ) : undefined;

  const error =
    errors.length > 0
      ? errors.map((message, i) => (
          <span key={i} className="block truncate">
            {message}
          </span>
        ))
      : undefined;

  return (
    <Dropzone
      onDrop={onDrop}
      accept={accept}
      multiple={multiple}
      maxFiles={maxFiles}
      maxSize={maxSize}
      disabled={disabled}
      size={size}
      title={title}
      description={description}
      icon={<ImageUp />}
      error={error}
      className={className}
    >
      {children ?? previewContent}
    </Dropzone>
  );
};

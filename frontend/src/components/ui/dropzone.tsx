import * as React from 'react';
import { CloudUpload } from 'lucide-react';
import {
  useDropzone,
  type Accept,
  type DropzoneOptions,
  type FileRejection,
} from 'react-dropzone';

import { cn } from '@/lib/utils';

type DropzoneProps = {
  /** Receives accepted files and, when `accept`/`maxSize` reject some, the rejections. */
  onDrop: (accepted: File[], rejections: FileRejection[]) => void;
  /** MIME-type map, e.g. `{ 'application/x-yaml': ['.yaml', '.yml'] }`. */
  accept?: Accept;
  multiple?: boolean;
  maxFiles?: number;
  maxSize?: number;
  disabled?: boolean;
  /** Compact fits inside forms and modals; default is the full-height target. */
  size?: 'default' | 'compact';
  /** Main line. Defaults to the generic upload prompt. */
  title?: React.ReactNode;
  /** Secondary line for accepted types and limits, e.g. ".yaml, up to 5 MB". */
  description?: React.ReactNode;
  /** Replaces the cloud icon. */
  icon?: React.ReactNode;
  /** Shown under the target in the destructive colour. */
  error?: React.ReactNode;
  /** Replaces the icon/title/description block entirely. */
  children?: React.ReactNode;
  className?: string;
  validator?: DropzoneOptions['validator'];
};

/**
 * Click-or-drag file target. Layout classes may be passed through
 * `className`; colours, border and radius are owned by the component and
 * follow the drag state (`data-drag-active`, `data-drag-reject`).
 */
function Dropzone({
  onDrop,
  accept,
  multiple = false,
  maxFiles,
  maxSize,
  disabled = false,
  size = 'default',
  title = 'Click to upload or drag and drop',
  description,
  icon,
  error,
  children,
  className,
  validator,
}: DropzoneProps) {
  const { getRootProps, getInputProps, isDragActive, isDragReject } =
    useDropzone({
      onDrop,
      accept,
      multiple,
      maxFiles,
      maxSize,
      disabled,
      validator,
    });

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div
        {...getRootProps()}
        data-slot="dropzone"
        data-size={size}
        data-disabled={disabled || undefined}
        data-drag-active={isDragActive || undefined}
        data-drag-reject={isDragReject || undefined}
        className={cn(
          'border-border bg-card text-foreground hover:bg-accent/40 focus-visible:ring-ring/50 flex w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed text-center transition-colors outline-none focus-visible:ring-3',
          'data-[drag-active]:border-primary data-[drag-active]:bg-primary/5',
          'data-[drag-reject]:border-destructive data-[drag-reject]:bg-destructive/5',
          'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
          size === 'default' && 'px-6 py-10',
          size === 'compact' && 'flex-row justify-start px-4 py-3 text-left',
        )}
      >
        <input {...getInputProps()} />
        {children ?? (
          <>
            <span
              className={cn(
                'bg-muted text-muted-foreground flex shrink-0 items-center justify-center rounded-full',
                size === 'default'
                  ? 'size-12 [&>svg]:size-6'
                  : 'size-8 [&>svg]:size-4',
              )}
            >
              {icon ?? <CloudUpload />}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-medium">{title}</span>
              {description ? (
                <span className="text-muted-foreground text-xs">
                  {description}
                </span>
              ) : null}
            </span>
          </>
        )}
      </div>
      {error ? <p className="text-destructive text-xs">{error}</p> : null}
    </div>
  );
}

export { Dropzone };
export type { DropzoneProps };

export type InputProps = {
  type: 'text' | 'number';
  value: string | string[] | number;
  colorVariant?: 'silver' | 'jet' | 'gray';
  borderVariant?: 'thin' | 'thick';
  textSize?: 'small' | 'medium';
  isAutoFocused?: boolean;
  id?: string;
  maxLength?: number;
  name?: string;
  placeholder?: string;
  required?: boolean;
  className?: string;
  children?: React.ReactElement;
  labelBgClassName?: string;
  onChange: (
    e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>,
  ) => void;
  onPaste?: (
    e: React.ClipboardEvent<HTMLTextAreaElement | HTMLInputElement>,
  ) => void;
  onKeyDown?: (
    e: React.KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>,
  ) => void;
};

export type MermaidRendererProps = {
  code: string;
  isLoading?: boolean;
};

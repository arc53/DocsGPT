export type InputProps = {
  type: 'text' | 'number';
  value: string | string[] | number;
  colorVariant?: 'silver' | 'jet' | 'gray';
  borderVariant?: 'thin' | 'thick';
  isAutoFocused?: boolean;
  id?: string;
  maxLength?: number;
  name?: string;
  placeholder?: string;
  className?: string;
  children?: React.ReactElement;
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

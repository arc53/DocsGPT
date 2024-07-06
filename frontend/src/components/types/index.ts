export type TextAreaProps = {
  value: string | string[] | number;
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

export type InputProps = TextAreaProps & {
  type: 'text' | 'number';
  colorVariant?: 'silver' | 'jet' | 'gray';
};

import { Search } from 'lucide-react';

import { Input, type InputProps } from './ui/input';

type SearchInputProps = Omit<InputProps, 'shape' | 'leftIcon' | 'size'> & {
  size?: 'field' | 'sm';
};

/**
 * The search field above a list or grid: a 38px pill with a search icon.
 * Give it a `label` (the floating label, the default for page searches) or a
 * `placeholder`; a placeholder-only field is named by its placeholder.
 */
export default function SearchInput({
  size = 'field',
  labelSurface = 'background',
  type = 'text',
  label,
  placeholder,
  ...props
}: SearchInputProps) {
  return (
    <Input
      type={type}
      size={size}
      shape="pill"
      label={label}
      placeholder={placeholder}
      aria-label={label ? undefined : (props['aria-label'] ?? placeholder)}
      labelSurface={labelSurface}
      leftIcon={<Search className="text-muted-foreground size-4" aria-hidden />}
      {...props}
    />
  );
}

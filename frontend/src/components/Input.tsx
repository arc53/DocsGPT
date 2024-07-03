import { InputProps } from './types';

const Input = ({
  id,
  name,
  type,
  value,
  isAutoFocused = false,
  placeholder,
  maxLength,
  className,
  hasSilverBorder,
  children,
  onChange,
  onPaste,
  onKeyDown,
}: InputProps) => {
  return (
    <input
      className={`h-[42px] w-full rounded-full border-2 px-3 outline-none dark:bg-transparent dark:text-white ${
        hasSilverBorder ? 'border-silver dark:border-silver/40' : ''
      } ${className}`}
      type={type}
      id={id}
      name={name}
      autoFocus={isAutoFocused}
      placeholder={placeholder}
      maxLength={maxLength}
      value={value}
      onChange={onChange}
      onPaste={onPaste}
      onKeyDown={onKeyDown}
    >
      {children}
    </input>
  );
};

export default Input;

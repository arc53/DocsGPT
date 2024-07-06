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
  colorVariant = 'silver',
  children,
  onChange,
  onPaste,
  onKeyDown,
}: InputProps) => {
  return (
    <input
      className={`h-[42px] w-full rounded-full border-2 px-3 outline-none dark:bg-transparent dark:text-white ${className} ${
        colorVariant === 'silver' ? 'border-silver dark:border-silver/40' : ''
      } ${colorVariant === 'jet' ? 'border-jet' : ''} ${
        colorVariant === 'gray' ? 'border-gray-5000 dark:text-silver' : ''
      }
      }`}
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

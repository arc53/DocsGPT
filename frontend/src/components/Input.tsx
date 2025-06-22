import { InputProps } from './types';
import { useRef } from 'react';

const Input = ({
  id,
  name,
  type,
  value,
  isAutoFocused = false,
  placeholder,
  required = false,
  maxLength,
  className = '',
  colorVariant = 'silver',
  borderVariant = 'thick',
  textSize = 'medium',
  children,
  labelBgClassName = 'bg-white dark:bg-raisin-black',
  onChange,
  onPaste,
  onKeyDown,
}: InputProps) => {
  const colorStyles = {
    silver: 'border-silver dark:border-silver/40',
    jet: 'border-jet',
    gray: 'border-gray-5000 dark:text-silver',
  };
  const borderStyles = {
    thin: 'border',
    thick: 'border-2',
  };
  const textSizeStyles = {
    small: 'text-sm',
    medium: 'text-base',
  };

  const inputRef = useRef<HTMLInputElement>(null);

  const hasValue = value !== undefined && value !== null && value !== '';

  return (
    <div className={`relative ${className}`}>
      <input
        ref={inputRef}
        className={`peer text-jet dark:text-bright-gray h-[42px] w-full rounded-full bg-transparent px-3 py-1 placeholder-transparent outline-hidden ${colorStyles[colorVariant]} ${borderStyles[borderVariant]} ${textSizeStyles[textSize]} [&:-webkit-autofill]:appearance-none [&:-webkit-autofill]:bg-transparent [&:-webkit-autofill_selected]:bg-transparent`}
        type={type}
        id={id}
        name={name}
        autoFocus={isAutoFocused}
        placeholder={placeholder || ''}
        maxLength={maxLength}
        value={value}
        onChange={onChange}
        onPaste={onPaste}
        onKeyDown={onKeyDown}
        required={required}
      >
        {children}
      </input>
      {placeholder && (
        <label
          htmlFor={id}
          className={`absolute select-none ${
            hasValue ? '-top-2.5 left-3 text-xs' : ''
          } px-2 transition-all peer-placeholder-shown:top-2.5 peer-placeholder-shown:left-3 peer-placeholder-shown:${
            textSizeStyles[textSize]
          } text-gray-4000 pointer-events-none cursor-none peer-focus:-top-2.5 peer-focus:left-3 peer-focus:text-xs dark:text-gray-400 ${labelBgClassName} max-w-[calc(100%-24px)] overflow-hidden text-ellipsis whitespace-nowrap`}
        >
          {placeholder}
          {required && (
            <span className="ml-0.5 text-[#D30000] dark:text-[#D42626]">*</span>
          )}
        </label>
      )}
    </div>
  );
};

export default Input;

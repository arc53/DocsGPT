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
  labelBgClassName = 'bg-card',
  leftIcon,
  onChange,
  onPaste,
  onKeyDown,
  edgeRoundness = 'rounded-full',
  'data-testid': dataTestId,
}: InputProps) => {
  const colorStyles = {
    silver: 'border-border dark:border-border',
    jet: 'border-jet',
    gray: 'border-gray-5000 dark:text-muted-foreground',
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
        className={`peer text-foreground dark:text-foreground h-[42px] w-full ${edgeRoundness} bg-transparent ${leftIcon ? 'pl-10' : 'px-3'} py-1 placeholder-transparent outline-hidden ${colorStyles[colorVariant]} ${borderStyles[borderVariant]} ${textSizeStyles[textSize]} [&:-webkit-autofill]:appearance-none [&:-webkit-autofill]:bg-transparent [&:-webkit-autofill_selected]:bg-transparent`}
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
        data-testid={dataTestId}
      >
        {children}
      </input>
      {leftIcon && (
        <div className="absolute top-1/2 left-3 flex -translate-y-1/2 transform items-center justify-center">
          {leftIcon}
        </div>
      )}
      {placeholder && (
        <label
          htmlFor={id}
          className={`absolute select-none ${
            hasValue ? '-top-2.5 left-3 text-xs' : ''
          } px-2 transition-all peer-placeholder-shown:top-2.5 ${
            leftIcon
              ? 'peer-placeholder-shown:left-7'
              : 'peer-placeholder-shown:left-3'
          } peer-placeholder-shown:${
            textSizeStyles[textSize]
          } text-muted-foreground pointer-events-none cursor-none peer-focus:-top-2.5 peer-focus:left-3 peer-focus:text-xs ${labelBgClassName} max-w-[calc(100%-24px)] overflow-hidden text-ellipsis whitespace-nowrap`}
        >
          {placeholder}
          {required && (
            <span className="ml-0.5 text-[#D30000] dark:text-red-500">*</span>
          )}
        </label>
      )}
    </div>
  );
};

export default Input;

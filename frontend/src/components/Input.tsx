import { InputProps } from './types';

const Input = ({
  id,
  name,
  type,
  value,
  isAutoFocused = false,
  placeholder,
  label,
  maxLength,
  className,
  colorVariant = 'silver',
  borderVariant = 'thick',
  children,
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
  return (
    <div className="relative">
      <input
        className={`h-[42px] w-full rounded-full px-3 py-1 outline-none dark:bg-transparent dark:text-white ${className} ${colorStyles[colorVariant]} ${borderStyles[borderVariant]}`}
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
      {label && (
        <div className="absolute -top-2 left-2">
          <span className="bg-white px-2 text-xs text-gray-4000 dark:bg-outer-space dark:text-silver">
            {label}
          </span>
        </div>
      )}
    </div>
  );
};

export default Input;

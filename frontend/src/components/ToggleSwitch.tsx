import React from 'react';

type ToggleSwitchProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  className?: string;
  label?: string;
  disabled?: boolean;
  activeColor?: string;
  inactiveColor?: string;
  id?: string;
};

const ToggleSwitch: React.FC<ToggleSwitchProps> = ({
  checked,
  onChange,
  className = '',
  label,
  disabled = false,
  activeColor = 'bg-purple-30',
  inactiveColor = 'bg-transparent',
  id,
}) => {
  return (
    <label
      className={`cursor-pointer select-none justify-between flex flex-row items-center ${disabled ? 'opacity-50 cursor-not-allowed' : ''} ${className}`}
      htmlFor={id}
    >
      {label && (
        <span className="mr-2 text-eerie-black dark:text-white">{label}</span>
      )}
      <div className="relative">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only"
          disabled={disabled}
          id={id}
        />
        <div
          className={`box block h-8 w-14 rounded-full border border-purple-30 ${
            checked
              ? `${activeColor} dark:${activeColor}`
              : `${inactiveColor} dark:${inactiveColor}`
          }`}
        ></div>
        <div
          className={`absolute left-1 top-1 flex h-6 w-6 items-center justify-center rounded-full transition ${
            checked ? 'translate-x-full bg-silver' : 'bg-purple-30'
          }`}
        ></div>
      </div>
    </label>
  );
};

export default ToggleSwitch;

import React from 'react';

type ToggleSwitchProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  className?: string;
  label?: string;
  disabled?: boolean;
  size?: 'small' | 'medium' | 'large';
  labelPosition?: 'left' | 'right';
  id?: string;
  ariaLabel?: string;
};

const ToggleSwitch: React.FC<ToggleSwitchProps> = ({
  checked,
  onChange,
  className = '',
  label,
  disabled = false,
  size = 'medium',
  labelPosition = 'left',
  id,
  ariaLabel,
}) => {
  // Size configurations
  const sizeConfig = {
    small: {
      box: 'h-5 w-9',
      toggle: 'h-4 w-4 left-0.5 top-0.5',
      translate: 'translate-x-full',
    },
    medium: {
      box: 'h-8 w-14',
      toggle: 'h-6 w-6 left-1 top-1',
      translate: 'translate-x-full',
    },
    large: {
      box: 'h-10 w-16',
      toggle: 'h-8 w-8 left-1 top-1',
      translate: 'translate-x-full',
    },
  };

  const { box, toggle, translate } = sizeConfig[size];

  return (
    <label
      className={`flex cursor-pointer select-none flex-row items-center ${
        labelPosition === 'right' ? 'flex-row-reverse' : ''
      } ${disabled ? 'cursor-not-allowed opacity-50' : ''} ${className}`}
    >
      {label && (
        <span
          className={`text-eerie-black dark:text-white ${
            labelPosition === 'left' ? 'mr-1' : 'ml-1'
          }`}
        >
          {label}
        </span>
      )}
      <div className="relative">
        <input
          type="checkbox"
          id={id}
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only"
          disabled={disabled}
          aria-label={ariaLabel}
        />
        <div
          className={`block ${box} rounded-full ${
            checked ? 'bg-north-texas-green' : 'bg-silver dark:bg-charcoal-grey'
          }`}
        ></div>
        <div
          className={`absolute ${toggle} flex items-center justify-center rounded-full bg-white opacity-80 transition ${
            checked ? `${translate} bg-silver` : ''
          }`}
        ></div>
      </div>
    </label>
  );
};

export default ToggleSwitch;

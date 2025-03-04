import React from 'react';

type ToggleSwitchProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  className?: string;
  label?: string;
  disabled?: boolean;
  size?: 'small' | 'medium' | 'large';
  labelPosition?: 'left' | 'right';
};

const ToggleSwitch: React.FC<ToggleSwitchProps> = ({
  checked,
  onChange,
  className = '',
  label,
  disabled = false,
  size = 'medium',
  labelPosition = 'left',
}) => {
  // Size configurations
  const sizeConfig = {
    small: {
      box: 'h-6 w-10',
      toggle: 'h-4 w-4 left-1 top-1',
      translate: 'translate-x-4',
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
      className={`cursor-pointer select-none flex flex-row items-center ${
        labelPosition === 'right' ? 'flex-row-reverse' : ''
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''} ${className}`}
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
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only"
          disabled={disabled}
        />
        <div
          className={`box block ${box} rounded-full ${
            checked ? 'bg-apple-green' : 'bg-silver dark:bg-charcoal-grey'
          }`}
        ></div>
        <div
          className={`absolute ${toggle} flex items-center justify-center rounded-full transition bg-white opacity-80 ${
            checked ? `${translate} bg-silver` : ''
          }`}
        ></div>
      </div>
    </label>
  );
};

export default ToggleSwitch;

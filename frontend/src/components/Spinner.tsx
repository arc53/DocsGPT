import { Spinner as UiSpinner } from './ui/spinner';

type SpinnerProps = {
  size?: 'small' | 'medium' | 'large';
};

const SIZE_MAP = { small: 'sm', medium: 'default', large: 'lg' } as const;

/**
 * Compatibility wrapper over `ui/spinner`. New code should import
 * `Spinner` from `@/components/ui/spinner` and use `sm | default | lg`.
 */
export default function Spinner({ size = 'medium' }: SpinnerProps) {
  return <UiSpinner size={SIZE_MAP[size]} />;
}

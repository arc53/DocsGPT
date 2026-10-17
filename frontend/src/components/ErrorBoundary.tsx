import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { isChunkLoadError } from '../utils/chunkReload';

import { Button } from './ui/button';

type ErrorBoundaryProps = {
  children: ReactNode;
  // Render-prop fallback; receives a retry callback that re-attempts
  // rendering the children.
  fallback?: (retry: () => void) => ReactNode;
  // A caught error clears when this changes, without remounting healthy
  // children the way a ``key`` would.
  resetKey?: unknown;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error?: unknown;
  resetKey?: unknown;
};

function DefaultFallback({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="text-muted-foreground flex flex-col items-center gap-3 p-6 text-sm"
    >
      <p>{t('errorBoundary.message')}</p>
      <Button type="button" variant="outline" onClick={onRetry}>
        {t('errorBoundary.tryAgain')}
      </Button>
    </div>
  );
}

export default class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = {
    hasError: false,
    resetKey: this.props.resetKey,
  };

  static getDerivedStateFromError(error: unknown): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: ErrorBoundaryState,
  ): Partial<ErrorBoundaryState> | null {
    if (props.resetKey === state.resetKey) return null;
    return { hasError: false, error: undefined, resetKey: props.resetKey };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught a render error:', error, info);
  }

  retry = () => {
    // A lazy chunk a deploy replaced can't be fetched again, and React.lazy
    // caches the failure, so only a reload (new index.html) recovers.
    if (isChunkLoadError(this.state.error)) {
      window.location.reload();
      return;
    }
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback(this.retry);
      return <DefaultFallback onRetry={this.retry} />;
    }
    return this.props.children;
  }
}

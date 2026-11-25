import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      message: error?.message || 'An unexpected application error occurred.',
    };
  }

  componentDidCatch(error: Error) {
    console.error('Atlas CTF ErrorBoundary caught:', error);
  }

  render() {
    if (this.state.hasError) {
      let displayDetail = this.state.message;
      try {
        const parsed = JSON.parse(this.state.message);
        if (parsed && parsed.operationType && parsed.error) {
          displayDetail = `Firestore ${parsed.operationType.toUpperCase()} error on ${parsed.path || 'unknown path'}: ${parsed.error}`;
        }
      } catch {
        // Keep plain string message
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-[#0B1120] p-6">
          <div className="max-w-lg w-full border border-slate-200 dark:border-slate-800 bg-white dark:bg-[#111827] rounded-lg p-6 space-y-4">
            <div className="flex items-center gap-3 text-red-600 dark:text-red-400">
              <AlertTriangle className="w-5 h-5 shrink-0" />
              <h2 className="text-lg font-semibold font-display">Workspace Error</h2>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-300 font-mono break-words bg-slate-100 dark:bg-slate-900 p-3 rounded border border-slate-200 dark:border-slate-800">
              {displayDetail}
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-amber-500 text-slate-950 hover:bg-amber-400 transition-colors cursor-pointer whitespace-nowrap"
            >
              <RotateCcw className="w-4 h-4" />
              Reload Workbench
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

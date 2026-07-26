import React from "react";

// Catches render-time errors anywhere below it in the tree so one broken component
// (e.g. a page crashing on unexpected API data) shows a recoverable message instead
// of a blank white screen for the whole app. Must be a class component — React error
// boundaries have no hook equivalent.
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("Unhandled UI error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center p-8 text-center text-white/80">
          <div>
            <h1 className="mb-2 text-lg font-semibold">Something went wrong</h1>
            <p className="mb-4 text-sm text-white/50">
              Try reloading the page. If this keeps happening, contact your admin.
            </p>
            <button
              className="rounded border border-white/20 px-4 py-2 text-sm hover:bg-white/10"
              onClick={() => window.location.reload()}
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

"use client";

import React from "react";

import { ApiError } from "@/lib/api";

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error("ErrorBoundary caught:", error, info);
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  private copyDetails = (): void => {
    const { error } = this.state;
    if (!error) return;
    const parts = [error.message];
    if (error instanceof ApiError && error.requestId) {
      parts.push(`request_id=${error.requestId}`);
    }
    if (error.stack) {
      parts.push(error.stack);
    }
    void navigator.clipboard.writeText(parts.join("\n"));
  };

  override render() {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }
    const requestId = error instanceof ApiError ? error.requestId : undefined;
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#0a0a0a] p-8 text-center">
        <h1 className="text-xl font-semibold text-gray-100">Something went wrong.</h1>
        <p className="max-w-md text-sm break-words text-gray-400">{error.message}</p>
        {requestId && <p className="text-xs text-gray-400">Request ID: {requestId}</p>}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={this.handleReload}
            className="rounded-md bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700"
          >
            Reload
          </button>
          <button
            type="button"
            onClick={this.copyDetails}
            className="rounded-md bg-gray-700 px-4 py-2 text-sm text-gray-200 hover:bg-gray-600"
          >
            Copy details
          </button>
        </div>
      </div>
    );
  }
}

import React, { Component, ErrorInfo, ReactNode } from "react";
import { AlertCircle, RotateCcw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("VYOM UI ErrorBoundary caught an unhandled exception:", error, errorInfo);
  }

  public handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div style={{
          position: "fixed",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#05090b",
          color: "#c8eeea",
          fontFamily: "system-ui, -apple-system, sans-serif",
          zIndex: 99999,
          padding: "24px",
          textAlign: "center"
        }}>
          <div style={{
            background: "rgba(22, 33, 36, 0.8)",
            border: "1px solid rgba(112, 208, 205, 0.25)",
            borderRadius: "12px",
            padding: "32px",
            maxWidth: "520px",
            boxShadow: "0 8px 32px rgba(0,0,0,0.6)"
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "10px", marginBottom: "16px", color: "#6fe0db" }}>
              <AlertCircle size={28} />
              <h2 style={{ margin: 0, fontSize: "1.25rem", letterSpacing: "0.08em" }}>VYOM RECOVERY</h2>
            </div>
            <p style={{ color: "#8bbab7", fontSize: "0.9rem", lineHeight: "1.5", marginBottom: "20px" }}>
              An interface component encountered an unexpected state. The living runtime remains active.
            </p>
            <button
              type="button"
              onClick={this.handleReset}
              style={{
                background: "#164e4f",
                color: "#e0f7f2",
                border: "1px solid #70d0cd",
                padding: "8px 20px",
                borderRadius: "6px",
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                fontSize: "0.85rem",
                letterSpacing: "0.04em"
              }}
            >
              <RotateCcw size={14} /> Restore Interface
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

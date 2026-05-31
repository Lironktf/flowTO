import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  /** What to label the failed region (e.g. "Copilot", "FlowTO"). */
  label?: string;
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/**
 * Reusable boundary: keeps a render error in one region (a dock, the copilot)
 * from blanking the whole app. Shows a compact, themed fallback with a reload.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label ?? "ui"}] render error:`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="insp-empty" role="alert" style={{ padding: "24px 16px" }}>
        <div className="big">{this.props.label ?? "Something"} hit an error</div>
        <div className="sm">This panel stopped responding. Reloading usually clears it.</div>
        <button className="btn btn-sm" style={{ marginTop: 12 }} onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}

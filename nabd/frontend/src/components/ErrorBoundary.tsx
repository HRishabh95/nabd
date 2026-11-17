// A failure inside one page shows a clear message instead of a blank screen; the rest of the app keeps working.
import { Component, type ReactNode } from 'react';

type State = { error: Error | null };

export default class ErrorBoundary extends Component<{ children: ReactNode; name: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State { return { error }; }

  componentDidUpdate(prev: { name: string }) {
    if (prev.name !== this.props.name && this.state.error) this.setState({ error: null });  // a new page starts clean
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="fill grid"><section className="card s12 crash" role="alert">
        <h2>This page hit a problem</h2>
        <p className="note">Nabd kept running and no data was changed. Reload the page; if it happens again, the details below help us fix it.</p>
        <pre className="json">{this.state.error.message}</pre>
        <button className="btn filled small" type="button" onClick={() => location.reload()}>Reload</button>
      </section></div>
    );
  }
}

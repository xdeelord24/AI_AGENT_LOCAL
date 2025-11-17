import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

if (typeof window !== 'undefined' && !window.__resizeObserverPatched) {
  window.__resizeObserverPatched = true;
  const SUPPRESSED_MESSAGES = new Set([
    'ResizeObserver loop completed with undelivered notifications.',
    'ResizeObserver loop limit exceeded',
  ]);

  const matchesSuppressedMessage = (message) => {
    if (!message) return false;
    const normalized = String(message);
    return (
      SUPPRESSED_MESSAGES.has(normalized) ||
      normalized.toLowerCase().includes('resizeobserver loop')
    );
  };

  const suppressResizeObserverError = (event) => {
    if (matchesSuppressedMessage(event?.message)) {
      event.preventDefault?.();
      event.stopImmediatePropagation?.();
      event.stopPropagation?.();
      event.returnValue = false;
    }
  };

  const suppressResizeObserverRejection = (event) => {
    const reasonMessage = event?.reason?.message || event?.reason;
    if (matchesSuppressedMessage(reasonMessage)) {
      event.preventDefault?.();
      event.stopImmediatePropagation?.();
      event.stopPropagation?.();
    }
  };

  window.addEventListener('error', suppressResizeObserverError, { capture: true });
  window.addEventListener('unhandledrejection', suppressResizeObserverRejection, { capture: true });

  // Also filter these noisy errors from the dev console / React error overlay by
  // patching console.error to drop them before the overlay sees them.
  const originalConsoleError = window.console?.error?.bind(window.console) || console.error;
  window.console.error = (...args) => {
    const [first] = args;
    if (first instanceof Error) {
      if (matchesSuppressedMessage(first.message)) {
        return;
      }
    }
    if (typeof first === 'string' && matchesSuppressedMessage(first)) {
      return;
    }
    originalConsoleError(...args);
  };
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

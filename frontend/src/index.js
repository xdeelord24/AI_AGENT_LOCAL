import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

if (typeof window !== 'undefined') {
  const SUPPRESSED_MESSAGES = new Set([
    'ResizeObserver loop completed with undelivered notifications.',
    'ResizeObserver loop limit exceeded',
  ]);

  const shouldSuppress = (message) => Boolean(message && SUPPRESSED_MESSAGES.has(message));

  const suppressResizeObserverError = (event) => {
    if (shouldSuppress(event?.message)) {
      event.preventDefault?.();
      event.stopImmediatePropagation?.();
      event.returnValue = false;
    }
  };

  const suppressResizeObserverRejection = (event) => {
    if (shouldSuppress(event?.reason?.message || event?.reason)) {
      event.preventDefault?.();
      event.stopImmediatePropagation?.();
    }
  };

  window.addEventListener('error', suppressResizeObserverError, true);
  window.addEventListener('unhandledrejection', suppressResizeObserverRejection, true);
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

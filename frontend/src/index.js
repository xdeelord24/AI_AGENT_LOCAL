import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

// Global patch to make ResizeObserver safer and quieter in dev.
// - Batches callbacks into requestAnimationFrame to avoid the Chrome
//   "ResizeObserver loop completed with undelivered notifications" error
//   that happens when resize handlers cause further layout changes.
// - Suppresses those specific noisy errors from the React error overlay.
if (typeof window !== 'undefined' && !window.__resizeObserverPatched) {
  window.__resizeObserverPatched = true;

  if (window.ResizeObserver) {
    const OriginalResizeObserver = window.ResizeObserver;
    window.ResizeObserver = class PatchedResizeObserver extends OriginalResizeObserver {
      constructor(callback) {
        let frameId = null;
        let pendingEntries = [];

        const rafCallback = (entries, observer) => {
          pendingEntries.push(...entries);
          if (frameId != null) {
            return;
          }
          frameId = window.requestAnimationFrame(() => {
            const toProcess = pendingEntries;
            pendingEntries = [];
            frameId = null;
            try {
              callback(toProcess, observer);
            } catch (error) {
              // Re-throw asynchronously so it doesn't trigger the ResizeObserver loop error.
              setTimeout(() => {
                throw error;
              }, 0);
            }
          });
        };

        super(rafCallback);
      }
    };
  }
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

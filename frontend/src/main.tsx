import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from 'react-query';
import { Dashboard } from './pages/Dashboard';
import './styles.css';

const qc = new QueryClient();

function Root() {
  return (
    <React.StrictMode>
      <QueryClientProvider client={qc}>
        <Dashboard />
      </QueryClientProvider>
    </React.StrictMode>
  );
}

const el = document.getElementById('root');
if (!el) {
  console.error('Root element not found');
} else {
  try {
    ReactDOM.createRoot(el as HTMLElement).render(<Root />);
  } catch (e) {
    console.error('Render error', e);
    const pre = document.createElement('pre');
    pre.style.color = 'red';
    pre.textContent = 'Render failed: ' + (e as any).message;
    document.body.appendChild(pre);
  }
}

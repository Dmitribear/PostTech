import App from '@/app/App';
import '@/shared/styles/styles.css';
import '@/shared/styles/workspace-shell.css';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

try {
  document.body.dataset.density =
    localStorage.getItem('posttech.density') === 'compact' ? 'compact' : 'comfortable';
} catch {
  /* browser storage is optional */
}
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);

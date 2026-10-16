import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles.css';

try { document.body.dataset.density = localStorage.getItem('posttech.density') === 'compact' ? 'compact' : 'comfortable'; } catch { /* browser storage is optional */ }
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>);

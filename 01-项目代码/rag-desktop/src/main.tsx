/**
 * React 应用的入口：把 <App /> 渲染到 index.html 的 #root 里。
 * 这行代码是 React 18 的新写法（以前是 ReactDOM.render）。
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

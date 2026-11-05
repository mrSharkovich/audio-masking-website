import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { useTheme } from './hooks/useTheme';
import { HomePage } from './pages/HomePage';
import { ProcessPage } from './pages/ProcessPage';
import { HowItWorksPage } from './pages/HowItWorksPage';
import { AboutPage } from './pages/AboutPage';
import type { AudioAdapters } from './types/audio';

const pages = [
  { path: '/', label: 'Главная' },
  { path: '/process', label: 'Обработка' },
  { path: '/how-it-works', label: 'Как это работает' },
  { path: '/about', label: 'О проекте' },
];

function Brand() {
  return <a className="brand" href="/" aria-label="AudioMask — на главную"><span>AudioMask</span></a>;
}

export function App({ adapters }: { adapters?: AudioAdapters }) {
  const { theme, toggle } = useTheme();
  const [path, setPath] = useState(window.location.pathname);
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(path);
  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  useEffect(() => {
    document.title = `${pages.find((page) => page.path === path)?.label ?? 'Страница не найдена'} — AudioMask`;
    if (previousPath.current !== path) {
      main.current?.focus();
      const target = document.getElementById(window.location.hash.slice(1));
      if (target) target.scrollIntoView();
      else window.scrollTo(0, 0);
      previousPath.current = path;
    }
  }, [path]);
  function navigate(event: MouseEvent<HTMLDivElement>) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as Element).closest('a');
    if (!anchor || anchor.target || anchor.hasAttribute('download')) return;
    const url = new URL(anchor.href);
    if (url.origin !== window.location.origin || !pages.some((page) => page.path === url.pathname)) return;
    if (url.pathname === path && url.hash) return;
    event.preventDefault();
    if (url.pathname === path) return;
    window.history.pushState(null, '', url.pathname + url.hash);
    setPath(url.pathname);
  }
  return <div onClick={navigate}>
    <a className="skip-link" href="#main-content">К содержимому страницы</a>
    <header className="site-header"><div className="header-inner"><Brand />
      <nav aria-label="Основная навигация">{pages.map((page) => <a key={page.path} href={page.path} aria-current={path === page.path ? 'page' : undefined}>{page.label}</a>)}</nav>
      <button type="button" className="theme-toggle" onClick={toggle} aria-label="Тёмная тема" aria-pressed={theme === 'dark'}><span aria-hidden="true">{theme === 'dark' ? '☾' : '☀'}</span><span>{theme === 'dark' ? 'Тёмная' : 'Светлая'}</span></button>
    </div></header>
    <main className="page-shell" id="main-content" ref={main} tabIndex={-1}>
      {path === '/' ? <HomePage /> : path === '/process' ? <ProcessPage adapters={adapters} /> : path === '/how-it-works' ? <HowItWorksPage /> : path === '/about' ? <AboutPage /> : <section className="workspace-section"><h1>Страница не найдена</h1><a href="/">На главную</a></section>}
    </main>
    <footer className="site-footer"><span>AudioMask</span><p>Исследование маскирования аудиозаписей</p><a href="/process">К рабочей области</a></footer>
  </div>;
}

import { useEffect, useRef, useState } from 'react';

export function useTheme() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const manual = useRef(false);
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const applySystem = () => {
      if (!manual.current) setTheme(media.matches ? 'dark' : 'light');
    };
    applySystem();
    media.addEventListener('change', applySystem);
    return () => media.removeEventListener('change', applySystem);
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const toggle = () => {
    manual.current = true;
    setTheme((current) => current === 'dark' ? 'light' : 'dark');
  };
  return { theme, toggle };
}

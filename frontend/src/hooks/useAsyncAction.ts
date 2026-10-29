import { useEffect, useRef, useState } from 'react';

export function useAsyncAction<T>() {
  const [state, setState] = useState<{ loading: boolean; value: T | null; error: string }>({ loading: false, value: null, error: '' });
  const active = useRef(true);
  const request = useRef(0);
  const locked = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; request.current++; };
  }, []);
  const run = async (action: () => Promise<T>) => {
    if (locked.current) return;
    locked.current = true;
    const id = ++request.current;
    setState({ loading: true, value: null, error: '' });
    try {
      const value = await action();
      if (active.current && id === request.current) setState({ loading: false, value, error: '' });
    } catch {
      if (active.current && id === request.current) setState({ loading: false, value: null, error: 'Не удалось получить демонстрационный ответ. Повторите попытку.' });
    } finally {
      if (id === request.current) locked.current = false;
    }
  };
  return { ...state, run };
}

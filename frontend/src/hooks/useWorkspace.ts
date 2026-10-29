import { useEffect, useRef, useState } from 'react';
import type { AudioResult, DemoSettings, MaskingAdapter } from '../types/audio';

export function useWorkspace(adapter: MaskingAdapter) {
  const [source, setSource] = useState<File | null>(null);
  const [result, setResult] = useState<AudioResult | null>(null);
  const [view, setView] = useState<'form' | 'result'>('form');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const revision = useRef(0);
  useEffect(() => () => { revision.current++; }, []);

  const selectFiles = (files: FileList | readonly File[]) => {
    if (lock.current) return;
    if (files.length !== 1) {
      if (files.length > 1) setError('Выберите один аудиофайл за раз.');
      return;
    }
    const file = files[0];
    if (!file.size) { setError('Файл пуст. Выберите другую запись.'); return; }
    revision.current++;
    setSource(file); setResult(null); setView('form'); setError('');
  };
  const clear = () => {
    if (lock.current) return;
    revision.current++;
    setSource(null); setResult(null); setView('form'); setError('');
  };
  const run = async (settings: DemoSettings) => {
    if (lock.current || !source) return;
    if (!settings.enabled) {
      setError('Реальная обработка пока недоступна. Для проверки интерфейса включите демонстрацию.');
      return;
    }
    lock.current = true; setBusy(true); setError('');
    const request = ++revision.current;
    try {
      const response = await adapter.run(source, settings.masking);
      if (request !== revision.current) return;
      if (response.status === 'success') { setResult(response.value); setView('result'); }
      else setError(response.message);
    } catch {
      if (request === revision.current) setError('Не удалось показать демонстрационный результат. Повторите попытку.');
    } finally {
      if (request === revision.current) { lock.current = false; setBusy(false); }
    }
  };
  const showForm = () => { if (!lock.current) { setView('form'); setError(''); } };
  const showResult = () => { if (!lock.current && result) { setView('result'); setError(''); } };
  return { source, result, view, busy, error, selectFiles, clear, run, showForm, showResult };
}

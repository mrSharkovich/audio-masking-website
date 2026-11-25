import { useEffect, useRef, useState } from 'react';
import type { AudioResult, DemoSettings, MaskingAdapter, MaskingOptions } from '../types/audio';
import { isSupportedAudioFile, unsupportedAudioTitle } from '../types/audioUpload';

export function useWorkspace(adapter: MaskingAdapter) {
  const [source, setSource] = useState<File | null>(null);
  const [result, setResult] = useState<AudioResult | null>(null);
  const [view, setView] = useState<'form' | 'result'>('form');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const revision = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => { revision.current++; controller.current?.abort(); }, []);

  const selectFiles = (files: FileList | readonly File[]) => {
    if (lock.current) return;
    if (files.length !== 1) {
      if (files.length > 1) setError('Выберите один аудиофайл за раз.');
      return;
    }
    const file = files[0];
    if (!file.size) { setError('Файл пуст. Выберите другую запись.'); return; }
    if (!isSupportedAudioFile(file)) { setError(unsupportedAudioTitle); return; }
    revision.current++;
    setSource(file); setResult(null); setView('form'); setError('');
  };
  const clear = () => {
    if (lock.current) return;
    revision.current++;
    setSource(null); setResult(null); setView('form'); setError('');
  };
  const run = async (settings: DemoSettings, options?: MaskingOptions) => {
    if (lock.current || !source) return;
    if (!settings.enabled) {
      setError('Реальная обработка недоступна: сервис пока не подключён.');
      return;
    }
    lock.current = true; setBusy(true); setError('');
    const abort = new AbortController();
    controller.current = abort;
    const request = ++revision.current;
    const submittedOptions = options && { ...options };
    try {
      const response = await adapter.run(source, settings.masking, submittedOptions, abort.signal);
      if (request !== revision.current) return;
      if (response.status === 'success') { setResult(response.value); setView('result'); }
      else setError(response.message);
    } catch {
      if (request === revision.current) setError('Не удалось получить результат обработки. Повторите попытку.');
    } finally {
      if (request === revision.current) { controller.current = null; lock.current = false; setBusy(false); }
    }
  };
  const cancel = () => {
    if (!controller.current) return;
    revision.current++;
    controller.current.abort(); controller.current = null;
    lock.current = false; setBusy(false); setError('Запрос обработки отменён.');
  };
  const showForm = () => { if (!lock.current) { setView('form'); setError(''); } };
  const showResult = () => { if (!lock.current && result) { setView('result'); setError(''); } };
  return { source, result, view, busy, error, selectFiles, clear, run, cancel, showForm, showResult };
}

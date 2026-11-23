import { useRef, useState } from 'react';
import type { RefObject } from 'react';
import { AudioPlayer } from './AudioPlayer';
import { matrixSizes } from '../types/audio';
import type { MaskingOptions, MatrixSize } from '../types/audio';

interface Props {
  source: File | null;
  sourceUrl?: string;
  busy: boolean;
  error: string;
  hasResult: boolean;
  demoEnabled: boolean;
  options: MaskingOptions;
  onOptionsChange: (options: MaskingOptions) => void;
  onCancel: () => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onSelect: (files: FileList | readonly File[]) => void;
  onClear: () => void;
  onRun: () => void;
  onShowResult: () => void;
}
function sizeLabel(bytes: number) {
  return bytes < 1024 * 1024
    ? `${(bytes / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} КБ`
    : `${(bytes / (1024 * 1024)).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} МБ`;
}
function durationLabel(duration: number | null) {
  if (duration === null) return 'Длительность недоступна';
  const minutes = Math.floor(duration / 60);
  return `${minutes}:${Math.floor(duration % 60).toString().padStart(2, '0')}`;
}

export function UploadForm(props: Props) {
  const { source, sourceUrl, busy, error, onSelect } = props;
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [duration, setDuration] = useState<number | null>(null);
  const select = (files: FileList | readonly File[]) => { if (!busy) onSelect(files); };
  return <form className="upload-form" aria-label="Форма маскирования" onSubmit={(event) => { event.preventDefault(); if (!busy) props.onRun(); }}>
    <div className="section-heading">
      <div><span className="section-index" aria-hidden="true">01</span><h2 ref={props.headingRef} tabIndex={-1}>Исходная запись</h2></div>
      <span className="status-chip">{busy ? 'Тестовый запрос' : source ? 'Файл выбран' : 'Ожидает файл'}</span>
    </div>
    <div
      className={`dropzone${dragging && !busy ? ' is-dragging' : ''}${busy ? ' is-locked' : ''}`}
      data-testid="dropzone"
      aria-disabled={busy}
      onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = busy ? 'none' : 'copy'; if (!busy) setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); if (!busy) select(event.dataTransfer.files); }}
    >
      <svg className="upload-symbol" viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M24 31V8m0 0-8 8m8-8 8 8M10 29v10h28V29" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      <p className="drop-title">{busy ? 'Файл защищён от изменений' : 'Перетащите аудиозапись сюда'}</p>
      <p className="drop-caption">{busy ? 'Выбор, удаление и замена доступны после завершения.' : 'или выберите файл на устройстве'}</p>
      <input ref={input} id="audio-file" aria-label="Аудиофайл" className="visually-hidden" tabIndex={-1} type="file" disabled={busy}
        onChange={(event) => { if (event.currentTarget.files) select(event.currentTarget.files); event.currentTarget.value = ''; }} />
      <button className="button secondary" type="button" disabled={busy} onClick={() => { if (!busy) input.current?.click(); }}>{source ? 'Заменить файл' : 'Выбрать файл'}</button>
    </div>
    <p className="small-note">{props.demoEnabled ? 'Поддерживается WAV PCM. Файл отправляется локальному backend при запуске тестовой обработки или транскрибации.' : 'Файл остаётся в браузере до запуска транскрибации. Для ASR поддерживается WAV PCM.'}</p>
    {source ? <div className="file-summary" key={`${source.name}:${source.lastModified}:${source.size}`}>
      <div className="file-line"><div className="file-info"><strong>{source.name}</strong><span>{sizeLabel(source.size)} <span aria-hidden="true">·</span> {durationLabel(duration)}</span></div>
        <button type="button" className="text-button danger" disabled={busy} onClick={() => { if (!busy) props.onClear(); }}>Удалить файл</button>
      </div>
      <AudioPlayer label="Предпрослушивание исходной записи" url={sourceUrl} onDuration={setDuration} />
    </div> : null}
    <details className="parameters"><summary>Параметры маскирования <span aria-hidden="true">＋</span></summary>
      {props.demoEnabled ? <fieldset className="masking-fields" disabled={busy} aria-label="Параметры маскирования">
        <label>Тип маскирования
          <select value={props.options.mode} onChange={(event) => props.onOptionsChange({ ...props.options, mode: event.currentTarget.value as MaskingOptions['mode'] })}>
            <option value="one-sided">Одностороннее</option>
            <option value="two-sided">Двустороннее</option>
          </select>
        </label>
        <label>Размер матрицы маскирования <select value={props.options.matrix} onChange={(event) => props.onOptionsChange({ ...props.options, matrix: Number(event.currentTarget.value) as MatrixSize })}>
          {matrixSizes.map((size) => <option key={size} value={size}>{size}</option>)}
        </select></label>
      </fieldset> : <p>Настройки появятся после согласования подключения алгоритма. Сейчас параметры не задаются.</p>}
    </details>
    {error ? <p className="message error" role="alert">{error}</p> : null}
    <div className="form-actions">
      <button className="button primary" type="submit" disabled={!source || busy}>{busy ? 'Тестовая обработка…' : props.demoEnabled ? 'Запустить тестовую обработку' : 'Начать маскирование'}<span aria-hidden="true">↗</span></button>
      {busy ? <button className="button secondary" type="button" onClick={props.onCancel}>Отменить обработку</button> : null}
      {props.hasResult ? <button className="button secondary" type="button" disabled={busy} onClick={props.onShowResult}>Открыть текущий результат</button> : null}
    </div>
    <p className="operation-status" role="status">{busy ? 'Идёт обработка аудио…' : props.demoEnabled ? 'Параметры применяются только в тестовом сценарии.' : 'Реальная обработка недоступна: подключение ещё не настроено.'}</p>
  </form>;
}

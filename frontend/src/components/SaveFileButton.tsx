import { useState } from 'react';

type SavePicker = (options: {
  suggestedName: string;
  types: { description: string; accept: Record<string, string[]> }[];
}) => Promise<{ createWritable(): Promise<WritableStreamForFile> }>;

interface WritableStreamForFile {
  write(data: Blob): Promise<void>;
  close(): Promise<void>;
  abort?(): Promise<void>;
}

interface Props {
  label: string;
  filename: string;
  extension: '.md' | '.txt';
  disabled?: boolean;
  content?: () => string;
}

export function SaveFileButton({ label, filename, extension, disabled, content }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);

  async function save() {
    if (!content) return;
    setSaving(true);
    setError(false);
    const mime = extension === '.md' ? 'text/markdown' : 'text/plain';
    const picker = (window as Window & { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
    try {
      const data = new Blob([content()], { type: `${mime};charset=utf-8` });
      if (typeof picker === 'function') {
        const handle = await picker.call(window, { suggestedName: filename,
          types: [{ description: extension === '.md' ? 'Markdown' : 'Текстовый файл', accept: { [mime]: [extension] } }],
        });
        const file = await handle.createWritable();
        try {
          await file.write(data);
          await file.close();
        } catch (failure) {
          await file.abort?.().catch(() => {});
          throw failure;
        }
        return;
      }
      const url = URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.append(link);
      try {
        link.click();
      } finally {
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (failure) {
      if (!(failure instanceof DOMException && failure.name === 'AbortError')) setError(true);
    } finally {
      setSaving(false);
    }
  }

  return <div className="save-file-control">
    <button type="button" className="button secondary save-file-button" aria-label={label} title={label}
      disabled={disabled || saving || !content} onClick={() => { void save(); }}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <path d="M4 3h13l4 4v14H3V3h1Zm3 0v6h10V3M7 21v-7h10v7" />
      </svg>
    </button>
    {error ? <span className="visually-hidden" role="alert">Не удалось сохранить файл.</span> : null}
  </div>;
}

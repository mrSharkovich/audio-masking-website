import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { useState } from 'react';
import { TranscriptionPanel } from './TranscriptionPanel';
import { createHttpTranscriptionAdapter } from '../adapters/httpTranscription';
import { App } from '../App';
import { readBytes, syntheticWav } from '../test/audio';
import type { AsrMaskedAudio, AudioLanguage } from '../types/audio';

const response = (language: 'ru' | 'en', text: string) => new Response(JSON.stringify({ language, model: language === 'ru' ? 'gigaam-multi' : 'whisper', text }));

function panel(fetcher: typeof fetch, source = syntheticWav(), maskedResult?: AsrMaskedAudio) {
  const adapter = createHttpTranscriptionAdapter({ fetcher });
  function Harness() {
    const [language, setLanguage] = useState<AudioLanguage>('ru');
    return <TranscriptionPanel source={source} maskedResult={maskedResult} adapter={adapter} audioLanguage={language} onAudioLanguageChange={setLanguage} />;
  }
  return render(<Harness />);
}

it.each([['Русский', 'ru'], ['English', 'en']] as const)('shows real HTTP transcription for %s', async (label, language) => {
  const fetcher = vi.fn().mockResolvedValue(response(language, 'Ответ HTTP'));
  panel(fetcher);
  await userEvent.setup().click(screen.getByLabelText(label));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Ответ HTTP')).toBeInTheDocument();
  expect(fetcher.mock.calls[0][1].body.get('language')).toBe(language);
  expect(fetcher.mock.calls[0][1].body.has('model')).toBe(false);
  expect(screen.queryByText(/демонстрационный ответ/)).not.toBeInTheDocument();
});

it('sends original and actual masked file sequentially with one request at a time', async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }))
    .mockResolvedValueOnce(response('ru', 'Текст маскированной записи'));
  const source = syntheticWav('original.wav');
  const masked = syntheticWav('real-masked.wav');
  panel(fetcher, source, { audio: masked, fileName: masked.name, demonstration: false });
  fireEvent.click(screen.getByLabelText('Оба файла'));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  expect(fetcher.mock.calls[0][1].body.get('file').name).toBe(source.name);
  await act(async () => finish(response('ru', 'Текст оригинала')));
  expect(await screen.findByText('Текст маскированной записи')).toBeInTheDocument();
  expect(screen.getByText('Текст оригинала')).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[1][1].body.get('file').name).toBe(masked.name);
});

it('sends only actual masked file when selected', async () => {
  const fetcher = vi.fn().mockResolvedValue(response('ru', 'Текст результата'));
  const masked = syntheticWav('real-masked.wav');
  panel(fetcher, syntheticWav(), { audio: masked, fileName: masked.name, demonstration: false });
  fireEvent.click(screen.getByLabelText('Маскированное аудио'));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Текст результата')).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledOnce();
  expect(fetcher.mock.calls[0][1].body.get('file').name).toBe(masked.name);
  expect(await readBytes(fetcher.mock.calls[0][1].body.get('file'))).toEqual(await readBytes(masked));
});

it('keeps the original transcript when masked recognition fails', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response('ru', 'Сохранённый текст оригинала'))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'asr_unavailable' }, text: 'FAKE TEXT' }), { status: 503 }));
  panel(fetcher, syntheticWav(), { audio: syntheticWav(), fileName: 'real-masked.wav', demonstration: false });
  fireEvent.click(screen.getByLabelText('Оба файла'));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Локальная ASR-модель пока не подключена или недоступна.')).toBeInTheDocument();
  expect(screen.getByText('Сохранённый текст оригинала')).toBeInTheDocument();
  expect(screen.queryByText('FAKE TEXT')).not.toBeInTheDocument();
});

it('does not send a request without source audio', async () => {
  const fetcher = vi.fn();
  render(<TranscriptionPanel source={null} adapter={createHttpTranscriptionAdapter({ fetcher })} audioLanguage="ru" onAudioLanguageChange={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Выберите исходную аудиозапись.')).toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});

it.each([undefined, true] as const)('never substitutes source or demo audio for unavailable masked audio (%s)', async (demonstration) => {
  const fetcher = vi.fn().mockResolvedValue(response('ru', 'Текст оригинала'));
  panel(fetcher, syntheticWav(), demonstration ? { audio: syntheticWav(), fileName: 'demo.wav', demonstration } : undefined);
  fireEvent.click(screen.getByLabelText('Маскированное аудио'));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText(/Реальная маскированная запись отсутствует/)).toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText('Оба файла'));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Текст оригинала')).toBeInTheDocument();
  expect(screen.getByText(/Реальная маскированная запись отсутствует/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledOnce();
});

it('blocks duplicate clicks, cancels fetch and ignores late answers', async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }))
    .mockResolvedValueOnce(response('ru', 'Новый ответ'));
  panel(fetcher);
  const run = screen.getByRole('button', { name: 'Запустить транскрибацию' });
  fireEvent.click(run); fireEvent.click(run);
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  expect(screen.getByLabelText('English')).toBeDisabled();
  expect(screen.getByText('Ожидание ответа локального ASR…')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Отменить запрос' }));
  expect(screen.getByText('Запрос распознавания отменён.')).toBeInTheDocument();
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  await act(async () => finish(response('ru', 'Поздний ответ')));
  expect(screen.queryByText('Поздний ответ')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Новый ответ')).toBeInTheDocument();
});

it('aborts and clears results when source changes or panel unmounts', async () => {
  const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>(() => {}));
  const adapter = createHttpTranscriptionAdapter({ fetcher });
  const props = { adapter, audioLanguage: 'ru' as const, onAudioLanguageChange: () => {} };
  const view = render(<TranscriptionPanel {...props} source={syntheticWav('first.wav')} />);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  view.rerender(<TranscriptionPanel {...props} source={syntheticWav('second.wav')} />);
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
  expect(screen.queryByRole('button', { name: 'Отменить запрос' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  view.unmount();
  expect(fetcher.mock.calls[1][1]?.signal?.aborted).toBe(true);
});

it('uses default HTTP adapter in App and never shows fake text after a server error', async () => {
  window.history.replaceState(null, '', '/process');
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'asr_unavailable', message: 'private/path' }, text: 'FAKE TEXT' }), { status: 503 }));
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [syntheticWav()] } });
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Локальная ASR-модель пока не подключена или недоступна.')).toBeInTheDocument();
  expect(screen.queryByText('FAKE TEXT')).not.toBeInTheDocument();
  expect(screen.queryByText('private/path')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Копировать текст оригинала' })).not.toBeInTheDocument();
});

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { useState } from 'react';
import { TranscriptionPanel } from './TranscriptionPanel';
import { createHttpTranscriptionAdapter } from '../adapters/httpTranscription';
import { App } from '../App';
import { readBytes, syntheticWav } from '../test/audio';
import type { AsrMaskedAudio, AudioLanguage } from '../types/audio';

const response = (language: 'ru' | 'en', text: string) => new Response(JSON.stringify({ language, model: language === 'ru' ? 'gigaam-multi' : 'whisper', text }));
const sourceLabel = 'Исходная запись';
const maskedLabel = 'Маскированная запись';
const demaskedLabel = 'Демаскированная запись';
const result: AsrMaskedAudio = {
  audio: syntheticWav('masked.wav'), fileName: 'masked.wav', demonstration: false,
  masking: { demasked: syntheticWav('demasked.wav'), demaskedFileName: 'demasked.wav',
    options: { mode: 'two-sided', matrix: 64 }, appliedMatrix: 64 },
};

it.each(['', ' \t\n'])('shows blank completion and clears previous cycles on retry (%j)', async (text) => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response('ru', 'Предыдущий текст'))
    .mockResolvedValueOnce(response('ru', 'Текст другой записи'))
    .mockResolvedValueOnce(response('ru', text))
    .mockResolvedValueOnce(new Response('{}', { status: 502 }))
    .mockImplementationOnce(() => new Promise<Response>(() => {}));
  const user = userEvent.setup();
  panel(fetcher, syntheticWav(), result);
  const run = () => user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await user.click(screen.getByLabelText(maskedLabel));
  await run();
  expect(await screen.findByText('Текст другой записи')).toBeVisible();
  await user.click(screen.getByLabelText(maskedLabel));
  expect(screen.getByText('Текст другой записи')).toBeVisible();
  await run();
  const empty = await screen.findByText('Не удалось распознать речь');
  const card = within(empty.closest('article')!);
  expect(card.getByRole('heading', { name: 'Оригинал · Русский' })).toBeVisible();
  expect(card.getByText('Модель не смогла распознать текст в данной аудиозаписи.')).toBeVisible();
  expect(card.getByText('GigaAM-Multilingual CTC 220M')).toBeVisible();
  expect(card.getByRole('status')).toHaveClass('transcript-empty');
  expect(card.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.queryByText('Предыдущий текст')).not.toBeInTheDocument();
  expect(screen.queryByText(/Распознавание завершено без текста/)).not.toBeInTheDocument();
  await user.click(screen.getByLabelText('English'));
  expect(empty).toBeVisible();
  expect(screen.queryByText('Текст другой записи')).not.toBeInTheDocument();
  await user.click(screen.getByLabelText('Русский'));
  await run();
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось получить результат');
  expect(empty).not.toBeInTheDocument();
  await run();
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(5));
  await user.click(screen.getByRole('button', { name: 'Отменить запрос' }));
  expect(empty).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

function panel(fetcher: typeof fetch, source = syntheticWav(), maskedResult?: AsrMaskedAudio) {
  const adapter = createHttpTranscriptionAdapter({ fetcher });
  function Harness() {
    const [language, setLanguage] = useState<AudioLanguage>('ru');
    return <TranscriptionPanel source={source} maskedResult={maskedResult} adapter={adapter} audioLanguage={language} onAudioLanguageChange={setLanguage} />;
  }
  return render(<Harness />);
}

it('exports completed text, blank and failed attempts together, with the language and model', async () => {
  const write = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('showSaveFilePicker', vi.fn().mockResolvedValue({ createWritable: async () => ({ write, close: async () => {} }) }));
  let finish!: (value: Response) => void;
  const fetcher = vi.fn().mockResolvedValueOnce(response('ru', 'Текст первой записи'))
    .mockResolvedValueOnce(response('ru', ''))
    .mockImplementationOnce(() => new Promise<Response>((done) => { finish = done; }));
  panel(fetcher, syntheticWav(), result);
  const save = screen.getByRole('button', { name: 'Сохранить транскрипции' });
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByLabelText(maskedLabel));
  fireEvent.click(screen.getByLabelText(demaskedLabel));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(save).toBeDisabled();
  await act(async () => finish(new Response('{}', { status: 502 })));
  expect(save).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Копировать текст оригинала' })).toBeVisible();
  fireEvent.click(save);
  await waitFor(() => expect(write).toHaveBeenCalledOnce());
  const blob = write.mock.calls[0][0] as Blob;
  expect(blob.type).toBe('text/plain;charset=utf-8');
  const text = new TextDecoder().decode(await readBytes(blob));
  expect(text).toContain('Оригинал\nЯзык: Русский\nМодель: GigaAM-Multilingual CTC 220M\nТекст первой записи\n\n');
  expect(text).toContain('После маскирования\nЯзык: Русский\nМодель: GigaAM-Multilingual CTC 220M\nМодель не смогла распознать текст в данной аудиозаписи\n\n');
  expect(text).toContain('Демаскированное аудио\nЯзык: Русский\nМодель: GigaAM-Multilingual CTC 220M\nОшибка:');
  expect(fetcher).toHaveBeenCalledTimes(3);
});

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
  fireEvent.click(screen.getByLabelText(maskedLabel));
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
  fireEvent.click(screen.getByLabelText(sourceLabel));
  fireEvent.click(screen.getByLabelText(maskedLabel));
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
  fireEvent.click(screen.getByLabelText(maskedLabel));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Локальная ASR-модель пока не подключена или недоступна.')).toBeInTheDocument();
  expect(screen.getByText('Сохранённый текст оригинала')).toBeInTheDocument();
  expect(screen.queryByText('FAKE TEXT')).not.toBeInTheDocument();
});

it('does not send a request without source audio', async () => {
  const fetcher = vi.fn();
  render(<TranscriptionPanel source={null} adapter={createHttpTranscriptionAdapter({ fetcher })} audioLanguage="ru" onAudioLanguageChange={() => {}} />);
  expect(screen.getByRole('button', { name: 'Запустить транскрибацию' })).toBeDisabled();
  expect(fetcher).not.toHaveBeenCalled();
});

it.each([undefined, true] as const)('never substitutes source or demo audio for unavailable masked audio (%s)', async (demonstration) => {
  const fetcher = vi.fn().mockResolvedValue(response('ru', 'Текст оригинала'));
  panel(fetcher, syntheticWav(), demonstration ? { audio: syntheticWav(), fileName: 'demo.wav', demonstration } : undefined);
  expect(screen.getByLabelText(sourceLabel)).toBeChecked();
  expect(screen.getByLabelText(maskedLabel)).toBeDisabled();
  expect(screen.getByLabelText(demaskedLabel)).toBeDisabled();
  fireEvent.click(screen.getByLabelText(sourceLabel));
  expect(screen.getByRole('button', { name: 'Запустить транскрибацию' })).toBeDisabled();
  fireEvent.click(screen.getByLabelText(sourceLabel));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Текст оригинала')).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledOnce();
});

it('blocks duplicate clicks, cancels fetch and ignores late answers', async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }))
    .mockResolvedValueOnce(response('ru', 'Новый ответ'));
  panel(fetcher, syntheticWav(), result);
  fireEvent.click(screen.getByLabelText(maskedLabel));
  fireEvent.click(screen.getByLabelText(demaskedLabel));
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
  expect(fetcher).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByLabelText(maskedLabel));
  fireEvent.click(screen.getByLabelText(demaskedLabel));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Новый ответ')).toBeInTheDocument();
});

it('aborts and clears results when source changes or panel unmounts', async () => {
  const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>(() => {}));
  const adapter = createHttpTranscriptionAdapter({ fetcher });
  const props = { adapter, audioLanguage: 'ru' as const, onAudioLanguageChange: () => {} };
  const view = render(<TranscriptionPanel {...props} source={syntheticWav('first.wav')} maskedResult={result} />);
  fireEvent.click(screen.getByLabelText(sourceLabel));
  fireEvent.click(screen.getByLabelText(maskedLabel));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  view.rerender(<TranscriptionPanel {...props} source={syntheticWav('second.wav')} />);
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
  expect(screen.getByLabelText(sourceLabel)).toBeChecked();
  expect(screen.getByLabelText(maskedLabel)).not.toBeChecked();
  expect(screen.getByLabelText(demaskedLabel)).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Отменить запрос' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect((fetcher.mock.calls[1][1]?.body as FormData).get('file')).toHaveProperty('name', 'second.wav');
  view.unmount();
  expect(fetcher.mock.calls[1][1]?.signal?.aborted).toBe(true);
});

it.each([
  [[sourceLabel, demaskedLabel], ['original.wav', 'demasked.wav']],
  [[maskedLabel, demaskedLabel], ['masked.wav', 'demasked.wav']],
  [[sourceLabel, maskedLabel, demaskedLabel], ['original.wav', 'masked.wav', 'demasked.wav']],
])('recognizes each selected recording once and in order (%j)', async (labels, files) => {
  const transcribe = vi.fn(async (file: Blob) => ({ status: 'success', value: `Текст ${(file as File).name}` } as const));
  const user = userEvent.setup();
  render(<TranscriptionPanel source={syntheticWav('original.wav')} maskedResult={result}
    adapter={{ transcribe }} audioLanguage="en" onAudioLanguageChange={() => {}} />);
  expect(screen.getByLabelText(sourceLabel)).toBeChecked();
  expect(screen.getByLabelText(maskedLabel)).not.toBeChecked();
  expect(screen.getByLabelText(demaskedLabel)).not.toBeChecked();
  for (const label of [demaskedLabel, maskedLabel, sourceLabel]) {
    if (labels.includes(label) !== (label === sourceLabel)) await user.click(screen.getByLabelText(label));
  }
  await user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  for (const file of files) expect(await screen.findByText(`Текст ${file}`)).toBeInTheDocument();
  expect(transcribe.mock.calls.map(([file]) => (file as File).name)).toEqual(files);
  for (const file of files) expect(transcribe).toHaveBeenCalledWith(expect.objectContaining({ name: file }), 'en', expect.any(AbortSignal));
});

it('continues the ordered batch after a rejected middle request', async () => {
  const transcribe = vi.fn().mockResolvedValueOnce({ status: 'success', value: 'Оригинал распознан' })
    .mockRejectedValueOnce(new Error('internal'))
    .mockResolvedValueOnce({ status: 'success', value: 'Демаскированная запись распознана' });
  const source = syntheticWav();
  const props = { source, adapter: { transcribe }, audioLanguage: 'ru' as const, onAudioLanguageChange: () => {} };
  const view = render(<TranscriptionPanel {...props} maskedResult={result} />);
  fireEvent.click(screen.getByLabelText(maskedLabel));
  fireEvent.click(screen.getByLabelText(demaskedLabel));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Демаскированная запись распознана')).toBeInTheDocument();
  expect(screen.getByText('Оригинал распознан')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось выполнить распознавание');
  expect(transcribe).toHaveBeenCalledTimes(3);
  view.rerender(<TranscriptionPanel {...props} />);
  expect(screen.getByLabelText(maskedLabel)).not.toBeChecked();
  expect(screen.getByLabelText(demaskedLabel)).not.toBeChecked();
  expect(screen.getByText('Оригинал распознан')).toBeInTheDocument();
  expect(screen.queryByText('Демаскированная запись распознана')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('keeps results while changing settings and clears every previous result on launch', async () => {
  let finish!: (value: Response) => void;
  const fetcher = vi.fn().mockResolvedValueOnce(response('ru', 'Оригинал RU'))
    .mockResolvedValueOnce(response('ru', 'Маскированная RU'))
    .mockResolvedValueOnce(response('en', 'Оригинал EN'))
    .mockImplementationOnce(() => new Promise<Response>((done) => { finish = done; }))
    .mockResolvedValueOnce(response('en', 'Оригинал EN обновлён'));
  const user = userEvent.setup();
  panel(fetcher, syntheticWav(), result);
  const run = () => user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await user.click(screen.getByLabelText(maskedLabel));
  await run();
  expect(await screen.findByText('Маскированная RU')).toBeVisible();
  await user.click(screen.getByLabelText(maskedLabel));
  await user.click(screen.getByLabelText('English'));
  expect(screen.getByText('Оригинал RU')).toBeVisible();
  expect(screen.getByText('Маскированная RU')).toBeVisible();
  await run();
  expect(await screen.findByText('Оригинал EN')).toBeVisible();
  expect(screen.queryByText('Оригинал RU')).not.toBeInTheDocument();
  expect(screen.queryByText('Маскированная RU')).not.toBeInTheDocument();
  await run();
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4));
  expect(screen.queryByText('Оригинал EN')).not.toBeInTheDocument();
  await act(async () => finish(new Response('{}', { status: 502 })));
  const english = screen.getByRole('heading', { name: 'Оригинал · English' }).closest('article')!;
  expect(within(english).getByRole('alert')).toHaveTextContent('Не удалось получить результат');
  await run();
  expect(await screen.findByText('Оригинал EN обновлён')).toBeVisible();
  expect(screen.queryByText('Оригинал EN')).not.toBeInTheDocument();
  expect(screen.getAllByRole('heading', { name: 'Оригинал · English' })).toHaveLength(1);
  expect(screen.queryByText('Оригинал RU')).not.toBeInTheDocument();
  expect(screen.queryByText('Маскированная RU')).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('retains completed items on cancel and invalidates only replaced audio, including same-name files', async () => {
  let finish!: (value: { status: 'success'; value: string }) => void;
  const transcribe = vi.fn().mockResolvedValueOnce({ status: 'success', value: 'Исходный текст' })
    .mockResolvedValueOnce({ status: 'success', value: 'Маскированный текст' })
    .mockResolvedValueOnce({ status: 'success', value: 'Демаскированный текст' })
    .mockResolvedValueOnce({ status: 'success', value: 'Успел завершиться' })
    .mockImplementationOnce(() => new Promise((done) => { finish = done; }))
    .mockImplementationOnce(() => new Promise((done) => { finish = done; }));
  const props = { source: syntheticWav('same.wav'), adapter: { transcribe }, audioLanguage: 'ru' as const, onAudioLanguageChange: () => {} };
  const view = render(<TranscriptionPanel {...props} maskedResult={result} />);
  fireEvent.click(screen.getByLabelText(maskedLabel));
  fireEvent.click(screen.getByLabelText(demaskedLabel));
  const run = () => fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  run();
  expect(await screen.findByText('Демаскированный текст')).toBeVisible();
  run();
  await waitFor(() => expect(transcribe).toHaveBeenCalledTimes(5));
  fireEvent.click(screen.getByRole('button', { name: 'Отменить запрос' }));
  expect(transcribe.mock.calls[4][2].aborted).toBe(true);
  await act(async () => finish({ status: 'success', value: 'Отменённый ответ' }));
  expect(transcribe).toHaveBeenCalledTimes(5);
  expect(screen.getByText('Успел завершиться')).toBeVisible();
  for (const text of ['Маскированный текст', 'Демаскированный текст']) expect(screen.queryByText(text)).not.toBeInTheDocument();
  expect(screen.queryByText('Отменённый ответ')).not.toBeInTheDocument();

  fireEvent.click(screen.getByLabelText(sourceLabel));
  run();
  await waitFor(() => expect(transcribe).toHaveBeenCalledTimes(6));
  const replaced = { ...result, audio: syntheticWav('masked.wav') };
  view.rerender(<TranscriptionPanel {...props} maskedResult={replaced} />);
  expect(transcribe.mock.calls[5][2].aborted).toBe(true);
  await act(async () => finish({ status: 'success', value: 'Ответ для старой копии' }));
  expect(transcribe).toHaveBeenCalledTimes(6);
  expect(screen.queryByText('Ответ для старой копии')).not.toBeInTheDocument();
  expect(screen.queryByText('Маскированный текст')).not.toBeInTheDocument();
  expect(screen.queryByText('Демаскированный текст')).not.toBeInTheDocument();
  expect(screen.queryByText('Успел завершиться')).not.toBeInTheDocument();

  view.rerender(<TranscriptionPanel {...props} source={syntheticWav('same.wav')} />);
  expect(screen.getByLabelText(sourceLabel)).toBeChecked();
  expect(screen.queryByText('Успел завершиться')).not.toBeInTheDocument();
  expect(screen.queryByText('Демаскированный текст')).not.toBeInTheDocument();
});

it('uses default HTTP adapter in App and never shows fake text after a server error', async () => {
  window.history.replaceState(null, '', '/process');
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'asr_unavailable', message: 'private/path' }, text: 'FAKE TEXT' }), { status: 503 }));
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [syntheticWav()] } });
  expect(fetcher).toHaveBeenCalledExactlyOnceWith('/api/masking/status', expect.objectContaining({ cache: 'no-store' }));
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Локальная ASR-модель пока не подключена или недоступна.')).toBeInTheDocument();
  expect(screen.queryByText('FAKE TEXT')).not.toBeInTheDocument();
  expect(screen.queryByText('private/path')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Копировать текст оригинала' })).not.toBeInTheDocument();
});

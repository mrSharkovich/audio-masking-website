import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AudioAdapters } from './types/audio';
import { maskingTestNotice } from './types/audio';
import { readBytes, syntheticWav } from './test/audio';

beforeEach(() => {
  window.history.replaceState(null, '', '/process');
  window.scrollTo = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
});

it('navigates pages and history, keeps the theme and resets it on a fresh mount', async () => {
  window.history.replaceState(null, '', '/');
  const user = userEvent.setup();
  const view = render(<App />);
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Маскирование аудиозаписей');
  await user.click(screen.getByRole('button', { name: 'Тёмная тема' }));
  await user.click(screen.getByRole('link', { name: 'Начать обработку' }));
  expect(window.location.pathname).toBe('/process');
  expect(screen.getByLabelText('Аудиофайл')).toBeInTheDocument();
  for (const [name, path] of [['Как это работает', '/how-it-works'], ['О проекте', '/about'], ['Главная', '/']]) {
    await user.click(within(screen.getByRole('navigation')).getByRole('link', { name }));
    expect(window.location.pathname).toBe(path);
    expect(within(screen.getByRole('navigation')).getByRole('link', { name })).toHaveAttribute('aria-current', 'page');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(screen.queryByLabelText('Аудиофайл')).not.toBeInTheDocument();
  }
  act(() => {
    window.history.replaceState(null, '', '/about');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('О проекте');
  view.unmount();
  render(<App />);
  expect(document.documentElement.dataset.theme).toBe('light');
});

it('links to metric explanations without resetting theme and keeps the brand text only', async () => {
  window.history.replaceState(null, '', '/');
  render(<App />);
  const user = userEvent.setup();
  const brand = screen.getByRole('link', { name: 'AudioMask — на главную' });
  expect(brand).toHaveTextContent('AudioMask');
  expect(brand.querySelector('svg, img')).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Тёмная тема' }));
  await user.click(screen.getByRole('link', { name: 'Подробнее об оценке качества' }));
  expect(window.location.pathname + window.location.hash).toBe('/how-it-works#quality');
  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(screen.getByRole('heading', { name: 'Оценка качества аудио' })).toBeInTheDocument();
  expect(screen.getByText(/16 кГц \(16 000 Гц\)/)).toBeInTheDocument();
  expect(screen.getByText(/не универсальное ограничение/)).toBeInTheDocument();
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
});

function adapters(): AudioAdapters {
  return {
    masking: { run: vi.fn().mockResolvedValue({ status: 'success', value: { id: 'demo-result', audio: new Blob(['independent tone']), fileName: 'demo-not-masked.wav', demonstration: true } }) },
    quality: { evaluate: vi.fn().mockResolvedValue({ PESQ: { status: 'success', value: 3.2 }, ViSQOL: { status: 'unavailable', message: 'Demo unavailable' } }) },
    transcription: { transcribe: vi.fn().mockResolvedValue({ status: 'unavailable', message: 'Локальная транскрибация пока не подключена.' }) },
  } satisfies AudioAdapters;
}
const selectFile = (name = 'synthetic.audio') => fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [new File(['test fixture'], name)] } });

it('removes demo controls and workspace labels and reports unavailable operations', async () => {
  const services = adapters();
  const user = userEvent.setup();
  render(<App adapters={services} />);
  expect(screen.queryByText('Демонстрационные сценарии')).not.toBeInTheDocument();
  expect(screen.queryByText('Рабочая область')).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'К рабочей области' })).not.toBeInTheDocument();
  expect(screen.queryByText('Демонстрационный режим')).not.toBeInTheDocument();
  expect(screen.getByText('Сервис не подключён')).toBeInTheDocument();
  selectFile();
  await user.click(screen.getByRole('button', { name: /Начать маскирование/ }));
  expect(screen.getByRole('alert')).toHaveTextContent('Реальная обработка недоступна: сервис пока не подключён.');
  expect(screen.getByText('synthetic.audio')).toBeInTheDocument();
  expect(screen.getByLabelText('Предпрослушивание исходной записи')).toHaveAttribute('controls');
  expect(screen.queryByRole('heading', { name: 'Результат демонстрации' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Скачать/ })).not.toBeInTheDocument();
  await user.click(screen.getByLabelText('English'));
  await user.click(screen.getByLabelText('Оба файла'));
  await user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Локальная транскрибация пока не подключена.')).toBeInTheDocument();
  expect(screen.getByText(/Реальная маскированная запись отсутствует/)).toBeInTheDocument();
  expect(services.masking.run).not.toHaveBeenCalled();
  expect(services.quality.evaluate).not.toHaveBeenCalled();
  expect(services.transcription.transcribe).toHaveBeenCalledTimes(1);
  expect(services.transcription.transcribe).toHaveBeenCalledWith(expect.any(File), 'en', expect.any(AbortSignal));
  await user.click(screen.getByRole('button', { name: 'Удалить файл' }));
  expect(screen.queryByText('synthetic.audio')).not.toBeInTheDocument();
});

it('preserves language and theme through navigation and resets language on fresh mount', async () => {
  const user = userEvent.setup();
  const view = render(<App />);
  expect(screen.getByLabelText('Русский')).toBeChecked();
  await user.click(screen.getByLabelText('English'));
  expect(screen.getByText(/Модель:/)).toHaveTextContent('Whisper small multilingual');
  await user.click(screen.getByRole('button', { name: 'Тёмная тема' }));
  await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'О проекте' }));
  expect(screen.queryByText('К рабочей области')).not.toBeInTheDocument();
  await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'Обработка' }));
  expect(screen.getByLabelText('English')).toBeChecked();
  expect(document.documentElement.dataset.theme).toBe('dark');
  view.unmount();
  render(<App />);
  expect(screen.getByLabelText('Русский')).toBeChecked();
  expect(screen.getByText(/Модель:/)).toHaveTextContent('GigaAM-Multilingual CTC 220M');
});

it.each(['test', 'real'] as const)('processes %s results, plays both files and transcribes the demasked WAV', async (backendMode) => {
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  const test = backendMode === 'test';
  const prefix = test ? 'test-' : '';
  const notice = test ? maskingTestNotice : null;
  const source = syntheticWav();
  const bytes = new Uint8Array(await readBytes(source));
  const base64 = btoa(String.fromCharCode(...bytes));
  const fetcher = vi.fn<typeof fetch>(async (url) => {
    if (url === '/api/masking/status') return Response.json({ available: true, test_mode: test, notice });
    if (url === '/api/asr/transcribe') return Response.json({ model: 'gigaam-multi', language: 'ru', text: 'Текст тестовой копии' });
    if (url === '/api/quality/status') return Response.json({
      metrics: { PESQ: { status: 'available' }, ViSQOL: { status: 'available' }, ViSQOL_LATTICE: { status: 'unavailable' } },
    });
    if (url === '/api/quality/evaluate') return Response.json({ comparisons: {
      masked: { PESQ: { status: 'success', value: 4.321 }, ViSQOL: { status: 'success', value: 3.2 },
        ViSQOL_LATTICE: { status: 'unavailable', message: 'Модель недоступна.' } },
    } });
    return Response.json({
      test_mode: test, masking_performed: !test, notice, mode: 'one-sided',
      selected_matrix: 128, applied_matrix: 64,
      masked: { file_name: `${prefix}masked.wav`, media_type: 'audio/wav', base64 },
      demasked: { file_name: `${prefix}demasked.wav`, media_type: 'audio/wav', base64 },
    });
  });
  vi.stubGlobal('fetch', fetcher);
  const user = userEvent.setup();
  render(<App />);
  expect(await screen.findByText(test ? maskingTestNotice : 'Маскирование доступно')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [source] } });
  await user.click(screen.getByText('Параметры маскирования', { exact: false }));
  const parameters = within(screen.getByRole('group', { name: 'Параметры маскирования' }));
  const mode = parameters.getByRole('combobox', { name: 'Тип маскирования' });
  const matrix = parameters.getByRole('combobox', { name: 'Размер матрицы маскирования' });
  expect(parameters.getAllByRole('combobox')).toEqual([mode, matrix]);
  expect(parameters.queryByRole('radio')).not.toBeInTheDocument();
  expect(parameters.queryByText('Тестовые параметры')).not.toBeInTheDocument();
  expect(within(mode).getAllByRole('option').map((item) => item.textContent)).toEqual(['Одностороннее', 'Двустороннее']);
  expect(within(matrix).getAllByRole('option').map((item) => item.textContent)).toEqual(['4', '8', '16', '32', '64', '128', '256', '512']);
  expect(mode).toHaveValue('two-sided');
  expect(matrix).toHaveValue('64');
  await user.selectOptions(mode, 'one-sided');
  await user.selectOptions(matrix, '128');
  await user.click(screen.getByRole('button', { name: test ? /Запустить тестовую обработку/ : /Начать маскирование/ }));
  expect(await screen.findByRole('heading', { name: test ? 'Результат тестовой обработки' : 'Результат обработки' })).toBeInTheDocument();
  if (!test) expect(screen.queryByText(maskingTestNotice)).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Оценка качества аудио' })).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url === '/api/quality/evaluate')).toBe(false);
  const form = fetcher.mock.calls[1][1]?.body as FormData;
  expect(fetcher.mock.calls[1][0]).toBe('/api/masking/process');
  expect(form.get('file')).toBe(source);
  expect(form.get('mode')).toBe('one-sided');
  expect(form.get('matrix')).toBe('128');
  expect(screen.getByText(/уменьшен с 128 до 64/)).toBeInTheDocument();
  expect(screen.getByText(/Выбранный размер матрицы: 128. Применённый размер( в тестовом режиме)?: 64/)).toBeInTheDocument();
  const recording = screen.getByRole('combobox', { name: 'Аудиозапись' });
  expect(recording).toHaveValue('original');
  await user.selectOptions(recording, 'masked');
  expect(screen.getByLabelText('Маскированное аудио', { selector: 'audio' })).toHaveAttribute('controls');
  expect(screen.getByRole('link', { name: 'Скачать аудио' })).toHaveAttribute('download', 'fixture-masked.wav');
  if (test) expect(screen.getByText('Тестовая маскированная копия')).toBeInTheDocument();
  else expect(screen.queryByText('Тестовая маскированная копия')).not.toBeInTheDocument();
  await user.selectOptions(recording, 'demasked');
  expect(screen.getByLabelText('Демаскированное аудио', { selector: 'audio' })).toHaveAttribute('controls');
  expect(screen.getByRole('link', { name: 'Скачать аудио' })).toHaveAttribute('download', 'fixture-demasked.wav');
  if (test) expect(screen.getByText('Тестовая демаскированная копия')).toBeInTheDocument();
  else expect(screen.queryByText('Тестовая демаскированная копия')).not.toBeInTheDocument();
  await user.selectOptions(recording, 'original');
  await user.click(screen.getByRole('radio', { name: test ? 'Тестовый демаскированный WAV' : 'Демаскированное аудио' }));
  await user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Текст тестовой копии')).toBeInTheDocument();
  const asrForm = fetcher.mock.calls.find(([url]) => url === '/api/asr/transcribe')?.[1]?.body as FormData;
  expect((asrForm.get('file') as File).name).toBe(`${prefix}demasked.wav`);
  expect(new Uint8Array(await readBytes(asrForm.get('file') as File))).toEqual(bytes);
  await user.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(await screen.findByText('4,321')).toBeInTheDocument();
  expect(screen.getByText('3,2')).toBeInTheDocument();
  expect(screen.getByText('Недоступно')).toBeInTheDocument();
  const qualityForm = fetcher.mock.calls.find(([url]) => url === '/api/quality/evaluate')?.[1]?.body as FormData;
  expect([...qualityForm.keys()]).toEqual(['pairs', 'original', 'masked']);
  expect(qualityForm.getAll('pairs')).toEqual(['masked']);
  for (const file of [qualityForm.get('original'), qualityForm.get('masked')]) {
    expect(new Uint8Array(await readBytes(file as File))).toEqual(bytes);
  }
  await user.click(screen.getByRole('button', { name: 'Вернуться к форме' }));
  await user.click(screen.getByText('Параметры маскирования', { exact: false }));
  expect(screen.getByRole('combobox', { name: 'Тип маскирования' })).toBeEnabled();
  expect(screen.getByRole('combobox', { name: 'Размер матрицы маскирования' })).toHaveValue('128');
});

it('cancels an active masking request and never renders a late result', async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>((url) => url === '/api/masking/status'
    ? Promise.resolve(Response.json({ test_mode: true, notice: maskingTestNotice }))
    : new Promise((resolve) => { finish = resolve; }));
  vi.stubGlobal('fetch', fetcher);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText(maskingTestNotice);
  selectFile('fixture.wav');
  await user.click(screen.getByText('Параметры маскирования', { exact: false }));
  await user.click(screen.getByRole('button', { name: /Запустить тестовую обработку/ }));
  const form = screen.getByRole('form', { name: 'Форма маскирования' });
  expect(within(form).getByRole('status')).toHaveTextContent('Идёт обработка аудио…');
  expect(screen.getByLabelText('Аудиофайл')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Заменить файл' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Удалить файл' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: 'Тип маскирования' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: 'Размер матрицы маскирования' })).toBeDisabled();
  expect(screen.getByRole('button', { name: /Тестовая обработка…/ })).toBeDisabled();
  fireEvent.submit(form);
  fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [syntheticWav('replacement.wav')] } });
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(screen.queryByText('replacement.wav')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Отменить обработку' }));
  expect(fetcher.mock.calls[1][1]?.signal?.aborted).toBe(true);
  await act(async () => { finish(Response.json({ test_mode: true })); });
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Запрос обработки отменён'));
  expect(screen.queryByRole('heading', { name: 'Результат тестовой обработки' })).not.toBeInTheDocument();
  expect(screen.getByText('fixture.wav')).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Тип маскирования' })).toBeEnabled();
});

it('aborts the old request on navigation and leaves the new workspace usable', async () => {
  const services = adapters();
  const late = await services.masking.run(syntheticWav(), 'success');
  const run = vi.fn<AudioAdapters['masking']['run']>();
  let resolve!: (value: typeof late) => void;
  run.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  run.mockResolvedValueOnce({ status: 'error', message: 'Ошибка тестовой обработки.' });
  services.masking = { available: async () => 'test', run };
  const user = userEvent.setup();
  render(<App adapters={services} />);
  await screen.findByText(maskingTestNotice);
  selectFile('old.wav');
  await user.click(screen.getByRole('button', { name: /Запустить тестовую обработку/ }));
  await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'О проекте' }));
  expect(run.mock.calls[0][3]?.aborted).toBe(true);
  await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'Обработка' }));
  await screen.findByText(maskingTestNotice);
  selectFile('current.wav');
  await user.click(screen.getByRole('button', { name: /Запустить тестовую обработку/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Ошибка тестовой обработки.');
  await act(async () => { resolve(late); });
  expect(screen.getByText('current.wav')).toBeInTheDocument();
  expect(screen.queryByText('old.wav')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Результат демонстрации' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Запустить тестовую обработку/ })).toBeEnabled();
});


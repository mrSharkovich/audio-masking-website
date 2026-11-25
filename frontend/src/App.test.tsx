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
const selectFile = (name = 'synthetic.wav') => fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [syntheticWav(name)] } });
const testBanner = 'Маскирование работает в тестовом режиме';
const expectStages = (...stages: string[]) => {
  expect([...document.querySelectorAll('.workspace-content .section-index')].map((number) =>
    `${number.textContent} ${number.nextElementSibling?.textContent}`)).toEqual(stages);
};
const resultStages = (title = 'Результат обработки') =>
  ['01 Исходная запись', `02 ${title}`, '03 Оценка качества аудио', '04 Транскрибация'];
const formStages = resultStages();

it('shows all four stages and only the waiting messages before masking', () => {
  render(<App adapters={adapters()} />);
  expectStages(...formStages);
  const result = within(screen.getByRole('region', { name: 'Результат обработки' }));
  const quality = within(screen.getByRole('region', { name: 'Оценка качества аудио' }));
  expect(result.getByText('Результаты появятся после маскирования')).toBeVisible();
  expect(quality.getByText('Сначала выполните маскирование')).toBeVisible();
  expect(quality.queryByRole('button', { name: 'Оценить качество' })).not.toBeInTheDocument();
  expect(result.queryByRole('combobox')).not.toBeInTheDocument();
});

it('rejects non-audio chooser and drop inputs before accepting a valid WAV', async () => {
  const services = adapters();
  services.masking.available = async () => 'real';
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ metrics: {} })));
  render(<App adapters={services} />);
  await screen.findByText('Маскирование доступно');
  const input = screen.getByLabelText('Аудиофайл');
  const accept = input.getAttribute('accept')?.split(',');
  for (const extension of ['wav', 'mp3', 'm4a', 'flac', 'ogg', 'aac', 'aiff', 'amr', 'ac3', 'eac3', 'au', 'mka', 'mkv', 'webm']) {
    expect(accept).toContain(`.${extension}`);
  }
  expect(accept).not.toContain('.pdf');
  for (const [name, type] of [['paper.pdf', 'application/pdf'], ['image.png', 'image/png'],
    ['letter.docx', ''], ['files.zip', 'application/octet-stream'], ['paper.wav', 'application/pdf']]) {
    fireEvent.change(input, { target: { files: [new File(['fixture'], name, { type })] } });
    expect(screen.getByRole('alert')).toHaveTextContent('Неподдерживаемый формат файла');
    expect(screen.getByRole('alert')).toHaveTextContent('Загрузите аудиозапись в поддерживаемом формате');
  }
  fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [new File(['%PDF-1.7'], 'drop.pdf')] } });
  expect(screen.getByRole('alert')).toHaveTextContent('Неподдерживаемый формат файла');
  expect(screen.getByText('Параметры маскирования', { exact: false }).closest('details')).not.toHaveAttribute('open');
  expect(screen.queryByLabelText('Предпрослушивание исходной записи')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Начать маскирование/ })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Запустить транскрибацию' })).toBeDisabled();
  expect(services.masking.run).not.toHaveBeenCalled();
  expect(services.transcription.transcribe).not.toHaveBeenCalled();
  fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [syntheticWav('valid.WAV')] } });
  expect(screen.getByLabelText('Предпрослушивание исходной записи')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Начать маскирование/ })).toBeEnabled();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it.each([['SONG.MP3', 'audio/mpeg'], ['x.m4a', ''], ['x.flac', 'application/octet-stream'],
  ['x.OGG', 'application/ogg'], ['x.aiff', 'audio/x-aiff'], ['x.MKA', 'audio/x-matroska'],
  ['x.webm', 'video/webm'], ['x.mkv', 'video/x-matroska'], ['x.amr', ''], ['x.ec3', 'audio/eac3'],
])('accepts supported audio metadata %s (%s)', (name, type) => {
  render(<App adapters={adapters()} />);
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [new File(['fixture'], name, { type })] } });
  expect(screen.getByText(name)).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it.each([true, false])('reports the actual metric availability in test mode (all ready: %s)', async (allReady) => {
  const fetcher = vi.fn<typeof fetch>(async (url) => url === '/api/masking/status'
    ? Response.json({ test_mode: true, notice: maskingTestNotice })
    : Response.json({ metrics: { PESQ: { status: 'available' }, ViSQOL: { status: 'available' },
      ViSQOL_LATTICE: { status: allReady ? 'available' : 'unavailable' } } }));
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  expect(await screen.findByText(testBanner)).toBeInTheDocument();
  expect(await screen.findByText(allReady ? 'Оценка качества доступна. Настоящее маскирование пока не выполняется.'
    : 'Доступна часть метрик оценки качества. Настоящее маскирование пока не выполняется.')).toBeInTheDocument();
  expect(screen.queryByText(/оценка качества пока недоступны|распознавание речи доступно/i)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/masking/status', '/api/quality/status']);
});

it('reports an unreachable backend without asserting metric or ASR readiness', async () => {
  const fetcher = vi.fn().mockRejectedValue(new Error('offline'));
  vi.stubGlobal('fetch', fetcher);
  render(<App />);
  await act(async () => {});
  expect(screen.getByText('Локальный backend недоступен или маскирование в нём не подключено.')).toBeInTheDocument();
  expect(screen.queryByText(/оценка качества доступна|распознавание речи доступно/i)).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledOnce();
});

it('opens parameters for each accepted file and preserves manual toggling on re-render', async () => {
  const user = userEvent.setup();
  render(<App adapters={adapters()} />);
  const summary = screen.getByText('Параметры маскирования', { exact: false });
  const details = summary.closest('details');
  const indicator = summary.querySelector('.parameters-indicator');
  expectStages(...formStages);
  expect(indicator).toHaveAttribute('aria-hidden', 'true');
  expect(summary).not.toHaveTextContent(/[＋+]/);
  expect(details).not.toHaveAttribute('open');
  expect(summary).toHaveAttribute('aria-expanded', 'false');
  selectFile('first.wav');
  expect(details).toHaveAttribute('open');
  expectStages(...formStages);
  expect(summary).toHaveAttribute('aria-expanded', 'true');
  summary.focus();
  await user.keyboard('{Enter}');
  expect(details).not.toHaveAttribute('open');
  expect(summary).toHaveAttribute('aria-expanded', 'false');
  expect(summary.querySelector('.parameters-indicator')).toBe(indicator);
  expectStages(...formStages);
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [new File([], 'empty.wav')] } });
  expect(screen.getByRole('alert')).toHaveTextContent('Файл пуст');
  await user.click(screen.getByLabelText('English'));
  expect(details).not.toHaveAttribute('open');
  await user.click(summary);
  expect(details).toHaveAttribute('open');
  await user.click(summary);
  selectFile('second.wav');
  expect(details).toHaveAttribute('open');
});

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
  expect(screen.getByText('synthetic.wav')).toBeInTheDocument();
  expect(screen.getByLabelText('Предпрослушивание исходной записи')).toHaveAttribute('controls');
  expect(screen.queryByRole('heading', { name: 'Результат демонстрации' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Скачать/ })).not.toBeInTheDocument();
  await user.click(screen.getByLabelText('English'));
  expect(screen.getByLabelText('Маскированная запись')).toBeDisabled();
  expect(screen.getByLabelText('Демаскированная запись')).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Локальная транскрибация пока не подключена.')).toBeInTheDocument();
  expect(services.masking.run).not.toHaveBeenCalled();
  expect(services.quality.evaluate).not.toHaveBeenCalled();
  expect(services.transcription.transcribe).toHaveBeenCalledTimes(1);
  expect(services.transcription.transcribe).toHaveBeenCalledWith(expect.any(File), 'en', expect.any(AbortSignal));
  await user.click(screen.getByRole('button', { name: 'Удалить файл' }));
  expect(screen.queryByText('synthetic.wav')).not.toBeInTheDocument();
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
  expect(await screen.findByText(test ? testBanner : 'Маскирование доступно')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [source] } });
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
  expectStages(...resultStages(test ? 'Результат тестовой обработки' : 'Результат обработки'));
  expect(screen.queryByText('Результаты появятся после маскирования')).not.toBeInTheDocument();
  expect(screen.queryByText('Сначала выполните маскирование')).not.toBeInTheDocument();
  if (!test) expect(screen.queryByText(maskingTestNotice)).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Оценка качества аудио' })).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url === '/api/quality/evaluate')).toBe(false);
  const form = fetcher.mock.calls.find(([url]) => url === '/api/masking/process')?.[1]?.body as FormData;
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
  await user.click(screen.getByLabelText('Исходная запись', { selector: 'input' }));
  await user.click(screen.getByLabelText('Демаскированная запись'));
  await user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  expect(await screen.findByText('Текст тестовой копии')).toBeInTheDocument();
  const asrForm = fetcher.mock.calls.find(([url]) => url === '/api/asr/transcribe')?.[1]?.body as FormData;
  expect((asrForm.get('file') as File).name).toBe(`${prefix}demasked.wav`);
  expect(new Uint8Array(await readBytes(asrForm.get('file') as File))).toEqual(bytes);
  await user.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(await screen.findByText('4,321')).toBeInTheDocument();
  expectStages(...resultStages(test ? 'Результат тестовой обработки' : 'Результат обработки'));
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/quality/status')).toHaveLength(1);
  expect(screen.getByText('3,2')).toBeInTheDocument();
  expect(screen.getByText('Недоступно')).toBeInTheDocument();
  const qualityForm = fetcher.mock.calls.find(([url]) => url === '/api/quality/evaluate')?.[1]?.body as FormData;
  expect([...qualityForm.keys()]).toEqual(['pairs', 'original', 'masked']);
  expect(qualityForm.getAll('pairs')).toEqual(['masked']);
  for (const file of [qualityForm.get('original'), qualityForm.get('masked')]) {
    expect(new Uint8Array(await readBytes(file as File))).toEqual(bytes);
  }
  await user.click(screen.getByRole('button', { name: 'Вернуться к форме' }));
  expect(screen.getByRole('combobox', { name: 'Тип маскирования' })).toBeEnabled();
  expect(screen.getByRole('combobox', { name: 'Размер матрицы маскирования' })).toHaveValue('128');
});

it('cancels an active masking request and never renders a late result', async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>((url) => url === '/api/masking/status'
    ? Promise.resolve(Response.json({ test_mode: true, notice: maskingTestNotice }))
    : url === '/api/quality/status' ? Promise.resolve(Response.json({ metrics: {} }))
    : new Promise((resolve) => { finish = resolve; }));
  vi.stubGlobal('fetch', fetcher);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText(testBanner);
  selectFile('fixture.wav');
  await user.click(screen.getByRole('button', { name: /Запустить тестовую обработку/ }));
  const form = screen.getByRole('form', { name: 'Форма маскирования' });
  expect(within(form).getByRole('status')).toHaveTextContent('Идёт обработка аудио…');
  expectStages(...formStages);
  expect(screen.getByLabelText('Аудиофайл')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Заменить файл' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Удалить файл' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: 'Тип маскирования' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: 'Размер матрицы маскирования' })).toBeDisabled();
  expect(screen.getByRole('button', { name: /Тестовая обработка…/ })).toBeDisabled();
  fireEvent.submit(form);
  fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [syntheticWav('replacement.wav')] } });
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/masking/process')).toHaveLength(1);
  expect(screen.queryByText('replacement.wav')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Отменить обработку' }));
  expect(fetcher.mock.calls.find(([url]) => url === '/api/masking/process')?.[1]?.signal?.aborted).toBe(true);
  await act(async () => { finish(Response.json({ test_mode: true })); });
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Запрос обработки отменён'));
  expectStages(...formStages);
  expect(screen.queryByRole('heading', { name: 'Результат тестовой обработки' })).not.toBeInTheDocument();
  expect(screen.getByText('fixture.wav')).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Тип маскирования' })).toBeEnabled();
});

it('preserves transcripts across tools and masking attempts until the recording actually changes', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  vi.stubGlobal('fetch', vi.fn<typeof fetch>(async (url) => url === '/api/quality/status'
    ? Response.json({ metrics: { PESQ: { status: 'available' }, ViSQOL: { status: 'available' }, ViSQOL_LATTICE: { status: 'available' } } })
    : Response.json({ comparisons: { masked: { PESQ: { status: 'success', value: 4 } } } })));
  const services = adapters();
  const processed = {
    id: 'first', audio: syntheticWav('masked.wav'), fileName: 'masked.wav', demonstration: false,
    masking: { demasked: syntheticWav('demasked.wav'), demaskedFileName: 'demasked.wav',
      options: { mode: 'two-sided', matrix: 64 }, appliedMatrix: 64 },
  } as const;
  const run = vi.fn<AudioAdapters['masking']['run']>()
    .mockResolvedValueOnce({ status: 'success', value: processed })
    .mockResolvedValueOnce({ status: 'error', message: 'Повторная обработка не удалась.' })
    .mockResolvedValueOnce({ status: 'success', value: { ...processed, id: 'second', audio: syntheticWav('masked.wav') } });
  services.masking = { available: async () => 'real', run };
  services.transcription.transcribe = vi.fn<AudioAdapters['transcription']['transcribe']>(
    async (file) => ({ status: 'success', value: `Текст: ${(file as File).name}` }),
  );
  const user = userEvent.setup();
  render(<App adapters={services} />);
  await screen.findByText('Маскирование доступно');
  const upload = () => fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [syntheticWav('same.wav')] } });
  const mask = () => user.click(screen.getByRole('button', { name: /Начать маскирование/ }));
  const asr = () => user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  upload();
  await asr();
  expect(await screen.findByText('Текст: same.wav')).toBeVisible();
  await mask();
  expect(await screen.findByRole('heading', { name: 'Результат обработки' })).toBeVisible();
  expect(screen.getByText('Текст: same.wav')).toBeVisible();
  await user.click(screen.getByLabelText('Маскированная запись'));
  await user.click(screen.getByLabelText('Демаскированная запись'));
  await asr();
  expect(await screen.findByText('Текст: demasked.wav')).toBeVisible();
  await user.selectOptions(screen.getByRole('combobox', { name: 'Аудиозапись' }), 'masked');
  await user.click(screen.getByLabelText('Исходная ↔ Демаскированная'));
  await user.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(await screen.findByText('Высокое качество')).toBeVisible();
  expect(screen.getByText('Текст: masked.wav')).toBeVisible();

  await user.click(screen.getByRole('button', { name: 'Вернуться к форме' }));
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [new File(['%PDF-1.7'], 'replacement.pdf')] } });
  expect(screen.getByRole('alert')).toHaveTextContent('Неподдерживаемый формат файла');
  expect(screen.getByText('Текст: same.wav')).toBeVisible();
  expect(screen.getByText('Текст: masked.wav')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Открыть текущий результат' }));
  expectStages(...resultStages());
  await user.click(screen.getByRole('button', { name: 'Вернуться к форме' }));
  const currentSummary = screen.getByText('Параметры маскирования', { exact: false });
  await user.click(currentSummary);
  await user.click(currentSummary);
  await user.selectOptions(screen.getByLabelText('Размер матрицы маскирования'), '128');
  expect(screen.getByText('Текст: masked.wav')).toBeVisible();
  await mask();
  expect(await screen.findByText('Повторная обработка не удалась.')).toBeVisible();
  expectStages(...formStages);
  expect(screen.getByText('Оценка доступна в текущем результате.')).toBeVisible();
  expect(screen.getByText('Текст: masked.wav')).toBeVisible();
  await mask();
  expect(await screen.findByRole('heading', { name: 'Результат обработки' })).toBeVisible();
  expectStages(...resultStages());
  expect(screen.queryByText('Текст: masked.wav')).not.toBeInTheDocument();
  expect(screen.getByText('Текст: same.wav')).toBeVisible();
  expect(screen.getByText('Текст: demasked.wav')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Вернуться к форме' }));
  upload();
  expectStages(...formStages);
  expect(screen.queryByText('Текст: same.wav')).not.toBeInTheDocument();
  expect(screen.queryByText('Текст: demasked.wav')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Исходная запись', { selector: 'input' })).toBeChecked();
  expect(screen.getByLabelText('Маскированная запись')).toBeDisabled();
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
  await screen.findByText(testBanner);
  selectFile('old.wav');
  await user.click(screen.getByRole('button', { name: /Запустить тестовую обработку/ }));
  await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'О проекте' }));
  expect(run.mock.calls[0][3]?.aborted).toBe(true);
  await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'Обработка' }));
  await screen.findByText(testBanner);
  selectFile('current.wav');
  await user.click(screen.getByRole('button', { name: /Запустить тестовую обработку/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Ошибка тестовой обработки.');
  await act(async () => { resolve(late); });
  expect(screen.getByText('current.wav')).toBeInTheDocument();
  expect(screen.queryByText('old.wav')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Результат демонстрации' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Запустить тестовую обработку/ })).toBeEnabled();
});


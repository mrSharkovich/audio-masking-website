import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';
import type { AudioAdapters } from './types/audio';

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


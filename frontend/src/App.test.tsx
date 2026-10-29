import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { App } from './App';
import type { AudioAdapters, AudioResult, OperationValue } from './types/audio';

function adapters(): AudioAdapters {
  return {
    masking: { run: vi.fn().mockResolvedValue({ status: 'success', value: { id: 'demo-result', audio: new Blob(['independent tone']), fileName: 'demo-not-masked.wav', demonstration: true } }) },
    quality: { evaluate: vi.fn().mockResolvedValue({ PESQ: { status: 'success', value: 3.2 }, ViSQOL: { status: 'unavailable', message: 'Demo unavailable' } }) },
    transcription: { transcribe: vi.fn().mockResolvedValue({ original: { status: 'success', value: 'Тестовый текст' } }) },
  } satisfies AudioAdapters;
}
const selectFile = (name = 'synthetic.audio') => fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [new File(['test fixture'], name)] } });

it('offers a visible keyboard file action without an invisible focus stop', async () => {
  render(<App adapters={adapters()} />);
  expect(screen.getByLabelText('Аудиофайл')).toHaveAttribute('tabindex', '-1');
  const choose = screen.getByRole('button', { name: 'Выбрать файл' });
  choose.focus();
  expect(choose).toHaveFocus();
  await userEvent.setup().tab();
  expect(screen.getByLabelText('Аудиофайл')).not.toHaveFocus();
});

it('replaces form with two native players, preserves result and starts extra operations only explicitly', async () => {
  const services = adapters();
  const user = userEvent.setup();
  render(<App adapters={services} />);
  selectFile(); await user.click(screen.getByRole('button', { name: /Начать маскирование/ }));
  await screen.findByRole('heading', { name: 'Результат демонстрации' });
  expect(screen.queryByRole('form', { name: 'Форма маскирования' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('Оригинал')).toHaveAttribute('controls');
  expect(screen.getByLabelText('После маскирования')).toHaveAttribute('controls');
  expect(screen.getByRole('button', { name: 'Скачать обработанное аудио' })).toBeDisabled();
  expect(services.quality.evaluate).not.toHaveBeenCalled(); expect(services.transcription.transcribe).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Оценить качество' }));
  expect(await screen.findByText('Демонстрационное значение, не расчёт')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Вернуться к форме' }));
  expect(screen.queryByLabelText('После маскирования')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Открыть текущий результат' }));
  expect(services.masking.run).toHaveBeenCalledTimes(1);
});

it('blocks input, deletion, drop and duplicate launch while masking', async () => {
  let finish!: (value: OperationValue<AudioResult>) => void;
  const services = adapters();
  services.masking.run = vi.fn(() => new Promise<OperationValue<AudioResult>>((resolve) => { finish = resolve; }));
  render(<App adapters={services} />);
  selectFile('original.audio');
  fireEvent.click(screen.getByRole('button', { name: /Начать маскирование/ }));
  expect(screen.getByLabelText('Аудиофайл')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Удалить файл' })).toBeDisabled();
  fireEvent.drop(screen.getByTestId('dropzone'), { dataTransfer: { files: [new File(['other'], 'other.audio')] } });
  fireEvent.submit(screen.getByRole('form', { name: 'Форма маскирования' }));
  expect(screen.queryByText('other.audio')).not.toBeInTheDocument();
  expect(services.masking.run).toHaveBeenCalledTimes(1);
  await act(async () => finish({ status: 'error', message: 'Test error' }));
  expect(screen.getByLabelText('Аудиофайл')).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Удалить файл' })).toBeEnabled();
});

it('passes both transcription sources and keeps result available on copy failure', async () => {
  const services = adapters();
  render(<App adapters={services} />);
  const user = userEvent.setup();
  selectFile(); await user.click(screen.getByRole('button', { name: /Начать маскирование/ }));
  await screen.findByRole('heading', { name: 'Результат демонстрации' });
  await user.click(screen.getByLabelText('Оба файла'));
  await user.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  await screen.findByText('Тестовый текст');
  expect(services.transcription.transcribe).toHaveBeenCalledWith('demo-result', 'both', 'success');
  vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Denied'));
  await user.click(screen.getByRole('button', { name: 'Копировать текст оригинала' }));
  expect(await screen.findByText(/Выделите текст/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Скачать демонстрационный файл' })).toBeEnabled();
});

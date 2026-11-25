import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ProcessPage } from './ProcessPage';
import { syntheticWav } from '../test/audio';
import type { AudioAdapters } from '../types/audio';

async function renderStub() {
  const run = vi.fn<AudioAdapters['masking']['run']>().mockResolvedValue({ status: 'error', message: 'Ответ заглушки' });
  const adapters: AudioAdapters = {
    masking: { available: async () => 'test', run },
    quality: { evaluate: vi.fn() },
    transcription: { transcribe: vi.fn() },
  };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ metrics: {} })));
  render(<ProcessPage adapters={adapters} audioLanguage="ru" onAudioLanguageChange={vi.fn()} />);
  await screen.findByText('Маскирование работает в тестовом режиме');
  return run;
}

function choose(file: File) {
  fireEvent.change(screen.getByLabelText('Аудиофайл'), { target: { files: [file] } });
}

it.each(['mp3', 'm4a', 'flac', 'ogg'])('uses an uncertain browser estimate for %s', async (extension) => {
  await renderStub();
  choose(new File(['metadata fixture'], 'fixture.' + extension));
  expect(screen.getByText(/Пока не удалось определить число отсчётов/)).toBeVisible();
  expect(screen.getByRole('button', { name: /Запустить тестовую обработку/ })).toBeEnabled();
  const player = screen.getByLabelText('Предпрослушивание исходной записи');
  Object.defineProperty(player, 'duration', { value: 0.01 });
  fireEvent.loadedMetadata(player);
  expect(screen.getByText(/По оценке браузера минимальный достаточный размер — 16/)).toHaveTextContent(
    'Точное число подготовленных отсчётов может отличаться.',
  );
});

it('updates the warning and submits the unchanged matrix to the stub', async () => {
  const user = userEvent.setup();
  const run = await renderStub();
  const wave = syntheticWav();
  choose(wave);
  const matrix = screen.getByRole('combobox', { name: 'Размер матрицы маскирования' });
  const warning = /Минимальный достаточный размер — 128/;
  await user.selectOptions(matrix, '256');
  expect(await screen.findByText(warning)).toHaveTextContent('вычислительную нагрузку');
  await user.selectOptions(matrix, '128');
  expect(screen.queryByText(warning)).not.toBeInTheDocument();
  await user.selectOptions(matrix, '256');
  choose(new File(['unknown duration'], 'replacement.ogg'));
  expect(screen.queryByText(warning)).not.toBeInTheDocument();
  expect(screen.getByText(/Пока не удалось определить число отсчётов/)).toBeVisible();
  expect(matrix).toHaveValue('256');
  choose(wave);
  expect(await screen.findByText(warning)).toBeVisible();
  const submit = screen.getByRole('button', { name: /Запустить тестовую обработку/ });
  expect(submit).toBeEnabled();
  await user.click(submit);
  expect(run).toHaveBeenCalledWith(wave, 'unavailable', { mode: 'two-sided', matrix: 256 }, expect.any(AbortSignal));
  expect(await screen.findByRole('alert')).toHaveTextContent('Ответ заглушки');
});

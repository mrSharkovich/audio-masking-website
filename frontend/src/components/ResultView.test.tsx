import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { ResultView } from './ResultView';
import { createDemoAdapters } from '../adapters/demoAudio';
import { syntheticWav } from '../test/audio';
import { maskingTestNotice } from '../types/audio';
import type { AudioResult } from '../types/audio';

function fixture() {
  const source = syntheticWav('original.wav');
  const masked = syntheticWav('masked.wav');
  const demasked = syntheticWav('demasked.wav');
  const details = { options: { mode: 'two-sided', matrix: 64 }, appliedMatrix: 16, demasked,
    demaskedFileName: demasked.name } as const;
  const result: AudioResult = { id: 'first', audio: masked, fileName: masked.name, demonstration: true, testMasking: details };
  return { result, details, source, masked, demasked };
}

function view(result: AudioResult, source: File) {
  const adapters = { ...createDemoAdapters(), transcription: { transcribe: vi.fn() } };
  return <ResultView result={result} source={source} adapters={adapters}
    settings={{ enabled: false, masking: 'unavailable', quality: 'unavailable', transcription: 'unavailable' }}
    audioLanguage="ru" onAudioLanguageChange={vi.fn()} headingRef={{ current: null }} onForm={vi.fn()} onNew={vi.fn()} />;
}

it('plays and downloads only the selected file, pauses old players, and resets for a new result', async () => {
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  const { result, source, masked, demasked } = fixture();
  const urls = new Map([[source, 'blob:original'], [masked, 'blob:masked'], [demasked, 'blob:demasked']]);
  vi.mocked(URL.createObjectURL).mockImplementation((file) => urls.get(file as File) ?? 'blob:unexpected');
  const user = userEvent.setup();
  const { container, rerender, unmount } = render(view(result, source));
  const selector = screen.getByRole('combobox', { name: 'Аудиозапись' });
  expect(selector).toHaveValue('original');
  expect(screen.getByText(maskingTestNotice)).toBeInTheDocument();
  expect(screen.getByText(/Выбранный размер матрицы: 64.*: 16/)).toBeInTheDocument();
  const expectTrack = (title: string, file: File, name = file.name) => {
    const audio = screen.getByLabelText<HTMLAudioElement>(title, { selector: 'audio' });
    expect(container.querySelectorAll('audio')).toHaveLength(1);
    expect(audio).toHaveAttribute('src', urls.get(file));
    expect(audio.currentTime).toBe(0);
    expect(screen.getByText(name)).toBeVisible();
    const download = screen.getByRole('link', { name: 'Скачать аудио' });
    expect(download).toHaveAttribute('download', name);
    expect(download).toHaveAttribute('href', urls.get(file));
    expect(download).toHaveAttribute('title', 'Скачать аудио');
    expect(download.compareDocumentPosition(audio) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    return audio;
  };
  const first = expectTrack('Оригинал', source);
  first.currentTime = 3;
  await user.selectOptions(selector, 'masked');
  const second = expectTrack('Маскированное аудио', masked, 'original-masked.wav');
  second.currentTime = 2;
  expect(pause.mock.contexts).toContain(first);
  expect(first).not.toBeInTheDocument();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:original');
  expect(screen.getByText('Тестовая маскированная копия')).toBeInTheDocument();
  await user.selectOptions(selector, 'demasked');
  const third = expectTrack('Демаскированное аудио', demasked, 'original-demasked.wav');
  expect(pause.mock.contexts).toContain(second);
  expect(screen.getByText('Тестовая демаскированная копия')).toBeInTheDocument();
  rerender(view({ ...result, id: 'next' }, source));
  expect(screen.getByRole('combobox', { name: 'Аудиозапись' })).toHaveValue('original');
  const newest = expectTrack('Оригинал', source);
  expect(pause.mock.contexts).toContain(third);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:demasked');
  unmount();
  expect(pause.mock.contexts).toContain(newest);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:masked');
});

it('shows real tracks without test labels and leaves a missing result unavailable', async () => {
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  const { result, details, source } = fixture();
  const real = { ...result, demonstration: false, testMasking: undefined, masking: { ...details, demasked: new Blob() } };
  const { container } = render(view(real, source));
  const user = userEvent.setup();
  const selector = screen.getByRole('combobox', { name: 'Аудиозапись' });
  expect(screen.getByRole('heading', { name: 'Результат обработки' })).toBeInTheDocument();
  await user.selectOptions(selector, 'masked');
  expect(screen.getByLabelText('Маскированное аудио', { selector: 'audio' })).toBeInTheDocument();
  const download = screen.getByRole('link', { name: 'Скачать аудио' });
  expect(download).toHaveAttribute('download', 'original-masked.wav');
  const activate = vi.fn((event: Event) => event.preventDefault());
  download.addEventListener('click', activate);
  selector.focus();
  await user.tab();
  expect(download).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(activate).toHaveBeenCalledOnce();
  expect(screen.queryByText(maskingTestNotice)).not.toBeInTheDocument();
  expect(screen.queryByText('Тестовая маскированная копия')).not.toBeInTheDocument();
  await user.selectOptions(selector, 'demasked');
  expect(screen.getByText('Выбранная запись недоступна.')).toBeVisible();
  expect(container.querySelector('audio')).toBeNull();
  expect(screen.queryByLabelText('Скачать аудио')).not.toBeInTheDocument();
  expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
});

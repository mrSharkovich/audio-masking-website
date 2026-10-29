import { act, fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { QualityPanel } from './QualityPanel';
import { TranscriptionPanel } from './TranscriptionPanel';
import type { DemoSettings, QualityResult, TranscriptionResult } from '../types/audio';

const settings: DemoSettings = { enabled: true, masking: 'success', quality: 'success', transcription: 'success' };

it('does not display a late quality result after switching the result version', async () => {
  let finish!: (value: QualityResult) => void;
  const adapter = { evaluate: vi.fn(() => new Promise<QualityResult>((resolve) => { finish = resolve; })) };
  const { rerender } = render(<QualityPanel key="old" resultId="old" adapter={adapter} settings={settings} />);
  fireEvent.click(screen.getByRole('button', { name: 'Оценить качество' }));
  rerender(<QualityPanel key="new" resultId="new" adapter={adapter} settings={settings} />);
  await act(async () => finish({ PESQ: { status: 'success', value: 4.321 }, ViSQOL: { status: 'success', value: 4.321 } }));
  expect(screen.queryByText('4,321')).not.toBeInTheDocument();
  expect(screen.getAllByText('Не запрошено')).toHaveLength(2);
  expect(adapter.evaluate).toHaveBeenCalledTimes(1);
});

it('does not display a late transcript after leaving the old result', async () => {
  let finish!: (value: TranscriptionResult) => void;
  const adapter = { transcribe: vi.fn(() => new Promise<TranscriptionResult>((resolve) => { finish = resolve; })) };
  const { rerender } = render(<TranscriptionPanel key="old" resultId="old" adapter={adapter} settings={settings} />);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить транскрибацию' }));
  rerender(<TranscriptionPanel key="new" resultId="new" adapter={adapter} settings={settings} />);
  await act(async () => finish({ original: { status: 'success', value: 'Old delayed text' } }));
  expect(screen.queryByText('Old delayed text')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Запустить транскрибацию' })).toBeEnabled();
  expect(adapter.transcribe).toHaveBeenCalledTimes(1);
});

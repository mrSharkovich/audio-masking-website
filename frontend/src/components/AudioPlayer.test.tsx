import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { AudioPlayer } from './AudioPlayer';

it('reports unavailable playback without inventing duration', () => {
  const duration = vi.fn();
  render(<AudioPlayer label="Оригинал" url="blob:fixture" onDuration={duration} />);
  const audio = screen.getByLabelText('Оригинал');
  expect(audio).toHaveAttribute('controls');
  fireEvent.error(audio);
  expect(screen.getByRole('alert')).toHaveTextContent('не смог воспроизвести');
  expect(duration).toHaveBeenLastCalledWith(null);
});

it('reports the actual loaded metadata duration and ignores non-finite duration', () => {
  const duration = vi.fn();
  render(<AudioPlayer label="Оригинал" url="blob:fixture" onDuration={duration} />);
  const audio = screen.getByLabelText('Оригинал');
  Object.defineProperty(audio, 'duration', { configurable: true, value: 12.75 });
  fireEvent.loadedMetadata(audio);
  expect(duration).toHaveBeenLastCalledWith(12.75);
  Object.defineProperty(audio, 'duration', { configurable: true, value: Infinity });
  fireEvent.loadedMetadata(audio);
  expect(duration).toHaveBeenLastCalledWith(null);
});

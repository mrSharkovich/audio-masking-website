import { expect, it } from 'vitest';
import { matrixSizes } from './audio';
import { minimumMatrixSize, readPreparedPcmSamples } from './matrixCapacity';
import { syntheticWav } from '../test/audio';

it.each(matrixSizes)('uses %i at its exact capacity and moves to the next size above it', (size) => {
  const capacity = size * size;
  expect(minimumMatrixSize(capacity - 1)).toBe(size);
  expect(minimumMatrixSize(capacity)).toBe(size);
  expect(minimumMatrixSize(capacity + 1)).toBe(matrixSizes[matrixSizes.indexOf(size) + 1]);
});

it('uses the smallest matrix for one sample', () => {
  expect(minimumMatrixSize(1)).toBe(4);
});

it('counts frames after normalizing a PCM WAV from 8 to 16 kHz', async () => {
  const { signal } = new AbortController();
  expect(await readPreparedPcmSamples(syntheticWav(), signal)).toBe(16000);
});

it('does not infer an exact sample count from the extension alone', async () => {
  const { signal } = new AbortController();
  expect(await readPreparedPcmSamples(new File(['invalid audio'], 'fixture.wav'), signal)).toBeNull();
});

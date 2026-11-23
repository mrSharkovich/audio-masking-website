import { expect, it } from 'vitest';
import { audioDownloadName } from './audioDownloadName';

it.each([
  ['recording.wav', 'recording.wav', 'recording'],
  ['Моя запись.mp3', 'Моя запись.mp3', 'Моя запись'],
  ['voice.test.wav', 'voice.test.wav', 'voice.test'],
  ['без расширения', 'без расширения', 'без расширения'],
  ['.hidden', '.hidden', '.hidden'],
  ['voice.', 'voice.', 'voice.'],
  ['../sub\\голос\u0000\n\u007f\u202E.wav', '.._sub_голос____.wav', '.._sub_голос____'],
  ['..', 'audio', 'audio'],
  ['', 'audio', 'audio'],
])('generates safe download names for %j', (source, original, base) => {
  expect(audioDownloadName(source, 'original')).toBe(original);
  expect(audioDownloadName(source, 'masked')).toBe(`${base}-masked.wav`);
  expect(audioDownloadName(source, 'demasked')).toBe(`${base}-demasked.wav`);
});

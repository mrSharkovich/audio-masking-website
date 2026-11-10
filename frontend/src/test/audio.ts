import { createDemoTone } from '../adapters/demoAudio';

// Independent synthetic PCM WAV; no recordings, transcripts, or dataset assets.
export const syntheticWav = (name = 'fixture.wav') => new File([createDemoTone()], name, { type: 'audio/wav' });
export const readBytes = (blob: Blob) => new Promise<ArrayBuffer>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result as ArrayBuffer);
  reader.onerror = reject;
  reader.readAsArrayBuffer(blob);
});

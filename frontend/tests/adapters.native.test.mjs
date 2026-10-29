import assert from 'node:assert/strict';
import test from 'node:test';
import { createDemoAdapters, createDemoTone } from '../src/adapters/demoAudio.ts';

test('demo masking produces a separate synthetic WAV, never the source', async () => {
  const source = new File(['synthetic-source'], 'fixture.audio');
  const adapters = createDemoAdapters(0);
  const response = await adapters.masking.run(source, 'success');
  assert.equal(response.status, 'success');
  assert.notEqual(response.value.audio, source);
  assert.equal(response.value.demonstration, true);
  assert.match(response.value.fileName, /demo.*not-masked/);
  const bytes = new Uint8Array(await response.value.audio.arrayBuffer());
  assert.equal(new TextDecoder().decode(bytes.slice(0, 4)), 'RIFF');
  assert.equal(new TextDecoder().decode(bytes.slice(8, 12)), 'WAVE');
  assert.notDeepEqual(bytes, new Uint8Array(await source.arrayBuffer()));
  assert.equal(response.value.audio.size, createDemoTone().size);
  const second = await adapters.masking.run(source, 'success');
  assert.notEqual(response.value.id, second.value.id);
});

test('explicit error/unavailable and independent quality results', async () => {
  const adapters = createDemoAdapters(0);
  const source = new File(['fixture'], 'fixture.audio');
  assert.equal((await adapters.masking.run(source, 'error')).status, 'error');
  assert.equal((await adapters.masking.run(source, 'unavailable')).status, 'unavailable');
  const partial = await adapters.quality.evaluate('demo', 'partial');
  assert.equal(partial.PESQ.status, 'success');
  assert.equal(partial.ViSQOL.status, 'unavailable');
  assert.equal((await adapters.quality.evaluate('demo', 'error')).PESQ.status, 'error');
});

test('transcription only returns selected sources and supports empty/partial', async () => {
  const adapter = createDemoAdapters(0).transcription;
  assert.deepEqual(Object.keys(await adapter.transcribe('demo', 'original', 'success')), ['original']);
  assert.deepEqual(Object.keys(await adapter.transcribe('demo', 'masked', 'success')), ['masked']);
  const partial = await adapter.transcribe('demo', 'both', 'partial');
  assert.equal(partial.original.status, 'success');
  assert.equal(partial.masked.status, 'unavailable');
  assert.equal((await adapter.transcribe('demo', 'original', 'empty')).original.status, 'empty');
});

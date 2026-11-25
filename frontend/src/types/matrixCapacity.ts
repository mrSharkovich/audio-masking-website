import { matrixSizes } from './audio';

const preparedRate = 16000;

export function minimumMatrixSize(samples: number) {
  return matrixSizes.find((size) => size * size >= samples);
}

export function estimatePreparedSamples(duration: number) {
  return Math.ceil(duration * preparedRate);
}

function readHeader(file: File, offset: number, length: number): Promise<DataView> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new DataView(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file.slice(offset, offset + length));
  });
}

export async function readPreparedPcmSamples(file: File, signal: AbortSignal): Promise<number | null> {
  const header = await readHeader(file, 0, 12);
  if (header.byteLength !== 12 || header.getUint32(0) !== 0x52494646 // RIFF
      || header.getUint32(8) !== 0x57415645 // WAVE
      || header.getUint32(4, true) + 8 !== file.size) return null;

  let format: { rate: number; frameBytes: number } | undefined;
  let dataBytes: number | undefined;
  let offset = 12;
  // Bound local header reads. Unusual layouts can still use media metadata.
  for (let chunks = 0; chunks < 128 && offset < file.size && !signal.aborted; chunks++) {
    const chunk = await readHeader(file, offset, 8);
    if (chunk.byteLength !== 8) return null;
    const kind = chunk.getUint32(0);
    const length = chunk.getUint32(4, true);
    const next = offset + 8 + length + length % 2;
    if (next > file.size) return null;
    if (kind === 0x666d7420) { // fmt
      if (format || length < 16) return null;
      const pcm = await readHeader(file, offset + 8, 16);
      const channels = pcm.getUint16(2, true);
      const rate = pcm.getUint32(4, true);
      const bits = pcm.getUint16(14, true);
      const frameBytes = channels * bits / 8;
      if (pcm.getUint16(0, true) !== 1 || (channels !== 1 && channels !== 2)
          || rate < 8000 || rate > 192000 || ![8, 16, 24, 32].includes(bits)
          || pcm.getUint16(12, true) !== frameBytes) return null;
      format = { rate, frameBytes };
    } else if (kind === 0x64617461) { // data
      if (!format || dataBytes !== undefined) return null;
      dataBytes = length;
    }
    offset = next;
  }
  if (signal.aborted || offset !== file.size || !format || !dataBytes || dataBytes % format.frameBytes) return null;
  // Downmix preserves frame count. Polyphase resampling rounds output length up.
  return Math.ceil((dataBytes / format.frameBytes) * preparedRate / format.rate);
}

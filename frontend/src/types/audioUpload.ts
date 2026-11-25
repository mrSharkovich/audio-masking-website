// Extensions and browser MIME types for the enabled FFmpeg audio demuxers.
const extensions = [
  'wav', 'wave', 'mp3', 'mp2', 'mp1', 'mpa', 'mpga', 'm4a', 'm4b', 'm4p', 'mp4', 'm4v', 'mov', 'qt', '3gp', '3g2',
  'flac', 'ogg', 'oga', 'ogx', 'opus', 'spx', 'aac', 'adts', 'aiff', 'aif', 'aifc', 'amr', 'awb', 'ac3', 'eac3', 'ec3',
  'au', 'snd', 'mka', 'mkv', 'mk3d', 'webm', 'weba',
];
const mimeTypes = [
  'audio/wav', 'audio/wave', 'audio/x-wav', 'audio/vnd.wave', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/m4a',
  'audio/x-m4a', 'application/mp4', 'video/mp4', 'video/x-m4v', 'video/quicktime', 'audio/quicktime',
  'audio/3gpp', 'audio/3gpp2', 'video/3gpp', 'video/3gpp2', 'audio/flac', 'audio/x-flac', 'audio/ogg',
  'application/ogg', 'application/x-ogg', 'video/ogg', 'audio/opus', 'audio/speex', 'audio/aac', 'audio/x-aac', 'audio/aiff', 'audio/x-aiff',
  'audio/amr', 'audio/amr-wb', 'audio/ac3', 'audio/ac-3', 'audio/eac3', 'audio/eac-3', 'audio/basic',
  'audio/webm', 'video/webm', 'audio/matroska', 'audio/x-matroska', 'video/matroska', 'video/x-matroska',
  'application/matroska', 'application/x-matroska',
];
const supportedExtensions = new Set(extensions);
const supportedMimeTypes = new Set(mimeTypes);

export const audioAccept = [...extensions.map((extension) => `.${extension}`), ...mimeTypes].join(',');
export const unsupportedAudioTitle = 'Неподдерживаемый формат файла';
export const unsupportedAudioDescription = 'Загрузите аудиозапись в поддерживаемом формате: WAV, MP3, M4A, FLAC, OGG, AAC или другом поддерживаемом аудиоформате.';

export function isSupportedAudioFile(file: File) {
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf('.');
  const mime = file.type.toLowerCase();
  if (dot < 0) return supportedMimeTypes.has(mime);
  return supportedExtensions.has(name.slice(dot + 1))
    && (!mime || mime === 'application/octet-stream' || mime.startsWith('audio/') || supportedMimeTypes.has(mime));
}

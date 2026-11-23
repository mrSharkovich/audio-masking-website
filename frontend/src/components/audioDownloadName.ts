export function audioDownloadName(sourceName: string, recording: 'original' | 'masked' | 'demasked'): string {
  const safeName = sourceName.replace(/[/\\\p{Cc}\p{Bidi_Control}]/gu, '_');
  const name = !safeName.trim() || safeName === '.' || safeName === '..' ? 'audio' : safeName;
  if (recording === 'original') return name;

  const dot = name.lastIndexOf('.');
  const base = dot > 0 && dot < name.length - 1 ? name.slice(0, dot) : name;
  return `${base}-${recording}.wav`;
}

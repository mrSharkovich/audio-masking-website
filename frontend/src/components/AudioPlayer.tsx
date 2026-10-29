import { useEffect, useState } from 'react';

interface Props {
  label: string;
  url?: string;
  onDuration?: (duration: number | null) => void;
}

export function AudioPlayer({ label, url, onDuration }: Props) {
  const [failedUrl, setFailedUrl] = useState<string | undefined>();
  useEffect(() => { onDuration?.(null); }, [url, onDuration]);
  return <div className="player-block">
    <span className="player-label">{label}</span>
    <audio
      key={url}
      aria-label={label}
      controls
      preload="metadata"
      src={url}
      onLoadedMetadata={(event) => {
        const value = event.currentTarget.duration;
        onDuration?.(Number.isFinite(value) ? value : null);
      }}
      onError={() => { setFailedUrl(url); onDuration?.(null); }}
    />
    {url && failedUrl === url ? <p className="field-error" role="alert">Браузер не смог воспроизвести запись. Это не определяет поддержку формата будущим сервисом.</p> : null}
  </div>;
}

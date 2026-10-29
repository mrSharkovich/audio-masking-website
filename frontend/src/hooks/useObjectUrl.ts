import { useEffect, useState } from 'react';

export function useObjectUrl(blob: Blob | null): string | undefined {
  const [resource, setResource] = useState<{ blob: Blob; url: string } | null>(null);
  useEffect(() => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    setResource({ blob, url });
    return () => URL.revokeObjectURL(url);
  }, [blob]);
  return resource?.blob === blob ? resource.url : undefined;
}

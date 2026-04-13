import { useEffect, useState, useRef } from 'react';
import type { EventLogEntry } from '../types';

type IndexedEntry = EventLogEntry & { _seq: number };

export function useEventLog(urls: string[]) {
  const [entries, setEntries] = useState<EventLogEntry[]>([]);
  const seqRef = useRef(0);

  useEffect(() => {
    const sources = urls.map((url) => {
      const es = new EventSource(url);
      es.onmessage = (e) => {
        try {
          const entry: EventLogEntry = JSON.parse(e.data);
          const seq = seqRef.current++;
          const indexed: IndexedEntry = { ...entry, _seq: seq };
          setEntries((prev) => {
            const next = [...(prev as IndexedEntry[]).slice(-99), indexed];
            next.sort((a, b) => {
              const t = (a as IndexedEntry).time.localeCompare((b as IndexedEntry).time);
              if (t !== 0) return t;
              return (a as IndexedEntry)._seq - (b as IndexedEntry)._seq;
            });
            return next;
          });
        } catch {}
      };
      return es;
    });
    return () => sources.forEach((es) => es.close());
  }, []);

  return entries;
}

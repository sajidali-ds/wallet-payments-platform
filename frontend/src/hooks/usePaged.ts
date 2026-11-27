import { useCallback, useEffect, useState } from "react";
import type { Page } from "../api/types";
import { describeError } from "../lib/errors";

// Cursor pagination used by the history and notification lists. `fetchPage` must be a stable
// function (define it outside the component). Changing `reloadKey` reloads from the first page.
export function usePaged<T>(fetchPage: (cursor: number | null) => Promise<Page<T>>, reloadKey = 0) {
  const [items, setItems] = useState<T[]>([]);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualReload, setManualReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchPage(null)
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(describeError(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPage, reloadKey, manualReload]);

  const loadMore = useCallback(async () => {
    if (nextCursor === null) return;
    setLoadingMore(true);
    try {
      const page = await fetchPage(nextCursor);
      setItems((previous) => [...previous, ...page.items]);
      setNextCursor(page.next_cursor);
      setError(null);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setLoadingMore(false);
    }
  }, [fetchPage, nextCursor]);

  const reload = useCallback(() => setManualReload((n) => n + 1), []);

  return { items, loading, loadingMore, error, hasMore: nextCursor !== null, loadMore, reload };
}

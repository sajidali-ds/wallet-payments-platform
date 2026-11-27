import * as api from "../api/client";
import { usePaged } from "../hooks/usePaged";
import { formatDateTime } from "../lib/format";
import { Notice } from "./Notice";

const fetchNotifications = (cursor: number | null) => api.listNotifications(20, cursor);

export function NotificationsView() {
  const { items, loading, loadingMore, error, hasMore, loadMore, reload } = usePaged(fetchNotifications);

  return (
    <section className="panel narrow" aria-labelledby="notifications-heading">
      <div className="panel-head">
        <h2 id="notifications-heading">Notifications</h2>
        <button type="button" className="link-button" onClick={reload} disabled={loading}>
          Reload
        </button>
      </div>
      <p className="hint">Created from transfer events delivered through RabbitMQ, usually within a second.</p>

      {error && <Notice kind="error">{error}</Notice>}
      {loading && items.length === 0 && <p role="status">Loading notifications…</p>}
      {!loading && !error && items.length === 0 && (
        <p className="empty-text">Nothing yet. You will see a message here when someone sends you money.</p>
      )}

      {items.length > 0 && (
        <ul className="notifications">
          {items.map((item) => (
            <li key={item.id}>
              <span>{item.message}</span>
              <span className="entry-meta">{formatDateTime(item.created_at)}</span>
            </li>
          ))}
        </ul>
      )}

      {hasMore && (
        <button type="button" className="secondary" onClick={() => void loadMore()} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Show older notifications"}
        </button>
      )}
    </section>
  );
}

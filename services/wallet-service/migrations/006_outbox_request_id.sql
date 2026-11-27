-- The id of the HTTP request that caused the event, so one request can be followed from the
-- gateway through wallet-service into RabbitMQ and notification-service.
ALTER TABLE outbox_events ADD COLUMN request_id TEXT;

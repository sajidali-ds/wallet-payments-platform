import contextlib

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractRobustConnection


class RabbitBroker:
    def __init__(self, url: str, exchange_name: str, *, publish_timeout: float = 10.0) -> None:
        self._url = url
        self._exchange_name = exchange_name
        self._publish_timeout = publish_timeout
        self._connection: AbstractRobustConnection | None = None
        self._exchange: AbstractExchange | None = None

    async def _ready_exchange(self) -> AbstractExchange:
        if self._exchange is None:
            connection = await aio_pika.connect_robust(self._url)  # reconnects by itself later
            try:
                channel = await connection.channel(
                    publisher_confirms=True,
                    on_return_raises=True,
                )
                self._exchange = await channel.declare_exchange(
                    self._exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
                )
            except Exception:
                await connection.close()
                raise
            self._connection = connection
        return self._exchange

    async def publish(
        self, *, event_id: str, event_type: str, body: bytes, request_id: str | None = None
    ) -> None:
        exchange = await self._ready_exchange()
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=event_id,
            correlation_id=request_id,  # lets consumers log the originating request id
            type=event_type,
        )
        await exchange.publish(
            message, routing_key=event_type, mandatory=True, timeout=self._publish_timeout
        )

    async def close(self) -> None:
        connection, self._connection, self._exchange = self._connection, None, None
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.close()

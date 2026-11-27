"""RabbitMQ topology for the notification consumer.

    wallet.events (topic exchange)
         | routing key "transfer.completed"
         v
    <queue>  ---- consumer ---- success --------------------------> ack
         ^            |
         |            +-- failure, retries left --> <queue>.retry.N (TTL = base * 2**(N-1))
         |                                              |
         +----------- message expires (dead-letters, via the default exchange) ----+
                      |
                      +-- poison message or retries exhausted --> <queue>.dlq (parked for humans)

Why one retry queue per attempt and not one queue with a per-message TTL? RabbitMQ only expires a
message when it reaches the HEAD of a queue. In a single queue holding a 20-second message in
front of a 5-second one, the short one would wait behind the long one. One queue per delay keeps
every message in a queue where all messages have the same TTL, so expiry is always on time.
"""

from dataclasses import dataclass

from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractQueue

ROUTING_KEY = "transfer.completed"


@dataclass(frozen=True)
class Topology:
    exchange: str
    queue: str
    max_retries: int
    retry_base_delay_ms: int

    @property
    def dlq(self) -> str:
        return f"{self.queue}.dlq"

    def retry_queue(self, attempt: int) -> str:
        return f"{self.queue}.retry.{attempt}"

    def retry_delay_ms(self, attempt: int) -> int:
        """Exponential backoff: base, 2*base, 4*base, ..."""
        return self.retry_base_delay_ms * 2 ** (attempt - 1)


async def declare_topology(channel: AbstractChannel, topology: Topology) -> AbstractQueue:
    """Declares everything (idempotent) and returns the main queue.

    Note: RabbitMQ refuses to re-declare an existing queue with different arguments, so after
    changing the retry delays the old queues must be deleted first.
    """
    exchange = await channel.declare_exchange(topology.exchange, ExchangeType.TOPIC, durable=True)
    await channel.declare_queue(topology.dlq, durable=True)
    for attempt in range(1, topology.max_retries + 1):
        await channel.declare_queue(
            topology.retry_queue(attempt),
            durable=True,
            arguments={
                "x-message-ttl": topology.retry_delay_ms(attempt),
                # Expired messages are re-routed through the default exchange ("") straight back
                # into the main queue, because its routing key is the main queue's name.
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": topology.queue,
            },
        )
    queue = await channel.declare_queue(topology.queue, durable=True)
    await queue.bind(exchange, routing_key=ROUTING_KEY)
    return queue

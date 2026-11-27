from app.consumers.topology import Topology


def _topology(**overrides) -> Topology:
    values = {"exchange": "ex", "queue": "q", "max_retries": 3, "retry_base_delay_ms": 5000}
    return Topology(**(values | overrides))


def test_retry_delays_double_each_attempt():
    topology = _topology()
    assert [topology.retry_delay_ms(n) for n in (1, 2, 3)] == [5000, 10_000, 20_000]


def test_queue_names():
    topology = _topology()
    assert topology.dlq == "q.dlq"
    assert topology.retry_queue(2) == "q.retry.2"

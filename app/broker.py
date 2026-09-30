from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Callable

from app.config import get_settings

settings = get_settings()


@dataclass(slots=True)
class QueueMessage:
    job_id: str
    event: str = "process"
    correlation_id: str | None = None


class BrokerClient:
    def __init__(self) -> None:
        self.enabled = settings.enable_rabbitmq
        self._connection = None

    def _connect(self):
        if not self.enabled:
            return None
        try:
            import pika

            params = pika.URLParameters(settings.rabbitmq_url)
            self._connection = pika.BlockingConnection(params)
            return self._connection
        except Exception:
            self._connection = None
            return None

    def publish(self, message: QueueMessage, queue_name: str | None = None) -> bool:
        if not self.enabled:
            return False
        queue = queue_name or settings.queue_name
        connection = self._connection or self._connect()
        if not connection:
            return False
        try:
            import pika

            channel = connection.channel()
            channel.queue_declare(queue=queue, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=queue,
                body=json.dumps(asdict(message)).encode("utf-8"),
                properties=pika.BasicProperties(delivery_mode=2),
            )
            return True
        except Exception:
            return False

    def consume(self, handler: Callable[[QueueMessage], None], queue_name: str | None = None) -> None:
        if not self.enabled:
            raise RuntimeError("RabbitMQ is disabled")

        queue = queue_name or settings.queue_name
        connection = self._connection or self._connect()
        if not connection:
            raise RuntimeError("Unable to connect to RabbitMQ")

        import pika

        channel = connection.channel()
        channel.queue_declare(queue=queue, durable=True)
        channel.basic_qos(prefetch_count=1)

        def on_message(_ch, method, _properties, body):
            payload = json.loads(body.decode("utf-8"))
            handler(QueueMessage(**payload))
            _ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=queue, on_message_callback=on_message)
        channel.start_consuming()


broker = BrokerClient()


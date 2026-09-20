"""SQS jobs queue + dead-letter queue."""

from __future__ import annotations

from aws_cdk import Duration, Stack
from aws_cdk import aws_sqs as sqs
from constructs import Construct


class QueueStack(Stack):
    def __init__(self, scope: Construct, id: str, **kw) -> None:
        super().__init__(scope, id, **kw)
        self.dlq = sqs.Queue(
            self,
            "DeadLetter",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
        )
        self.queue = sqs.Queue(
            self,
            "Jobs",
            # the worker extends the visibility every 5 minutes while a job runs; this is the
            # window for a crashed task before the message becomes visible again
            visibility_timeout=Duration.minutes(20),
            retention_period=Duration.days(1),
            receive_message_wait_time=Duration.seconds(20),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=2, queue=self.dlq),
        )

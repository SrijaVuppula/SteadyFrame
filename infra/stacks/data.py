"""DynamoDB: jobs (pk job_id) and traces (pk job_id, sk seq). On-demand, TTL 7 days."""

from __future__ import annotations

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as ddb
from constructs import Construct

TTL_ATTRIBUTE = "_ttl"  # set by service/core.py: now + 7 days


class DataStack(Stack):
    def __init__(self, scope: Construct, id: str, **kw) -> None:
        super().__init__(scope, id, **kw)
        self.jobs = ddb.Table(
            self,
            "Jobs",
            partition_key=ddb.Attribute(name="job_id", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute=TTL_ATTRIBUTE,
            encryption=ddb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.traces = ddb.Table(
            self,
            "Traces",
            partition_key=ddb.Attribute(name="job_id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="seq", type=ddb.AttributeType.NUMBER),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute=TTL_ATTRIBUTE,
            encryption=ddb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
        )

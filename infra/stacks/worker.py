"""ECS Fargate worker on ARM64 (Graviton), scaled 0..2 by queue backlog.

Tasks run in public subnets with a public IP so there is no NAT gateway to pay for; every
call the worker makes (S3, SQS, DynamoDB, CloudWatch, Bedrock) is an outbound HTTPS call.
"""

from __future__ import annotations

import re

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from . import ROOT

PLACEHOLDER_IMAGE = "public.ecr.aws/docker/library/python:3.11-slim"
_REGION_PREFIX = re.compile(r"^(us|eu|apac|global|jp|au|ca|us-gov)\.")


def bedrock_resources(stack: Stack, model_id: str) -> list[str]:
    """ARNs an inference-profile id resolves to: the profile in this account/region plus the
    underlying foundation model, which for cross-region profiles lives in other regions."""
    base = _REGION_PREFIX.sub("", model_id)
    return [
        stack.format_arn(service="bedrock", resource="inference-profile", resource_name=model_id),
        f"arn:{stack.partition}:bedrock:*::foundation-model/{base}",
    ]


class WorkerStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        bucket: s3.IBucket,
        jobs: ddb.ITable,
        traces: ddb.ITable,
        queue: sqs.IQueue,
        bedrock_model_id: str = "",
        skip_docker_build: bool = False,
        idle_exit_s: int = 600,
        **kw,
    ) -> None:
        super().__init__(scope, id, **kw)
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
            restrict_default_security_group=False,
        )
        vpc.add_gateway_endpoint("S3", service=ec2.GatewayVpcEndpointAwsService.S3)
        vpc.add_gateway_endpoint("DynamoDB", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB)
        self.cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        self.log_group = logs.LogGroup(
            self,
            "WorkerLogs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.task = ecs.FargateTaskDefinition(
            self,
            "Task",
            cpu=2048,
            memory_limit_mib=4096,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        if skip_docker_build:
            image = ecs.ContainerImage.from_registry(PLACEHOLDER_IMAGE)
        else:
            image = ecs.ContainerImage.from_docker_image_asset(
                ecr_assets.DockerImageAsset(
                    self,
                    "WorkerImage",
                    directory=str(ROOT),
                    file="Dockerfile",
                    target="worker",
                    platform=ecr_assets.Platform.LINUX_ARM64,
                )
            )
        env = {
            "STEADYFRAME_MODE": "aws",
            "AWS_REGION": self.region,
            "BUCKET_NAME": bucket.bucket_name,
            "JOBS_TABLE": jobs.table_name,
            "TRACES_TABLE": traces.table_name,
            "QUEUE_URL": queue.queue_url,
            "WORKER_WORKDIR": "/tmp/jobs",
            "WORKER_IDLE_EXIT_S": str(idle_exit_s),
            "PYTHONUNBUFFERED": "1",
        }
        if bedrock_model_id:
            env["STEADYFRAME_BEDROCK_MODEL_ID"] = bedrock_model_id
        self.task.add_container(
            "worker",
            image=image,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="worker", log_group=self.log_group),
            environment=env,
            stop_timeout=Duration.seconds(120),
        )

        task_role = self.task.task_role
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="ReadInputsAndPausedState",
                actions=["s3:GetObject"],
                resources=[
                    bucket.arn_for_objects("uploads/*"),
                    bucket.arn_for_objects("outputs/*"),
                ],
            )
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="WriteOutputs",
                actions=["s3:PutObject"],
                resources=[bucket.arn_for_objects("outputs/*")],
            )
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="JobsTable",
                actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
                resources=[jobs.table_arn],
            )
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="TracesTableWrite",
                actions=["dynamodb:BatchWriteItem", "dynamodb:PutItem"],
                resources=[traces.table_arn],
            )
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="ConsumeQueue",
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:ChangeMessageVisibility",
                    "sqs:GetQueueAttributes",
                ],
                resources=[queue.queue_arn],
            )
        )
        task_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="Metrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],  # PutMetricData has no resource-level scope
                conditions={"StringEquals": {"cloudwatch:namespace": "SteadyFrame"}},
            )
        )
        if bedrock_model_id:
            task_role.add_to_principal_policy(
                iam.PolicyStatement(
                    sid="BedrockConverse",
                    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                    resources=bedrock_resources(self, bedrock_model_id),
                )
            )

        self.service = ecs.FargateService(
            self,
            "Service",
            cluster=self.cluster,
            task_definition=self.task,
            desired_count=0,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            min_healthy_percent=0,
            max_healthy_percent=200,
            enable_execute_command=False,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        scaling = self.service.auto_scale_task_count(min_capacity=0, max_capacity=2)
        # visible + in-flight: a message being worked on is not visible, and a scale-in on
        # "visible == 0" alone would stop the task in the middle of that job
        backlog = cloudwatch.MathExpression(
            expression="visible + inflight",
            using_metrics={
                "visible": queue.metric_approximate_number_of_messages_visible(
                    period=Duration.minutes(1), statistic="Maximum"
                ),
                "inflight": queue.metric_approximate_number_of_messages_not_visible(
                    period=Duration.minutes(1), statistic="Maximum"
                ),
            },
            period=Duration.minutes(1),
            label="queue backlog",
        )
        scaling.scale_on_metric(
            "ScaleOutOnBacklog",
            metric=backlog,
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=0),
                appscaling.ScalingInterval(lower=1, change=1),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
            cooldown=Duration.seconds(60),
            evaluation_periods=1,
        )
        scaling.scale_on_metric(
            "ScaleInWhenIdle",
            metric=backlog,
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=-1),
                appscaling.ScalingInterval(lower=1, change=0),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
            cooldown=Duration.minutes(5),
            evaluation_periods=10,  # ten idle minutes before the last task goes away
        )
        self.backlog_metric = backlog

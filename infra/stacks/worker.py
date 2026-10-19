"""Workers on ARM64 (Graviton) that consume the jobs queue.

By default a Lambda function (arm64 container image, ``lambda`` target of the Dockerfile) takes
each message within seconds and costs nothing while idle; the ECS service below stays as the
fallback and scales out only when messages wait unread (``-c lambda_worker=false`` turns the
Lambda off and the ECS service is the worker again). The ECS service has two engines:

- ``fargate`` (default): Fargate tasks from the repo ``Dockerfile`` with the
  opencv-python-headless wheel.
- ``cool``: the AWS Marketplace COOL container ("OpenCV 5 for Graviton4 - Python 3.11") as
  the base of ``Dockerfile.cool``, on an Auto Scaling group of Graviton4 instances behind an
  ECS capacity provider. COOL is built for Neoverse-V2 (Graviton4) and the listing does not
  support Fargate, whose ARM64 tasks are not Graviton4.

Tasks run in public subnets with a public IP so there is no NAT gateway to pay for; every
call the worker makes (S3, SQS, DynamoDB, CloudWatch, Bedrock, Marketplace metering) is an
outbound HTTPS call. On EC2 the tasks use bridge networking and go out through the
instance's public IP: awsvpc tasks on EC2 get no public IP of their own.
"""

from __future__ import annotations

import re

from aws_cdk import Duration, RemovalPolicy, Size, Stack
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as events_targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_event_sources as lambda_events
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from . import ROOT

PLACEHOLDER_IMAGE = "public.ecr.aws/docker/library/python:3.11-slim"
_REGION_PREFIX = re.compile(r"^(us|eu|apac|global|jp|au|ca|us-gov)\.")

WORKER_ENGINES = ("fargate", "cool")
COOL_INSTANCE_TYPE = "c8g.large"
# Graviton4 families the COOL container supports (c8gd, c8gn, m8gd, r8gd included)
COOL_INSTANCE_FAMILIES = ("c8g", "m8g", "r8g")


def check_worker_engine(
    engine: str, cool_image: str = "", cool_instance_type: str = COOL_INSTANCE_TYPE
) -> None:
    """Fail synth on a worker_engine / cool_* context that cannot deploy."""
    if engine not in WORKER_ENGINES:
        raise ValueError(
            f"worker_engine must be one of {', '.join(WORKER_ENGINES)}, got {engine!r}"
        )
    if engine != "cool":
        return
    if not cool_image:
        raise ValueError(
            "worker_engine=cool needs -c cool_image=<image URI of the Marketplace delivery "
            "option 'OpenCV 5 for Graviton4 - Python 3.11'> (infra/README.md, COOL worker)"
        )
    family, dot, size = cool_instance_type.partition(".")
    if not (dot and size and family.startswith(COOL_INSTANCE_FAMILIES)):
        raise ValueError(
            f"cool_instance_type must be a Graviton4 type ({', '.join(COOL_INSTANCE_FAMILIES)} "
            f"families), got {cool_instance_type!r}"
        )


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
        min_tasks: int = 0,
        engine: str = "fargate",
        cool_image: str = "",
        cool_instance_type: str = COOL_INSTANCE_TYPE,
        lambda_worker: bool = True,
        **kw,
    ) -> None:
        check_worker_engine(engine, cool_image, cool_instance_type)
        super().__init__(scope, id, **kw)
        self.engine = engine
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
        env = {
            "STEADYFRAME_MODE": "aws",
            "AWS_REGION": self.region,
            "BUCKET_NAME": bucket.bucket_name,
            "JOBS_TABLE": jobs.table_name,
            "TRACES_TABLE": traces.table_name,
            "QUEUE_URL": queue.queue_url,
            "WORKER_WORKDIR": "/tmp/jobs",
            "PYTHONUNBUFFERED": "1",
        }
        if min_tasks == 0:
            # with a warm task kept on purpose, exiting when idle would only churn it
            env["WORKER_IDLE_EXIT_S"] = str(idle_exit_s)
        if bedrock_model_id:
            env["STEADYFRAME_BEDROCK_MODEL_ID"] = bedrock_model_id
        if engine == "cool":
            self._cool(vpc, env, skip_docker_build, min_tasks, cool_image, cool_instance_type)
        else:
            self._fargate(env, skip_docker_build, min_tasks)
        task_role = self.task.task_role
        self._grant(task_role, bucket, jobs, traces, queue, bedrock_model_id)
        if engine == "cool":
            # the entitlement check in the image's libopencv_core calls RegisterUsage with the
            # task's credentials when the worker loads cv2; without it the task exits 133
            task_role.add_to_principal_policy(
                iam.PolicyStatement(
                    sid="MarketplaceRegisterUsage",
                    actions=["aws-marketplace:RegisterUsage"],
                    resources=["*"],  # RegisterUsage has no resource-level scope
                )
            )
        # COOL needs Graviton4 instances, so with that engine the ECS service stays the worker
        self.lambda_function = None
        if lambda_worker and engine != "cool":
            self.lambda_function = self._lambda(env, skip_docker_build, queue)
            self._grant(self.lambda_function.role, bucket, jobs, traces, queue, bedrock_model_id)
        self.backlog_metric = self._scale_on_backlog(
            queue, min_tasks, fallback=self.lambda_function is not None
        )

    def _lambda(self, env: dict, skip_docker_build: bool, queue: sqs.IQueue):
        if skip_docker_build:
            code = lambda_.DockerImageCode.from_ecr(
                ecr.Repository.from_repository_name(self, "PlaceholderRepo", "placeholder")
            )
        else:
            code = lambda_.DockerImageCode.from_image_asset(
                str(ROOT),
                file="Dockerfile",
                target="lambda",
                platform=ecr_assets.Platform.LINUX_ARM64,
            )
        fn_env = {k: v for k, v in env.items() if k not in ("AWS_REGION", "WORKER_IDLE_EXIT_S")}
        fn_env.update({"MPLCONFIGDIR": "/tmp/mpl", "HOME": "/tmp", "WORKER_WORKDIR": "/tmp/jobs"})
        fn = lambda_.DockerImageFunction(
            self,
            "LambdaWorker",
            description="SteadyFrame worker: one SQS job per invocation (same JobRunner as ECS)",
            code=code,
            architecture=lambda_.Architecture.ARM_64,
            # 3008 MB is the most a new account may set; it buys about two vCPUs
            memory_size=3008,
            ephemeral_storage_size=Size.mebibytes(2048),
            timeout=Duration.minutes(15),  # the queue's visibility timeout (20 min) is longer
            environment=fn_env,
            log_group=logs.LogGroup(
                self,
                "LambdaWorkerLogs",
                retention=logs.RetentionDays.TWO_WEEKS,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        fn.add_event_source(
            lambda_events.SqsEventSource(
                queue, batch_size=1, max_concurrency=2, report_batch_item_failures=True
            )
        )
        # keep one execution environment warm (OpenCV loaded) so a demo job starts in seconds
        events.Rule(
            self,
            "KeepWarm",
            description="SteadyFrame: keep one Lambda worker warm",
            schedule=events.Schedule.rate(Duration.minutes(5)),
            targets=[
                events_targets.LambdaFunction(
                    fn, event=events.RuleTargetInput.from_object({"warmup": True})
                )
            ],
        )
        return fn

    def _worker_image(self, skip_docker_build: bool, **asset) -> ecs.ContainerImage:
        if skip_docker_build:
            return ecs.ContainerImage.from_registry(PLACEHOLDER_IMAGE)
        return ecs.ContainerImage.from_docker_image_asset(
            ecr_assets.DockerImageAsset(
                self,
                asset.pop("id"),
                directory=str(ROOT),
                platform=ecr_assets.Platform.LINUX_ARM64,
                **asset,
            )
        )

    def _fargate(self, env: dict, skip_docker_build: bool, min_tasks: int) -> None:
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
        image = self._worker_image(
            skip_docker_build, id="WorkerImage", file="Dockerfile", target="worker"
        )
        self.task.add_container(
            "worker",
            image=image,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="worker", log_group=self.log_group),
            environment=env,
            stop_timeout=Duration.seconds(120),
        )
        self.service = ecs.FargateService(
            self,
            "Service",
            cluster=self.cluster,
            task_definition=self.task,
            desired_count=min_tasks,
            assign_public_ip=True,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            min_healthy_percent=0,
            max_healthy_percent=200,
            enable_execute_command=False,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )

    def _cool(
        self,
        vpc: ec2.IVpc,
        env: dict,
        skip_docker_build: bool,
        min_tasks: int,
        cool_image: str,
        instance_type: str,
    ) -> None:
        max_tasks = max(2, min_tasks)
        # Graviton4 instances in the public subnets, public IP, no inbound rule. Managed
        # scaling sizes the group from the tasks the service asks for (0 when it is at 0);
        # managed termination protection keeps an instance with a running job from being
        # scaled in under it
        sg = ec2.SecurityGroup(
            self,
            "CoolInstanceSg",
            vpc=vpc,
            description="SteadyFrame COOL worker instances: no inbound",
            allow_all_outbound=True,
        )
        launch_template = ec2.LaunchTemplate(
            self,
            "CoolLaunchTemplate",
            instance_type=ec2.InstanceType(instance_type),
            machine_image=ecs.EcsOptimizedImage.amazon_linux2023(ecs.AmiHardwareType.ARM),
            role=iam.Role(
                self, "CoolInstanceRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com")
            ),
            security_group=sg,
            associate_public_ip_address=True,
            # IMDSv2 with one hop: the ECS agent (host network) reaches it, bridge-mode
            # containers do not, so the worker only ever holds the task role
            require_imdsv2=True,
            http_put_response_hop_limit=1,
            user_data=ec2.UserData.for_linux(),  # the cluster adds ECS_CLUSTER to it
        )
        self.auto_scaling_group = autoscaling.AutoScalingGroup(
            self,
            "CoolInstances",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            launch_template=launch_template,
            min_capacity=0,
            max_capacity=max_tasks,
        )
        self.capacity_provider = ecs.AsgCapacityProvider(
            self,
            "CoolCapacityProvider",
            auto_scaling_group=self.auto_scaling_group,
            enable_managed_scaling=True,
            enable_managed_termination_protection=True,
            target_capacity_percent=100,
        )
        self.cluster.add_asg_capacity_provider(self.capacity_provider)

        # bridge: awsvpc tasks on EC2 get no public IP and there is no NAT, so the task uses
        # the instance's network. EC2 task definitions take no runtimePlatform; the placement
        # constraint keeps the task on arm64 container instances. Sized to fit one task on a
        # c8g.large (2 vCPU, 4 GiB, a little less of it registered with ECS); the memory
        # reservation is soft, so the worker can use what the instance has free
        self.task = ecs.Ec2TaskDefinition(
            self,
            "CoolTask",
            network_mode=ecs.NetworkMode.BRIDGE,
            placement_constraints=[
                ecs.PlacementConstraint.member_of("attribute:ecs.cpu-architecture == arm64")
            ],
        )
        image = self._worker_image(
            skip_docker_build,
            id="CoolWorkerImage",
            file="Dockerfile.cool",
            build_args={"COOL_IMAGE": cool_image},
        )
        self.task.add_container(
            "worker",
            image=image,
            cpu=2048,
            memory_reservation_mib=3072,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="worker", log_group=self.log_group),
            environment={
                **env,
                # the image's SDK needs a writable HOME; the worker reports the engine
                "HOME": "/tmp",
                "STEADYFRAME_OPENCV_ENGINE": "cool",
            },
            stop_timeout=Duration.seconds(120),
        )
        self.service = ecs.Ec2Service(
            self,
            "CoolService",
            cluster=self.cluster,
            task_definition=self.task,
            desired_count=min_tasks,
            capacity_provider_strategies=[
                ecs.CapacityProviderStrategy(
                    capacity_provider=self.capacity_provider.capacity_provider_name, weight=1
                )
            ],
            min_healthy_percent=0,
            max_healthy_percent=200,
            enable_execute_command=False,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        # the service may only be created once the capacity provider is on the cluster, and
        # must be gone before it is taken off again. The association is created under the
        # cluster at synth time; a dependency on the cluster construct covers it
        self.service.node.add_dependency(self.cluster)

    def _grant(
        self,
        task_role: iam.IRole,
        bucket: s3.IBucket,
        jobs: ddb.ITable,
        traces: ddb.ITable,
        queue: sqs.IQueue,
        bedrock_model_id: str,
    ) -> None:
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

    def _scale_on_backlog(
        self, queue: sqs.IQueue, min_tasks: int, *, fallback: bool = False
    ) -> cloudwatch.MathExpression:
        scaling = self.service.auto_scale_task_count(
            min_capacity=min_tasks, max_capacity=max(2, min_tasks)
        )
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
        # With the Lambda worker in front, a message is in flight within seconds of arriving;
        # the ECS service only steps in when messages sit visible (unread) for two minutes.
        waiting = queue.metric_approximate_number_of_messages_visible(
            period=Duration.minutes(1), statistic="Maximum"
        )
        scaling.scale_on_metric(
            "ScaleOutOnBacklog",
            metric=waiting if fallback else backlog,
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=0),
                appscaling.ScalingInterval(lower=1, change=1),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
            cooldown=Duration.seconds(60),
            evaluation_periods=2 if fallback else 1,
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
        return backlog

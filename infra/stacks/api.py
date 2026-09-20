"""HTTP API + one Lambda routing every endpoint in docs/API.md.

The Lambda is packaged from ``service/`` minus the worker files; it imports only boto3 (in
the runtime) and never cv2. Least-privilege statements are written out by hand so the
effective policy is readable (see infra/policies/)."""

from __future__ import annotations

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from . import ROOT

LAMBDA_EXCLUDES = [
    "worker.py",
    "local_api.py",
    "smoke.py",
    "__pycache__",
    "**/__pycache__",
    "*.pyc",
    "**/*.pyc",
]


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        bucket: s3.IBucket,
        jobs: ddb.ITable,
        traces: ddb.ITable,
        queue: sqs.IQueue,
        version: str,
        opencv_version: str,
        **kw,
    ) -> None:
        super().__init__(scope, id, **kw)
        log_group = logs.LogGroup(
            self,
            "ApiLogs",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.function = lambda_.Function(
            self,
            "Api",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambda/handler.handler",
            code=lambda_.Code.from_asset(str(ROOT / "service"), exclude=LAMBDA_EXCLUDES),
            memory_size=512,
            timeout=Duration.seconds(29),  # HTTP API integration limit is 30 s
            log_group=log_group,
            environment={
                "STEADYFRAME_MODE": "aws",
                "BUCKET_NAME": bucket.bucket_name,
                "JOBS_TABLE": jobs.table_name,
                "TRACES_TABLE": traces.table_name,
                "QUEUE_URL": queue.queue_url,
                "STEADYFRAME_VERSION": version,
                "STEADYFRAME_OPENCV_VERSION": opencv_version,
            },
            description="SteadyFrame HTTP API (create/presign/status/approve/download)",
        )
        role = self.function.role
        assert role is not None
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="UploadsPresignAndCleanup",
                actions=["s3:PutObject", "s3:DeleteObject"],
                resources=[bucket.arn_for_objects("uploads/*")],
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="ReadJobObjects",
                actions=["s3:GetObject"],
                resources=[
                    bucket.arn_for_objects("uploads/*"),
                    bucket.arn_for_objects("outputs/*"),
                    bucket.arn_for_objects("samples/*"),
                ],
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="ListSamplesAndJobPrefixes",
                actions=["s3:ListBucket"],
                resources=[bucket.bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["samples/*", "uploads/*", "outputs/*"]}},
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="JobsTable",
                actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                resources=[jobs.table_arn],
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="TracesTableRead", actions=["dynamodb:Query"], resources=[traces.table_arn]
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="EnqueueJobs", actions=["sqs:SendMessage"], resources=[queue.queue_arn]
            )
        )

        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name="steadyframe",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.PUT,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["*"],
                max_age=Duration.hours(1),
            ),
            default_integration=integrations.HttpLambdaIntegration("LambdaProxy", self.function),
        )
        self.api_url = self.http_api.api_endpoint
        CfnOutput(self, "ApiUrl", value=self.api_url)

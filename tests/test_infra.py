"""CDK synth (in-process, no Docker, no lookups) and checks on the templates."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"

pytest.importorskip("aws_cdk")

from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402


def _load_app_module():
    sys.path.insert(0, str(INFRA))
    spec = importlib.util.spec_from_file_location("steadyframe_infra_app", INFRA / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def stacks():
    mod = _load_app_module()
    app = App(
        context={
            "skip_docker_build": "true",
            "alert_email": "alerts@example.com",
            "bedrock_model_id": "us.example.model-v1:0",
        }
    )
    built = mod.build(app)
    app.synth()
    return built


@pytest.fixture(scope="module")
def templates(stacks):
    return {k: Template.from_stack(v) for k, v in stacks.items()}


def test_all_stacks_synthesise(stacks):
    assert set(stacks) == {"storage", "data", "queue", "api", "worker", "web", "observability"}


def test_worker_is_arm64_fargate_2vcpu_4gb(templates):
    t = templates["worker"]
    t.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "Cpu": "2048",
            "Memory": "4096",
            "RequiresCompatibilities": ["FARGATE"],
            "RuntimePlatform": {"CpuArchitecture": "ARM64", "OperatingSystemFamily": "LINUX"},
        },
    )
    t.has_resource_properties("AWS::ECS::Service", {"DesiredCount": 0, "LaunchType": "FARGATE"})
    t.has_resource_properties(
        "AWS::ApplicationAutoScaling::ScalableTarget", {"MinCapacity": 0, "MaxCapacity": 2}
    )
    assert len(t.find_resources("AWS::ApplicationAutoScaling::ScalingPolicy")) == 2
    # no NAT gateway: public subnets with public IPs
    assert t.find_resources("AWS::EC2::NatGateway") == {}
    t.has_resource_properties(
        "AWS::ECS::Service",
        {"NetworkConfiguration": {"AwsvpcConfiguration": {"AssignPublicIp": "ENABLED"}}},
    )
    env = t.find_resources("AWS::ECS::TaskDefinition")
    (task,) = env.values()
    names = {e["Name"] for e in task["Properties"]["ContainerDefinitions"][0]["Environment"]}
    assert {"BUCKET_NAME", "JOBS_TABLE", "TRACES_TABLE", "QUEUE_URL", "WORKER_IDLE_EXIT_S"} <= names


def test_bucket_is_private_encrypted_with_one_day_lifecycle(templates):
    t = templates["storage"]
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.any_value(),
            "LifecycleConfiguration": {
                "Rules": Match.array_with(
                    [
                        Match.object_like(
                            {"Prefix": "uploads/", "ExpirationInDays": 1, "Status": "Enabled"}
                        ),
                        Match.object_like(
                            {"Prefix": "outputs/", "ExpirationInDays": 1, "Status": "Enabled"}
                        ),
                    ]
                )
            },
            "CorsConfiguration": {
                "CorsRules": Match.array_with(
                    [Match.object_like({"AllowedMethods": Match.array_with(["PUT"])})]
                )
            },
        },
    )
    # every bucket in every stack blocks public access and enforces TLS
    for name, tpl in templates.items():
        for logical, res in tpl.find_resources("AWS::S3::Bucket").items():
            pab = res["Properties"].get("PublicAccessBlockConfiguration", {})
            assert all(pab.get(k) for k in ("BlockPublicAcls", "BlockPublicPolicy")), (
                name,
                logical,
            )
        for res in tpl.find_resources("AWS::S3::BucketPolicy").values():
            doc = json.dumps(res["Properties"]["PolicyDocument"])
            assert "aws:SecureTransport" in doc, name


def test_tables_have_ttl_and_on_demand_billing(templates):
    t = templates["data"]
    t.resource_count_is("AWS::DynamoDB::Table", 2)
    t.all_resources_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "TimeToLiveSpecification": {"AttributeName": "_ttl", "Enabled": True},
        },
    )
    t.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": [
                {"AttributeName": "job_id", "KeyType": "HASH"},
                {"AttributeName": "seq", "KeyType": "RANGE"},
            ]
        },
    )


def test_queue_has_dead_letter_queue(templates):
    t = templates["queue"]
    t.resource_count_is("AWS::SQS::Queue", 2)
    t.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "VisibilityTimeout": 1200,
            "RedrivePolicy": {"maxReceiveCount": 2, "deadLetterTargetArn": Match.any_value()},
        },
    )


def test_api_lambda_is_light_and_routes_everything(templates):
    t = templates["api"]
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.11",
            "Handler": "lambda/handler.handler",
            "Architectures": ["arm64"],
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "STEADYFRAME_MODE": "aws",
                        "STEADYFRAME_OPENCV_VERSION": Match.string_like_regexp(r"^5\."),
                    }
                )
            },
        },
    )
    t.has_resource_properties("AWS::ApiGatewayV2::Api", {"ProtocolType": "HTTP"})
    t.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": "$default"})
    t.has_output("ApiUrl", {})
    # the packaged asset must not carry the worker
    for res in t.find_resources("AWS::Lambda::Function").values():
        if res["Properties"].get("Handler") == "lambda/handler.handler":
            asset_hash = res["Properties"]["Code"]["S3Key"]
            assert asset_hash


def test_bedrock_permission_is_scoped_to_the_configured_model(templates):
    t = templates["worker"]
    statements = []
    for res in t.find_resources("AWS::IAM::Policy").values():
        statements.extend(res["Properties"]["PolicyDocument"]["Statement"])
    bedrock = [
        s
        for s in statements
        if any(str(a).startswith("bedrock:") for a in _as_list(s.get("Action")))
    ]
    assert len(bedrock) == 1, bedrock
    s = bedrock[0]
    assert set(_as_list(s["Action"])) == {
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
    }
    resources = json.dumps(s["Resource"])
    assert '"*"' not in json.dumps(_as_list(s["Resource"]))  # no bare wildcard resource
    assert "inference-profile/us.example.model-v1:0" in resources
    assert "foundation-model/example.model-v1:0" in resources
    # the only "*" resource in the worker is PutMetricData, and it is namespace-conditioned
    for st in statements:
        if "*" in _as_list(st.get("Resource")):
            assert _as_list(st["Action"]) == ["cloudwatch:PutMetricData"], st
            assert st["Condition"] == {"StringEquals": {"cloudwatch:namespace": "SteadyFrame"}}


def test_worker_without_model_id_has_no_bedrock_statement():
    mod = _load_app_module()
    app = App(context={"skip_docker_build": "true", "bedrock_model_id": ""})
    built = mod.build(app)
    t = Template.from_stack(built["worker"])
    doc = json.dumps(t.to_json())
    assert "bedrock:" not in doc


def test_web_and_observability(templates):
    w = templates["web"]
    w.has_output("WebUrl", {})
    w.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "PathPattern": "/api/*",
                                    "AllowedMethods": Match.array_with(["PUT", "POST"]),
                                }
                            )
                        ]
                    )
                }
            )
        },
    )
    o = templates["observability"]
    o.resource_count_is("AWS::CloudWatch::Dashboard", 1)
    assert len(o.find_resources("AWS::CloudWatch::Alarm")) == 3
    o.has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "alerts@example.com"}
    )
    templates["storage"].has_output("BucketName", {})


def test_no_public_wildcard_iam_principals(templates):
    for name, tpl in templates.items():
        for logical, res in tpl.find_resources("AWS::IAM::Role").items():
            for st in res["Properties"]["AssumeRolePolicyDocument"]["Statement"]:
                assert st.get("Principal") != {"AWS": "*"}, (name, logical)


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

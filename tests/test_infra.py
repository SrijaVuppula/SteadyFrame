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
    assert len(bedrock) == 2, bedrock  # the ECS task role and the Lambda worker's role
    for s in bedrock:
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
    o.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": Match.object_like(
                {
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": 50, "Unit": "USD"},
                }
            ),
            "NotificationsWithSubscribers": Match.array_with(
                [
                    Match.object_like(
                        {
                            "Subscribers": [
                                {"Address": "alerts@example.com", "SubscriptionType": "EMAIL"}
                            ]
                        }
                    )
                ]
            ),
        },
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


def test_worker_can_be_kept_warm():
    mod = _load_app_module()
    app = App(context={"skip_docker_build": "true", "worker_min_tasks": "1"})
    t = Template.from_stack(mod.build(app)["worker"])
    t.has_resource_properties("AWS::ECS::Service", {"DesiredCount": 1})
    t.has_resource_properties(
        "AWS::ApplicationAutoScaling::ScalableTarget", {"MinCapacity": 1, "MaxCapacity": 2}
    )
    env = t.find_resources("AWS::ECS::TaskDefinition")
    names = [
        e["Name"]
        for td in env.values()
        for c in td["Properties"]["ContainerDefinitions"]
        for e in c.get("Environment", [])
    ]
    assert "WORKER_IDLE_EXIT_S" not in names  # a warm task must not exit when idle


def test_worker_scales_to_zero_by_default(templates):
    t = templates["worker"]
    t.has_resource_properties("AWS::ECS::Service", {"DesiredCount": 0})
    t.has_resource_properties("AWS::ApplicationAutoScaling::ScalableTarget", {"MinCapacity": 0})


# ---------------------------------------------------------------- worker_engine=cool

COOL_IMAGE = "123456789012.dkr.ecr.us-east-1.amazonaws.com/example/cool-opencv:python-3.11"
ECS_AL2023_ARM64 = "/aws/service/ecs/optimized-ami/amazon-linux-2023/arm64/recommended/image_id"


def _env(task_definition: dict) -> dict:
    (c,) = task_definition["Properties"]["ContainerDefinitions"]
    return {e["Name"]: e["Value"] for e in c.get("Environment", [])}


@pytest.fixture(scope="module")
def cool():
    mod = _load_app_module()
    app = App(
        context={
            "skip_docker_build": "true",
            "bedrock_model_id": "us.example.model-v1:0",
            "worker_engine": "cool",
            "cool_image": COOL_IMAGE,
        }
    )
    built = mod.build(app)
    return {k: Template.from_stack(built[k]) for k in ("worker", "observability")}


def test_default_engine_is_fargate_without_ec2_capacity(templates):
    t = templates["worker"]
    t.resource_count_is("AWS::ECS::Service", 1)
    t.has_resource_properties("AWS::ECS::Service", {"LaunchType": "FARGATE"})
    for kind in (
        "AWS::AutoScaling::AutoScalingGroup",
        "AWS::EC2::LaunchTemplate",
        "AWS::ECS::CapacityProvider",
        "AWS::ECS::ClusterCapacityProviderAssociations",
    ):
        assert t.find_resources(kind) == {}, kind
    doc = json.dumps(t.to_json())
    assert "aws-marketplace" not in doc and "STEADYFRAME_OPENCV_ENGINE" not in doc


def test_cool_engine_runs_on_graviton4_instances_in_public_subnets(cool):
    t = cool["worker"]
    t.has_resource_properties(
        "AWS::EC2::LaunchTemplate",
        {
            "LaunchTemplateData": Match.object_like(
                {
                    "InstanceType": "c8g.large",
                    # IMDSv2, one hop: bridge-mode containers cannot reach the instance role
                    "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
                    "NetworkInterfaces": [
                        Match.object_like({"AssociatePublicIpAddress": True, "DeviceIndex": 0})
                    ],
                }
            )
        },
    )
    params = t.to_json()["Parameters"]
    assert any(p.get("Default") == ECS_AL2023_ARM64 for p in params.values())
    (asg,) = t.find_resources("AWS::AutoScaling::AutoScalingGroup").values()
    assert asg["Properties"]["MinSize"] == "0" and asg["Properties"]["MaxSize"] == "2"
    assert asg["Properties"]["NewInstancesProtectedFromScaleIn"] is True
    subnets = [s["Ref"] for s in asg["Properties"]["VPCZoneIdentifier"]]
    assert len(subnets) == 2 and all("public" in s for s in subnets)
    assert t.find_resources("AWS::EC2::NatGateway") == {}
    (cp_id,) = t.find_resources("AWS::ECS::CapacityProvider")
    t.has_resource_properties(
        "AWS::ECS::CapacityProvider",
        {
            "AutoScalingGroupProvider": Match.object_like(
                {
                    "ManagedScaling": Match.object_like({"Status": "ENABLED"}),
                    "ManagedTerminationProtection": "ENABLED",
                }
            )
        },
    )
    t.has_resource_properties(
        "AWS::ECS::ClusterCapacityProviderAssociations",
        {"CapacityProviders": [{"Ref": cp_id}]},
    )


def test_cool_task_is_ec2_arm64_bridge_with_the_fargate_env_plus_engine(cool, templates):
    t = cool["worker"]
    (td,) = t.find_resources("AWS::ECS::TaskDefinition").values()
    p = td["Properties"]
    assert p["RequiresCompatibilities"] == ["EC2"]
    assert p["NetworkMode"] == "bridge"
    assert p["PlacementConstraints"] == [
        {"Type": "memberOf", "Expression": "attribute:ecs.cpu-architecture == arm64"}
    ]
    (c,) = p["ContainerDefinitions"]
    assert c["Cpu"] == 2048 and c["MemoryReservation"] <= 3584  # one task fits a c8g.large
    assert c["StopTimeout"] == 120 and c["LogConfiguration"]["LogDriver"] == "awslogs"
    env = _env(td)
    assert env["STEADYFRAME_OPENCV_ENGINE"] == "cool"
    assert env["HOME"] == "/tmp"
    assert env["AWS_REGION"] == {"Ref": "AWS::Region"}
    (fargate_td,) = templates["worker"].find_resources("AWS::ECS::TaskDefinition").values()
    assert set(env) == set(_env(fargate_td)) | {"HOME", "STEADYFRAME_OPENCV_ENGINE"}
    for k, v in _env(fargate_td).items():
        assert env[k] == v, k


def test_cool_service_uses_the_capacity_provider_and_the_same_scaling(cool, templates):
    t = cool["worker"]
    t.resource_count_is("AWS::ECS::Service", 1)
    t.resource_count_is("AWS::ECS::TaskDefinition", 1)
    ((svc_id, svc),) = t.find_resources("AWS::ECS::Service").items()
    p = svc["Properties"]
    assert "LaunchType" not in p and "NetworkConfiguration" not in p
    (cp_id,) = t.find_resources("AWS::ECS::CapacityProvider")
    assert p["CapacityProviderStrategy"] == [{"CapacityProvider": {"Ref": cp_id}, "Weight": 1}]
    assert p["DesiredCount"] == 0
    (assoc_id,) = t.find_resources("AWS::ECS::ClusterCapacityProviderAssociations")
    assert assoc_id in svc["DependsOn"]  # created after, deleted before the association
    t.has_resource_properties(
        "AWS::ApplicationAutoScaling::ScalableTarget", {"MinCapacity": 0, "MaxCapacity": 2}
    )

    def steps(tpl):
        return sorted(
            json.dumps(r["Properties"]["StepScalingPolicyConfiguration"], sort_keys=True)
            for r in tpl.find_resources("AWS::ApplicationAutoScaling::ScalingPolicy").values()
        )

    # same scaling as the ECS worker has when it is the only worker (no Lambda in front)
    assert len(steps(t)) == 2 and steps(t) == steps(_worker_template(lambda_worker="false"))
    # the dashboard follows the one worker service there is
    assert f"ExportsOutputFnGetAtt{svc_id}Name" in json.dumps(cool["observability"].to_json())


def test_register_usage_is_on_the_task_role_only(cool):
    t = cool["worker"]
    (td,) = t.find_resources("AWS::ECS::TaskDefinition").values()
    task_role = td["Properties"]["TaskRoleArn"]["Fn::GetAtt"][0]
    holders = []
    for res in t.find_resources("AWS::IAM::Policy").values():
        roles = [r["Ref"] for r in res["Properties"]["Roles"]]
        for st in res["Properties"]["PolicyDocument"]["Statement"]:
            actions = _as_list(st["Action"])
            if any(a.startswith("aws-marketplace:") for a in actions):
                assert actions == ["aws-marketplace:RegisterUsage"], st
                holders.extend(roles)
            if task_role in roles and "*" in _as_list(st.get("Resource")):
                assert actions in (["cloudwatch:PutMetricData"], ["aws-marketplace:RegisterUsage"])
    assert holders == [task_role]
    for res in t.find_resources("AWS::IAM::Role").values():
        assert "aws-marketplace" not in json.dumps(res["Properties"])


def test_cool_instance_type_can_be_overridden():
    mod = _load_app_module()
    app = App(
        context={
            "skip_docker_build": "true",
            "worker_engine": "cool",
            "cool_image": COOL_IMAGE,
            "cool_instance_type": "m8g.xlarge",
            "worker_min_tasks": "1",
        }
    )
    t = Template.from_stack(mod.build(app)["worker"])
    t.has_resource_properties(
        "AWS::EC2::LaunchTemplate",
        {"LaunchTemplateData": Match.object_like({"InstanceType": "m8g.xlarge"})},
    )
    t.has_resource_properties("AWS::ECS::Service", {"DesiredCount": 1})
    t.has_resource_properties(
        "AWS::ApplicationAutoScaling::ScalableTarget", {"MinCapacity": 1, "MaxCapacity": 2}
    )


@pytest.mark.parametrize(
    "ctx, message",
    [
        ({"worker_engine": "cool"}, "worker_engine=cool needs -c cool_image="),
        ({"worker_engine": "cool", "cool_image": "  "}, "worker_engine=cool needs -c cool_image="),
        ({"worker_engine": "ec2"}, "worker_engine must be one of fargate, cool"),
        (
            {"worker_engine": "cool", "cool_image": COOL_IMAGE, "cool_instance_type": "c7g.large"},
            "must be a Graviton4 type",
        ),
    ],
)
def test_unusable_worker_engine_context_fails_synth(ctx, message):
    mod = _load_app_module()
    app = App(context={"skip_docker_build": "true", **ctx})
    with pytest.raises(ValueError, match=message):
        mod.build(app)


def _worker_template(**ctx) -> Template:
    mod = _load_app_module()
    app = App(
        context={"skip_docker_build": "true", "bedrock_model_id": "us.example.model-v1:0", **ctx}
    )
    built = mod.build(app)
    app.synth()
    return Template.from_stack(built["worker"])


def test_lambda_worker_takes_the_queue_first(templates):
    t = templates["worker"]
    fns = [
        r["Properties"]
        for r in t.find_resources("AWS::Lambda::Function").values()
        if r["Properties"].get("PackageType") == "Image"
    ]
    assert len(fns) == 1
    fn = fns[0]
    assert fn["Architectures"] == ["arm64"]
    assert fn["MemorySize"] == 3008 and fn["Timeout"] == 900
    assert fn["EphemeralStorage"] == {"Size": 2048}
    env = fn["Environment"]["Variables"]
    assert "AWS_REGION" not in env and "WORKER_IDLE_EXIT_S" not in env  # reserved / ECS only
    assert env["HOME"] == "/tmp" and env["MPLCONFIGDIR"] == "/tmp/mpl"
    assert env["STEADYFRAME_MODE"] == "aws" and env["STEADYFRAME_BEDROCK_MODEL_ID"]
    t.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {
            "BatchSize": 1,
            "ScalingConfig": {"MaximumConcurrency": 2},
            "FunctionResponseTypes": ["ReportBatchItemFailures"],
        },
    )
    t.has_resource_properties(
        "AWS::Events::Rule",
        {
            "ScheduleExpression": "rate(5 minutes)",
            "Targets": Match.array_with([Match.object_like({"Input": '{"warmup":true}'})]),
        },
    )
    # the ECS service is the fallback: it scales out only on messages left visible for 2 min
    alarms = t.find_resources("AWS::CloudWatch::Alarm")
    assert any(a["Properties"].get("EvaluationPeriods") == 2 for a in alarms.values())


def test_lambda_worker_can_be_turned_off():
    t = _worker_template(lambda_worker="false")
    assert not [
        r
        for r in t.find_resources("AWS::Lambda::Function").values()
        if r["Properties"].get("PackageType") == "Image"
    ]
    t.resource_count_is("AWS::Lambda::EventSourceMapping", 0)

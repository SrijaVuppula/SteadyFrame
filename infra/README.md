# infra: AWS CDK (Python)

Seven stacks, region-agnostic, deployed together:

| stack | what |
|---|---|
| `SteadyFrame-Storage` | one private S3 bucket (`uploads/`, `outputs/`, `samples/`), SSE-S3, TLS-only, lifecycle deletes `uploads/` and `outputs/` after 1 day, CORS for browser PUTs; the three sample clips are copied in at deploy time |
| `SteadyFrame-Data` | DynamoDB `jobs` (pk `job_id`) and `traces` (pk `job_id`, sk `seq`), on-demand, TTL 7 days (`_ttl`) |
| `SteadyFrame-Queue` | SQS jobs queue (20 min visibility, long polling) + dead-letter queue after 2 receives |
| `SteadyFrame-Api` | HTTP API -> one arm64 Python 3.11 Lambda (`service/lambda/handler.py`, boto3 only) |
| `SteadyFrame-Worker` | VPC (public subnets, no NAT), ECS cluster, Fargate task 2 vCPU / 4 GB on **ARM64 (Graviton)** from the repo `Dockerfile` (`linux/arm64`), service desired 0, step scaling 0..2 on queue backlog, Bedrock invoke scoped to the configured model, logs 2 weeks. With `worker_engine=cool`: Graviton4 EC2 capacity and the COOL image instead (see [COOL worker](#cool-worker-optional)) |
| `SteadyFrame-Web` | S3 + CloudFront for `web/dist`; `/api/*` is forwarded to the HTTP API |
| `SteadyFrame-Observability` | CloudWatch dashboard (job duration, realtime factor, iterations/segment, failures, queue depth, worker CPU/memory, API), alarms on DLQ > 0, job failures and API errors, SNS e-mail from `alert_email` |

Outputs: `ApiUrl` (Api), `WebUrl` (Web), `BucketName` (Storage). `make deploy` writes them to
`infra/cdk-outputs.json`, which `service/smoke.py` reads.

## Prerequisites

- Python venv with the infra extra: `.venv/bin/pip install -r infra/requirements-infra.lock`
  (aws-cdk-lib 2.270.0). Node 18+ for the CDK CLI: `cd infra && npm ci` pins `aws-cdk` 2.1142.0,
  then use `npx cdk ...` from `infra/` (or install it globally).
- Docker with buildx for the arm64 image (`docker buildx create --use` once on an x86 machine;
  QEMU emulation is enough, the build takes a few minutes). The Docker daemon is only needed
  at `cdk deploy`, not at `cdk synth`.
- AWS credentials with admin rights for the deployment itself, and a bootstrapped account:
  `npx cdk bootstrap aws://ACCOUNT/REGION`.
- Bedrock model access enabled in the region; copy the inference profile id (looks like
  `us.<vendor>.<model>-v1:0`) into `cdk.json` -> `bedrock_model_id`. Leave it empty to deploy
  without any Bedrock permission (the worker then always runs the fixed policy).

## Deploy

```
cd infra
npx cdk synth --no-lookups                 # offline check; needs the venv's python in ../.venv
npx cdk deploy --all --require-approval never --outputs-file cdk-outputs.json
cd .. && .venv/bin/python service/smoke.py --outputs infra/cdk-outputs.json
```

`cdk.json` runs `../.venv/bin/python app.py`; pass `--app "python app.py"` if the venv lives
elsewhere. Context knobs (`-c key=value` or `cdk.json`):

| key | meaning |
|---|---|
| `alert_email` | e-mail subscribed to the alarm topic (confirm the subscription mail) |
| `bedrock_model_id` | inference profile id the worker may call; also sets `STEADYFRAME_BEDROCK_MODEL_ID` in the task |
| `skip_docker_build` | `true` swaps the worker image for a public placeholder so `synth` needs no Docker (CI, `tests/test_infra.py`, `export_policies.py`). Never deploy with it. |
| `web_origin` | CORS origin allowed to PUT uploads (default `*`; tighten to the `WebUrl` after the first deploy) |
| `web_dist` | frontend build directory (default `web/dist`; a placeholder page is deployed if missing) |
| `worker_min_tasks` | worker tasks kept running with an empty queue (default `0`: scale to zero). `1` removes the cold start (several minutes for the first job after idle) for about 2 USD a day; useful while judges are trying the endpoint |
| `worker_engine` | `fargate` (default, the template above) or `cool` (the COOL container on Graviton4 EC2, [COOL worker](#cool-worker-optional)); anything else fails synth |
| `cool_image` | `worker_engine=cool` only, required (synth fails without it): image URI of the delivery option "OpenCV 5 for Graviton4 - Python 3.11" |
| `cool_instance_type` | `worker_engine=cool` only: Graviton4 instance type, `c8g`, `m8g` or `r8g` family (default `c8g.large`) |

From the repo root, `make deploy CDK_ARGS="-c bedrock_model_id=... -c alert_email=..."` passes
the same knobs. Pass them on every deploy: a value left out falls back to `cdk.json`, where
`bedrock_model_id` and `alert_email` are empty.

The sample clips are rendered into `infra/.samples/` at synth time by `service/samples.py`
(gitignored: they flash). `web/dist` comes from `make web`.

Order of operations on a fresh account: `make web` (optional), `make deploy`, `make smoke`,
open `WebUrl`.

## COOL worker (optional)

`-c worker_engine=cool` runs the same worker on "Cloud-Optimized OpenCV for AWS Graviton4
[Docker]" (AWS Marketplace, https://aws.amazon.com/marketplace/pp/prodview-fsbcuniykfunw)
instead of the `opencv-python-headless` wheel. The default stays Fargate.

Why not Fargate: the container is built for Neoverse-V2 and supports Graviton4 instance
families (m8g, c8g, r8g) on Amazon ECS and EKS only. Fargate's ARM64 tasks are not Graviton4,
and the listing names Fargate and earlier Graviton generations as unsupported targets.

What changes in `SteadyFrame-Worker` (the Fargate task and service are left out; there is
one worker service either way):

- an Auto Scaling group of Graviton4 instances (`c8g.large`, `-c cool_instance_type=...` to
  change), ECS-optimised Amazon Linux 2023 arm64 (public SSM parameter), min 0 / max 2, in
  the same public subnets with public IPs, no NAT, no inbound rule, IMDSv2 with a hop limit
  of 1 (bridge-mode containers cannot reach it, so the worker holds only the task role)
- an ECS capacity provider on that group, attached to the cluster: managed scaling (the group
  follows the tasks, 0 instances at 0 tasks) and managed termination protection (an instance
  running a job is not scaled in under it)
- the worker task for the EC2 launch type, bridge networking (awsvpc tasks on EC2 get no
  public IP, and there is no NAT), arm64 placement, 2 vCPU and a soft 3 GiB memory
  reservation so one task fits a c8g.large. Same environment, log group and IAM grants as
  the Fargate task, plus `HOME=/tmp` and `STEADYFRAME_OPENCV_ENGINE=cool`, and
  `aws-marketplace:RegisterUsage` on the task role (the entitlement check inside the
  image's `libopencv_core` calls it with the task's credentials)
- the service places tasks through the capacity provider; desired count, `worker_min_tasks`
  and the step scaling on queue backlog are the same as on Fargate
- the image is built from `Dockerfile.cool` (`FROM` the `cool_image`, `linux/arm64`): the
  runtime requirements from `requirements.lock` except `opencv-python-headless`, the package
  with `--no-deps`, uid 1000, `HOME=/tmp`. The build never imports cv2 (the entitlement
  check fails outside ECS); it checks the wheel is absent and that cv2 is found without
  loading it. Assumption, checked at build time: the image's Python 3.11 is the
  `python3.11` / `python3` / `python` on its PATH (else `/opt/cool/venvs/python_3.11`)

Prerequisites, once per account:

1. Subscribe to the container listing above with the AWS account that deploys and runs the
   worker ("Continue to Subscribe", accept the terms). The entitlement is checked against
   the account the task runs in. The AMI listing used by `bench/` is a separate product and
   not needed here.
2. "Continue to Configuration", delivery option "OpenCV 5 for Graviton4 - Python 3.11": copy
   the image URI shown there. It is `cool_image`, and its registry host is where Docker has
   to be logged in when `cdk deploy` builds the image:
   `aws ecr get-login-password --region <region of the URI> | docker login --username AWS --password-stdin <registry host>`

Deploy (Docker logged in to that registry, as above):

```
make deploy CDK_ARGS="-c bedrock_model_id=<id> -c alert_email=<email> -c worker_engine=cool -c cool_image=<uri>"
```

Pass the two flags on every deploy: a deploy without them switches back to Fargate (see
below).

Switching an existing deployment between engines replaces the worker service, and
`SteadyFrame-Observability` imports its name: CloudFormation refuses to change or delete an
export that another stack uses. Remove that stack first, then deploy; `make deploy` creates it
again (confirm the alarm e-mail subscription again):

```
cd infra && npx cdk destroy SteadyFrame-Observability --force && cd ..
make deploy CDK_ARGS="..."
```

Cost: the instance's on-demand price (check it on the day) and its public IPv4 address while
an instance runs, plus 0.03 USD per container hour for the COOL image after its 7-day free
trial. Nothing runs at an empty queue: the service scales to 0 tasks as on Fargate, and
managed scaling then takes the group to 0 instances (ECS waits about 15 minutes of empty
capacity before it scales in). The cold start is longer than on Fargate, since an instance
has to boot and pull the image before the first job.

Verify (CloudWatch Logs, the `WorkerLogs` group of `SteadyFrame-Worker`, stream prefix
`worker`):

- the `"msg": "package"` line at worker start: `build.file` is `cv2.__file__`, and should be
  the image's install (under `/opt/cool` if the image keeps the AMI's layout), not a
  `site-packages/cv2` from the wheel; `build.version` is `cv2.__version__`, and
  `build.kleidicv` (when the build lists it) comes from `cv2.getBuildInformation()`
- `GET /jobs/{id}`: `tool.opencv` is the OpenCV version the worker ran and `tool.engine` is
  `cool` (the job page shows "COOL build on Graviton4" next to it)
- a task that stops with exit code 133 failed the entitlement check before running any code:
  check the subscription (same account), the task role's `RegisterUsage` and egress (public
  IP on the instance)

Roll back: destroy `SteadyFrame-Observability` as above, then deploy without
`-c worker_engine=cool -c cool_image=...`. The Auto Scaling group, capacity provider, EC2 task
definition and service are deleted and the Fargate worker comes back. The Marketplace
subscription only costs while COOL containers run; cancel it under "Manage subscriptions"
when it is no longer needed.

## Destroy

```
cd infra && npx cdk destroy --all --force
```

Buckets are emptied by the `autoDeleteObjects` custom resource, tables and log groups have
`RemovalPolicy.DESTROY`, the ECS service scales to zero and is deleted with the stack. Nothing
billable remains except CloudWatch log data already ingested (free tier) and the bootstrap
stack, which you can leave or `aws cloudformation delete-stack --stack-name CDKToolkit`.

## Cost notes

- Idle: about 0 USD/month. The worker runs only while messages exist (desired count 0, no NAT
  gateway, public IPs instead). DynamoDB and SQS are on-demand, Lambda and CloudFront are in
  the free tier for demo traffic, S3 holds at most a day of job data. The dashboard costs
  3 USD/month after the first three free dashboards; the alarms are 0.10 USD each.
- Per job: a 2 vCPU / 4 GB ARM64 Fargate task is roughly 0.08 USD/hour (about 20% cheaper than
  x86); a 30 s clip finishes in a few minutes, so a job is about 0.5 cents plus the model call
  when `policy=agent` (a handful of short tool-use turns). Scale-in waits 10 idle minutes.
- The worker task also exits by itself after `WORKER_IDLE_EXIT_S` (600 s) without messages;
  the service restarts it until the scaling policy has brought the desired count to zero.
- With `worker_min_tasks=1` one task runs all the time: about 0.08 USD/hour for the task plus
  its public IPv4 address, roughly 2 USD a day. Deploy again with `worker_min_tasks=0` when
  judging ends.
- `worker_engine=cool`: instance on-demand price plus 0.03 USD per COOL container hour after
  the free trial, also 0 at an empty queue ([COOL worker](#cool-worker-optional)).
- With `alert_email` set, `SteadyFrame-Observability` also creates an account-wide monthly cost
  budget (`SteadyFrame-monthly`, 50 USD) that e-mails that address at 80% of actual spend and
  at 100% of the forecast. AWS Budgets e-mails need no confirmation; the first two budgets
  are free.

## IAM

`infra/policies/*.json` holds the effective policy documents per stack (roles and inline
policies), regenerated with `.venv/bin/python infra/export_policies.py`. Summary:

- API Lambda: `s3:PutObject/DeleteObject` on `uploads/*`, `s3:GetObject` on `uploads/*`,
  `outputs/*`, `samples/*`, `s3:ListBucket` limited to those prefixes, `GetItem/PutItem/
  UpdateItem` on jobs, `Query` on traces, `sqs:SendMessage`.
- Worker task: `s3:GetObject` on `uploads/*` and `outputs/*`, `s3:PutObject` on `outputs/*`,
  `GetItem/UpdateItem` on jobs, `PutItem/BatchWriteItem` on traces, receive/delete/change-
  visibility on the queue, `cloudwatch:PutMetricData` limited to namespace `SteadyFrame`,
  `bedrock:InvokeModel` + `InvokeModelWithResponseStream` on the configured inference profile
  and its foundation model only. The execution role only pulls the image and writes logs.
- `worker_engine=cool` adds `aws-marketplace:RegisterUsage` (no resource-level scope, so
  `*`) to the worker task role, nowhere else, and an instance role for the ECS agent (register
  / deregister / submit state on the cluster, poll with a cluster condition, discover poll
  endpoint, `ecr:GetAuthorizationToken`, log events). `infra/policies/` is exported from the
  default (Fargate) synth.
- Deployment custom resources (bucket deployment, auto-delete) get the permissions CDK
  generates for them.

## Scaling detail

Step scaling reads `ApproximateNumberOfMessagesVisible + ApproximateNumberOfMessagesNotVisible`
(in-flight messages count, otherwise a scale-in on an empty *visible* queue would stop the
task in the middle of the job it is working on). Backlog >= 1 for one minute adds a task
(max 2); backlog 0 for ten minutes removes one. The worker extends the SQS visibility every
five minutes while a job runs and stops cleanly on SIGTERM (`stopTimeout` 120 s).

## Local mode

`docker compose up --build` at the repo root runs the same worker image, the FastAPI variant
of the API (`service/local_api.py`) on :8000 and the web build on :8080, with no AWS at all.

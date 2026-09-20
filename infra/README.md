# infra: AWS CDK (Python)

Seven stacks, region-agnostic, deployed together:

| stack | what |
|---|---|
| `SteadyFrame-Storage` | one private S3 bucket (`uploads/`, `outputs/`, `samples/`), SSE-S3, TLS-only, lifecycle deletes `uploads/` and `outputs/` after 1 day, CORS for browser PUTs; the three sample clips are copied in at deploy time |
| `SteadyFrame-Data` | DynamoDB `jobs` (pk `job_id`) and `traces` (pk `job_id`, sk `seq`), on-demand, TTL 7 days (`_ttl`) |
| `SteadyFrame-Queue` | SQS jobs queue (20 min visibility, long polling) + dead-letter queue after 2 receives |
| `SteadyFrame-Api` | HTTP API -> one arm64 Python 3.11 Lambda (`service/lambda/handler.py`, boto3 only) |
| `SteadyFrame-Worker` | VPC (public subnets, no NAT), ECS cluster, Fargate task 2 vCPU / 4 GB on **ARM64 (Graviton)** from the repo `Dockerfile` (`linux/arm64`), service desired 0, step scaling 0..2 on queue backlog, Bedrock invoke scoped to the configured model, logs 2 weeks |
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

The sample clips are rendered into `infra/.samples/` at synth time by `service/samples.py`
(gitignored: they flash). `web/dist` comes from `make web`.

Order of operations on a fresh account: `make web` (optional), `make deploy`, `make smoke`,
open `WebUrl`.

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
- Set the account budget alarm (50 USD) by hand, see `docs/HUMAN_TASKS.md`.

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

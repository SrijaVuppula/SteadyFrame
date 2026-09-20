"""One dashboard, three alarms, one SNS topic."""

from __future__ import annotations

from aws_cdk import Duration, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from aws_cdk import aws_sqs as sqs
from constructs import Construct

NAMESPACE = "SteadyFrame"


def _metric(name: str, statistic: str, label: str | None = None) -> cloudwatch.Metric:
    return cloudwatch.Metric(
        namespace=NAMESPACE,
        metric_name=name,
        statistic=statistic,
        period=Duration.minutes(5),
        label=label or f"{name} ({statistic})",
    )


class ObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        queue: sqs.IQueue,
        dlq: sqs.IQueue,
        service: ecs.FargateService,
        api_function: lambda_.IFunction,
        alert_email: str = "",
        **kw,
    ) -> None:
        super().__init__(scope, id, **kw)
        self.topic = sns.Topic(self, "Alerts", display_name="SteadyFrame alerts")
        if alert_email:
            self.topic.add_subscription(subs.EmailSubscription(alert_email))
        action = cw_actions.SnsAction(self.topic)

        self.dashboard = cloudwatch.Dashboard(
            self, "Dashboard", dashboard_name="SteadyFrame", default_interval=Duration.hours(6)
        )
        self.dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Job duration (s)",
                left=[_metric("JobDuration", "Average"), _metric("JobDuration", "Maximum")],
                width=8,
            ),
            cloudwatch.GraphWidget(
                title="Analysis realtime factor (x)",
                left=[_metric("RealtimeFactor", "Average"), _metric("RealtimeFactor", "Minimum")],
                width=8,
            ),
            cloudwatch.GraphWidget(
                title="Iterations per segment",
                left=[_metric("IterationsPerSegment", "Average")],
                width=8,
            ),
        )
        self.dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Failures and approvals",
                left=[_metric("JobFailures", "Sum"), _metric("ApprovalsRequested", "Sum")],
                width=8,
            ),
            cloudwatch.GraphWidget(
                title="Queue depth",
                left=[
                    queue.metric_approximate_number_of_messages_visible(label="visible"),
                    queue.metric_approximate_number_of_messages_not_visible(label="in flight"),
                    dlq.metric_approximate_number_of_messages_visible(label="dead letter"),
                ],
                width=8,
            ),
            cloudwatch.GraphWidget(
                title="Worker CPU / memory (%)",
                left=[
                    service.metric_cpu_utilization(label="cpu"),
                    service.metric_memory_utilization(label="memory"),
                ],
                width=8,
            ),
        )
        self.dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="API",
                left=[api_function.metric_invocations(), api_function.metric_errors()],
                right=[api_function.metric_duration()],
                width=12,
            ),
            cloudwatch.GraphWidget(
                title="Running worker tasks (desired vs running)",
                left=[
                    cloudwatch.Metric(
                        namespace="ECS/ContainerInsights",
                        metric_name="RunningTaskCount",
                        dimensions_map={
                            "ClusterName": service.cluster.cluster_name,
                            "ServiceName": service.service_name,
                        },
                        statistic="Maximum",
                        period=Duration.minutes(1),
                    )
                ],
                width=12,
            ),
        )

        self.dlq_alarm = cloudwatch.Alarm(
            self,
            "DeadLetterAlarm",
            alarm_description="A job message ended in the dead-letter queue (worker crashed twice)",
            metric=dlq.metric_approximate_number_of_messages_visible(period=Duration.minutes(1)),
            threshold=0,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        self.failures_alarm = cloudwatch.Alarm(
            self,
            "JobFailuresAlarm",
            alarm_description="A job ended in error or failed verification",
            metric=_metric("JobFailures", "Sum"),
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        self.api_alarm = cloudwatch.Alarm(
            self,
            "ApiErrorsAlarm",
            alarm_description="The API Lambda raised an unhandled error",
            metric=api_function.metric_errors(period=Duration.minutes(5), statistic="Sum"),
            threshold=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        for alarm in (self.dlq_alarm, self.failures_alarm, self.api_alarm):
            alarm.add_alarm_action(action)

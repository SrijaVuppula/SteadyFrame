"""Frontend: S3 + CloudFront. ``/api/*`` goes to the HTTP API, everything else is the SPA."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Fn, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct


class WebStack(Stack):
    def __init__(
        self, scope: Construct, id: str, *, api_endpoint: str, dist_dir: Path, **kw
    ) -> None:
        super().__init__(scope, id, **kw)
        self.bucket = s3.Bucket(
            self,
            "WebBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        # https://abc.execute-api.<region>.amazonaws.com -> abc.execute-api.<region>.amazonaws.com
        api_domain = Fn.select(2, Fn.split("/", api_endpoint))
        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment="SteadyFrame web",
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                compress=True,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        api_domain, protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY
                    ),
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                )
            },
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=code,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                )
                for code in (403, 404)
            ],
        )
        s3deploy.BucketDeployment(
            self,
            "Deploy",
            sources=[s3deploy.Source.asset(str(dist_dir))],
            destination_bucket=self.bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
            memory_limit=256,
        )
        self.url = f"https://{self.distribution.distribution_domain_name}"
        CfnOutput(self, "WebUrl", value=self.url)

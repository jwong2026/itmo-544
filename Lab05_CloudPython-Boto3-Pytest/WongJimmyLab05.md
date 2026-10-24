Jimmy Wong\
October 24, 2026\
ITMO-544\
Lab 05 - Infrastructure as Python: From AWS CLI and Bash to boto3 and pytest

# Part 0: Set Up Your Lab05 Folder
![Screenshots of copy lab04 to lab05](photos/part-0_copy-lab-04.png)
The picture above shows that I copied from the whole lab 04 to new lab which is lab 05.\

![Screenshots of python3 venv](photos/part-0_pip-requirements-install.png)
The picture above shows that the *pip install -r requirements.txt* is executed.\

![Screenshots of show venv file](photos/part-0_python-venv-file.png)
The picture above shows *printf '.venv/\n__pycache__/\n.pytest_cache/\nstack_outputs.json\nstack_outputs.env\n' >> .gitignore* is displayed in the .gitignore file that GitHub ignores any specific files noted before pushing onto a repository.\

![Screenshots of python check identity from aws credential](photos/part-0_python3-check-identity.png)
The picture above shows *python3 -c "import boto3; print(boto3.client('sts').get_caller_identity()['Arn'])"* is executed successfully to display who current IAM is.\

![Screenshots of create folders and init py files](photos/part-0_create-files-folders.png)
The picture above shows that I created required folders and *__init__.py* file in each folder.\

![Screenshots of show pip list](photos/part-0_pip-list.png)
The picture above shows that *pip list | grep -E "boto3|pytest|moto"* successfully displayed all 3 of them.\

# Part A: From AWS CLI to boto3
Question: You can explain why *ignore_errors("NoSuchEntity")* is safer than *2>/dev/null || true*.\
Answer: *2>/dev/null || true* would continue regarding what errors may be caused and be suppressed which would be difficult to find what kind of errors or where to find them. *ignore_errors("NoSuchEntity")* is safer because python would check error codes and if an error code is discovered, it would halt a script and print what kind of error code is.\

# Part B: Configuration and Helpers
![Screenshots of python print two tiers](photos/part-b_python-print-two-tiers.png)
The picture above shows the following command: *python3 -c "from stack.config import Settings; print(Settings.from_file('.env').tiers)"* prints two *Tiers(...)* objects with your real names. If a key is missing, the error lists exactly which ones.\

# Part C: Storage and IAM
Question: You can name which *ignore_errors* codes appear in *storage.py* and what each one means.\
Answer: 
- *"EntityAlreadyExists"*: Check if roles or instance profiles existed, or otherwise it would print an error for what happened.\
- *"NoSuchEntity"*: Check if roles or instance profiles never existed, or otherwise it would print an error for what happened.\
- *"NoSuchBucket"*: Check if a bucket never existed on AWS, or otherwise it would print an error for what happened.\

# Part E: Network, Load Balancer, and Auto Scaling
Question: You can point to the line in *ensure_asg* that makes the ASG trust the load balancer's health check, and say why that matters for recovery.\
Answer: The line in *ensure_asg* that makes the ASG trust the load balancer's health check is ***HealthCheckType="ELB"***. For this lab, an ASG only creates EC2 instances when current EC2 instances' health status are being checked and maintained on being responsive to the ASG. Uploader and Viewer websites would give responsive on health check with "HTTP 200" which is ok and good to continue until either website stops giving "HTTP 200" response then ASP detects that non "HTTP 200" then deploys a new EC2 instance to replace old instance automatically without having a human interaction.\

# Part F: 
![Screenshots of py_compile *.py](photos/part-f_python-py-compile-all.png)
The picture above shows the following command: *python3 -m py_compile stack\*.py create_stack.py delete_stack.py* prints nothing. Do not run *create_stack.py* yet. The unit tests come first, and they are free.\

# Part G: Unit Tests (No AWS Account Needed)
![Screenshots of pytest ran twice](photos/part-g_pytest-twice.png)\
The picture above shows that pytest ran twice to ensure no errors are made.\

![Screenshots of pytest with s3:PutObject](photos/part-g_pytest-s3-putobject-twice.png)
The picture above shows that I changed from *"s3:PutObject"* to *"s3:\*"* and ran pytest to show an error or failure.\

![Screenshots of pytest with HealthCheckType](photos/part-g_healthchecktype-elb-ec2.png)
The picture above shows that I changed from *HealthCheckType="ELB"* to *"EC2"* and ran pytest to show an error or failure.\

![Screenshots of pytest ASG commented line](photos/part-g_asg.png)
The picture above shows that I did comment this line to call *restrict_app_security_group*. The following line is *network.restrict_app_security_group(aws, settings, alb_sg_id)*. It shows which test caught the error.\

![Screenshots of pytest reports 19 passed](photos/part-g_pytest-reports-19-passed.png)
The picture above shows is *pytest* reports 19 passed, and you completed at least one of the "break it on purpose" experiments.\

# Part: Integration and Chaos Tests (Against Your Real Stack)
![Screenshots of pytest collection only](photos/part-h_collection-14-integration-2-chaos.png)
The picture above shows the following command: *pytest --collect-only -m "integration or chaos"* which resulted 14 integration tests and 2 chaos tests.\

Question: you can explain why *test_every_target_becomes_healthy* polls with *wait_until* instead of checking once.\
Answer: The *test_every_target_becomes_healthy* with *wait_until* is necessary because EC2 instances do not become healthy instantly as soon as they are being created. EC2 instances need some time to execute what required packages are before uploader and viewer websites become available for clients to check on their websites. The *wait_until* allows tester(s) to wait until a time period ends and check targets' status.\

# Between Part H and I
![Screenshots of folder hierachy part 1](photos/part-h-i_checkpoint-folder-hierachy-part-1.png)
![Screenshots of folder hierachy part 2](photos/part-h-i_checkpoint-folder-hierachy-part-2.png)
The pictures above show every file and folder.\

# Part I: Run It End to End
![Screenshots of create_stack.py and pytest integration](photos/part-i_python-create-stack-py-pytest-integration.png)
The picture above shows the following commands: *python create_stack.py* and *pytest -m integration -v*.\

![Screenshots of Uploader and Viewer websites success](photos/part-i_uploader-viewer-websites-success.png)
The picture above shows both of the Uploader and Viewer websites are working without errors before experimenting "break it on purpose".\

![Screenshots of pytest chaos](photos/part-i_pytest-m-chaos-s-2nd-time.png)
The picture above shows the following command: *pytest -m chaos -s*.\

![Screenshots of Recovery SLO time is 60s part 1](photos/part-i_pytest-recovery-slo-seconds-60-fail-1.png)
![Screenshots of Recovery SLO time is 60s part 2](photos/part-i_pytest-recovery-slo-seconds-60-fail-2.png)
The pictures above show the pytest with tighten SLO time from 180s to 60s. I ran twice to ensure it actually failed within the SLO time.\

![Screenshots of pytest with SLO 60 seconds](photos/part-i_recovery-slo-seconds-60-pytest.png)
![Screenshots of pytest with SLO 60 seconds](photos/part-i_recovery-slo-seconds-60-pytest-1.png)
![Screenshots of pytest with SLO 60 seconds](photos/part-i_recovery-slo-seconds-60-pytest-2.png)
![Screenshots of Post-pytest result on website](photos/part-i_recovery-slo-seconds-60-pytest-websites-result.png)
The pictures above show that recovery SLO time is set to 60 seconds. I ran the chaos test a couple more times to see if I could get a fail on either instance, and I took a screenshot each result.\

![Screenshots of pytest with SLO 180 seconds](photos/part-i_recovery-slo-seconds-180-pytest.png)
The picture above shows that recovery SLO time is set to 180 seconds.\

![Screenshots of show stack_outputs.env file](photos/part-i_stack-outputs-env.png)
The picture above shows what *stack_outputs.env* have.\

![Screenshots of ?](photos/part-i_python-delete-stack-py.png)
The picture above shows the *delete_stack.py* is executed twice.\

![Screenshots of ?](photos/part-i_python-delete-stack-py-keep-foundation.png)
The picture above shows the *delete_stack.py* with *--keep-foundation* is executed without removing the S3 Bucket, IAM roles, and launch templates.\

# Part J: Challenges
## Tags Test Challenge:
![Screenshots of Challenge - Tag Test Success](photos/part-j_tags-test-success.png)
![Screenshots of Challenge - Tag Test Failure](photos/part-j_tags-test-failure.png)
I added this tag test codes:\
The codes below are in *tests/unit/test_stack_with_moto.py*.
```
from stack.compute import launch_template_data

def test_launch_template_tags_instance(env):
    settings, aws = env
        for tier in settings.tiers:
            data = launch_template_data(settings, tier)
            tags_spec = data.get("TagSpecifications", [])
            assert len(tags_spec) > 0, f"Missing TagSpecifications for {tier.name}"
            assert tags_spec[0]["ResourceType"] == "instance"
            tags = {t["Key"]: t["Value"] for t in tags_spec[0]["Tags"]}
            assert tags.get("Name") == f"{tier.name}-app"
```
The codes below are in *tests/integration/test_infrastructure.py*.
```
def test_deployed_launch_templates_contain_name_tags(aws, settings):
    for tier in settings.tiers:
        response = aws.ec2.describe_launch_template_versions(LaunchTemplateName=tier.lt_name, Versions=["1"])
        data = response["LaunchTemplateVersions"][0]["LaunchTemplateData"]
        tags_spec = data.get("TagSpecifications", [])
        assert len(tags_spec) > 0
        tags = {t["Key"]: t["Value"] for t in tags_spec[0]["Tags"]}
        assert tags.get("Name") == f"{tier.name}-app"
```

## A Failing Path:
![Screenshots of Challenge - Failing Path](photos/part-j_failing-path.png)
I added new line codes and commented one line:\
The codes below are in *stack/config.py*.
```
try:
    recovery_slo = int(v["RECOVERY_SLO_SECONDS"])
except ValueError:
    raise ConfigError(
        f"RECOVERY_SLO_SECONDS must be an integer numeric string (e.g., '180'). Got: '{v.get('RECOVERY_SLOT_SECONDS')}'"
    )

return cls(
    region=v["AWS_REGION"], ami_id=v["AMI_ID"], key_name=v["KEY_NAME"],
    instance_type=v["INSTANCE_TYPE"], bucket_name=v["BUCKET_NAME"],
    app_sg_id=v["APP_SECURITY_GROUP_ID"], alb_name=v["ALB_NAME"],
    alb_sg_name=v["ALB_SG_NAME"], az_a=v["AZ_A"], az_b=v["AZ_B"],
    # recovery_slo_seconds=int(v["RECOVERY_SLO_SECONDS"]),
		recovery_slo_seconds = recovery_slo,
    uploader=tier("UPLOADER"), viewer=tier("VIEWER"),
)
```
The codes below are in *tests/unit/test_config.py*.
```
def test_invalid_recovery_slo_seconds_throws_config_error():
    values = dict(FAKE_VALUES)
    values["RECOVERY_SLO_SECONDS"] = "fast"
    with pytest.raises(ConfigError) as err:
        Settings.from_values(values)
    assert "must be an integer numeric string" in str(err.value)
```

## Dry Run:
![Screenshots of Challenge - Dry Run](photos/part-j_dry-run.png)
I added new line codes:\
The codes are in *create_stack.py*.
```
def main() -> None:
    ...
    parser.add_argument("--dry-run", action="store_true", help="print infrastructure changes without applying them")
    ...
    outputs = create_stack(settings, AwsClients.create(settings.region), dry_run=args.dry_run)
    outputs.save()
    if args.dry_run:
        print("\n[DRY RUN COMPLETE] No live AWS modificiations were committed.")
    else:
        print()
        print(f"Uploader: http://{outputs.alb_dns_name}:{settings.uploader.listener_port}/")
        print(f"Viewer: http://{outputs.alb_dns_name}:{settings.viewer.listener_port}/")
        print("Give the target groups 1 to 2 minutes to report healthy, then run: pytest -m integration")
```
The codes are in *stack/storage.py*.
```
def ensure_bucket(aws: AwsClients, settings: Settings, dry_run: bool = False) -> None:
    if dry_run:
        log.info("[DRY RUN] Would check and ensure S3 Bucket: %s", settings.bucket_name)
        return
    try:
        aws.s3.head_bucket(Bucket=settings.bucket_name)
        log.info("Bucket %s already exists, skipping.", settings.bucket_name)
    except ClientError as err:
        # 404 means "free to create". 403 means someone else owns that name, so we must stop.
        if error_code(err) not in ("404", "NoSuchBucket", "NotFound"):
            raise
        args = {"Bucket": settings.bucket_name}
        if settings.region != "us-east-1":
            args["CreateBucketConfiguration"] = {"LocationConstraint": settings.region}
        aws.s3.create_bucket(**args)
        log.info("Created bucket %s", settings.bucket_name)
    # Not in the bash version: nothing in this lab ever needs a public bucket.
    aws.s3.put_public_access_block(
        Bucket=settings.bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
```
The codes are in *stack/runner.py*.
```
def create_stack(..., dry_run: bool = False)
    ...
    log.info("== IAM roles and instance profiles ==")
    if dry_run:
        for tier in settings.tiers:
            log.info("[DRY RUN] Would ensure IAM role and profile for tier: %s", tier.name)
    else:
        for	tier in settings.tiers:
            storage.ensure_role_and_profile(aws, settings, tier)
        log.info("Waiting %ss for IAM propagation...", iam_wait)
        sleep(iam_wait)
    if dry_run:
        log.info("[DRY RUN] Bypassing remainder of stack creation details.")
        return StackOutputs(
            vpc_id="vpc-dryrun",
            subnet_a="subnet-a-dryrun",
            subnet_b="subnet-b-dryrun",
            alb_security_group_id="sg-dryrun",
            alb_arn="arn-dryrun",
            alb_dns_name="://amazonaws.com",
            uploader_tg_arn="tg-up-dryrun",
            viewer_tg_arn="tg-vw-dryrun",
    		)
    log.info("== Launch templates ==")
    ...
```

## Drift Check
![Screenshots of Challenge - Drift Check Pass](photos/part-j_drift-check-pass.png)
![Screenshots of Challenge - Drift Check Fail 1](photos/part-j_drift-check-fail.png)
![Screenshots of Challenge - Drift Check Fail 2](photos/part-j_drift-check-fail-2.png)
I added new line codes:\
The codes are in *tests/integration/test_infrastructure.py*.
```
def test_security_drift_port_22_not_open_to_world(aws, settings):
    group = aws.ec2.describe_security_groups(GroupIds=[settings.app_sg_id])["SecurityGroups"][0]
    for rule in group.get("IpPermissions", []):
        from_port = rule.get("FromPort")
        to_port = rule.get("ToPort")
        if (from_port is None) or (from_port <= 22 <= to_port):
            for ip_range in rule.get("IpRanges", []):
                assert ip_range.get("CidrIp") != "0.0.0.0/0", (f"CRITICAL SECURITY DRIFT DETECTED: Port 22 is open to the world on security group {settings.app_sg_id}!")
```
Question: What would a daily run of this test give a team?\
Answer: To ensure the port 22 is not open to the world.\

## Reflect:
Question: Pick one place where the bash version was shorter than the Python version. Write two sentences on what the extra Python lines bought you.\
Answer: I chose S3 bucket codes to compare between bash and python. The bash codes show that it can either check or create a S3 bucket while suppressing errors in hide. The python codes show that it will catch an error to display a 404 page instead being suppressed and continued, and this will halt the execution of a script.\

The Bash codes are from Lab03 & Lab04 below:
```
echo "== S3 bucket =="
if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null; then
    echo "Bucket already exists, skipping."
else
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" --create-bucket-configuration LocationConstraint="$AWS_REGION"
fi
```
The Python codes are below:
```
def ensure_bucket(aws: AwsClients, settings: Settings) -> None:
    try:
        aws.s3.head_bucket(Bucket=settings.bucket_name)
        log.info("Bucket	%s	already	exists,	skipping.",	settings.bucket_name)
    except ClientError as err:
        # 404 means "free to create". 403 means someone else owns that name, so we must stop.
        if error_code(err) not in ("404", "NoSuchBucket", "NotFound"):
            raise
        args = {"Bucket": settings.bucket_name}
        if settings.region != "us-east-1":
            args["CreateBucketConfiguration"] = {"LocationConstraint": settings.region}
        aws.s3.create_bucket(**args)
        log.info("Created	bucket	%s",	settings.bucket_name)
    # Not in the bash version: nothing in this lab ever needs a public bucket.
    aws.s3.put_public_access_block(
        Bucket=settings.bucket_name,
        PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
```

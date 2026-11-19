Jimmy Wong\
November 6, 2026\
ITMO-544\
Lab 07 - Infrastructure as Code with Terraform: Rebuild the Weather Advisor

# Part 0: Install Terraform and Set Up Your Lab07 Folder
![Screenshot of aws sts get caller identity](photos/part-0_aws-sts-get-caller-identity.png)
The picture above shows that Terraform is installed and displays the current version.

# Part A: Your First Terraform
![Screenshot of terraform plan](photos/part-a_terraform-plan.png)
The picture above shows that I executed the following commands: `terraform init` and `terraform plan` for the first time.

![Screenshot of terraform apply](photos/part-a_terraform-apply.png)
The picture above shows that `terraform apply` after the above commands, is success.

![Screenshot of terraform apply again](photos/part-a_terraform-apply-again.png)
The picture above shows that `terraform apply` command is executed again and the result is to let user know there is a message: "No changes. Your infrastructure matches the configuration."

![Screenshot of terraform update plan apply](photos/part-a_terraform-plan-update-apply-1.png)
The picture above shows that the main.tf is edited by adding this: `tags = { Purpose = "first-taste" }`. And the `terraform apply` is executed once again to show what changes by showing "~" and "+".

![Screenshot of terraform update plan apply](photos/part-a_terraform-plan-update-apply-2.png)
The picture above shows that the main.tf is edited again by changing both `hash_key` and `attribute` values from "id" to "name". By seeing the picture, there are signs of "~", "-", "-/+", and "+".

![Screenshot of terraform destroy](photos/part-a_terraform-destroy.png)
The picture above shows the command `terraform destroy` is being executed.

Question: Explain why the `-/+` plan was the one to be careful about.\
Answer: The symbol of `-/+` plan tells two meanings. The `-` sign is to remove or destroy a part of a file. The `+` sign is to recreate the plan after receiving new updates on file(s).

# Part E: Deploy
![Screenshot of terraform commands to run](photos/part-e-1_terraform-init-fmt-validate.png)
The picture above shows the following commands to run: `terraform init`, `terraform fmt`, and `terraform validate`. Those commands show no errors which is good news.

![Screenshot of terraform plan](photos/part-e-1_terraform-plan.png)
The picture above shows the following command: `terraform plan -out tfplan` to create a tfplan as a save file to not lose any created configurations or infrastructure. It means any changes to .tf files will not affect the tfplan until the `terraform plan -out tfplan` command is executed to recreate the tfplan file.

![Screenshot of terraform apply tfplan part 1](photos/part-e-2_terraform-apply-tfplan-1.png)
![Screenshot of terraform apply tfplan part 2](photos/part-e-2_terraform-apply-tfplan-2.png)
The pictures above show that the command `terraform apply tfplan` is being executed without any errors to catch which is success to deploy.

![Screenshot of check health states on both roles](photos/part-e-4_ensure-both-healthy.png)
The picture above shows that AWS needed my Gemini API Key before able to check if weather and advisor prints their health states. *Note: it is easy to overlook what you're typing such as "itmo-544-lab-07" instead "itmo-544-lab07".*

![Screenshot of curl weather-advisor to get a statement from gemini](photos/part-e-4_curl-weather-advisor.png)
![Screenshot of advisor website displays with input zipcode to display a statement](photos/part-e-4_advisor-website.png)\
The pictures above show that both `curl` and website are showing what inputs ask properly without having fallback or errors.

![Screenshot of test app_smoke_test.py with 9 passes](photos/part-e_app-smoke-test-py.png)
The picture above shows that the `app_smoke_test.py` is being executed to show how many passes in one test.

# Part F: Experiments
## Step 1: Count the effort
![Screenshot of print how many lines in scripts](photos/part-f_step-1.png)
The picture above shows comparisons between bash/python scripts and terraform files.

|  | lab06 python | lab07 Terraform |
| ------------- | ------------- | ------------- |
| Lines to create the stack | 333 | 430 |
| Lines to delete the stack | 69 | 0 |
| Steps you had to order by hand | 7 | 0 |
| Helper functions you wrote | 6 | 0 |
| Retry or wait loops you write | 3 | 0 |

<details>
    <summary>Click to expand for line counters</summary>
    The python files below are counted without the comment and blank lines. 

    balancer - 78
    client - 24
    compute - 103
    config - 117
    database - 114
    network - 60
    outputs - 27
    policies - 32
    runner - 103
    scaling - 40
    storage - 43
    util - 24
    create db - 37
    create stack - 24
    delete db - 50
    delete stack - 19
</details>

Question: Write two sentences on where the effort went down anyway.\
Answer: Having fewer lines of code isn't the goal, but how structural they are designed to help developers to code lines to declare infrastructure variables using declarative blocks instead of writing complex structural logic. Terraform provides helpers such as `terraform destroy` or `terraform validate` to reduce amount of if-statements while writing in a file/script.

## Step 2: Prove the order Terraform worked out
![Screenshot of terraform state list & graph](photos/part-f_step-2.png)
The picture above shows the list of current running, and the list of load balancer and launch templates.

Question: Write one sentence on what would happen if you removed the *WEATHER_URL* line from *compute.tf*: would the order change, and would the advisor still work?\
Answer: By looking at the picture, `"aws_launch_template.tier" -> "aws_lb.main";`, if the *WEATHER_URL* is removed from the *compute.tf*, the order would change and the advisor would not work in a bit of time later due to the advisor not knowing where to send weather requests.

## Step 3: Run apply again
![Screenshot of terraform plan](photos/part-f_step-3.png)
The picture above shows the command, `terraform plan` is executed to show no changes since I didn't use `terraform plan -out tfplan` to save the current plan file.

Question: Write one sentence comparing this with running `create_weather_stack.sh` twice in lab06. (Hint: the bash script printed "already exists, skipping" lines. What did it check, and what did it not check?)\
Answer: The bash script only checked resources' names existed then skipped along with if health state or parameters are correct or not.

## Step 4: Change one setting and watch a rolling replacement
![Screenshot of added a line in tfvars and plan](photos/part-f_step-4-part-1.png)
![Screenshot of terraform apply with the change](photos/part-f_step-4-part-2.png)
![Screenshot of cat environment in weather app](photos/part-f_step-4-part-3.png)
The pictures above show there is a change after adding the variable ("cache_seconds = 60") in the `terraform.tfvars` file. Then the change is being applied to current state list (this only changed 2 changes, not the entire list). `Environment="CACHE_SECONDS=60"` can be seen via SSH on the weather instance. 

Question: Write down how many commands this took, and how many it took in lab06 (edit .env, run the create script, find the instance, terminate it).\
Answer: For Terraform, it took 5 total terminal commands to execute the deployment and explicitly verify the status of the rolling update (including planning, applying, monitoring the instance refresh progress, and running an SSH check). The Python lifecycle in Lab 06 required 3 actual terminal commands to run the script, query the AWS CLI for the active instance ID, and manually terminate it.

## Step 5: Cause drift and watch Terraform notice
![Screenshot of read "HealthCheckPath"](photos/part-f_step-5-part-1.png)
![Screenshot of terraform plan update](photos/part-f_step-5-part-2.png)
The pictures above show the *weather-tg* is modified with a cause drift by changing **"HealthCheckPath"** before the `terraform plan` is being executed.

![Screenshot of notice the health state is unhealthy after the `terraform plan`](photos/part-f_step-5-part-3.png)
The picture above shows that the health is changed after the terraform plan updated.

![Screenshot of terraform apply](photos/part-f_step-5-part-4.png)
The picture above shows the `terraform apply` is executed and displayed ***1 changed***. 

![Screenshot of delete the entire advisor page](photos/part-f_step-5-part-5.png)
The picture above shows that the advisor page is gone and it did not respond to any incoming requests before doing `terraform apply -auto-approve`.

![Screenshot of terraform apply -auto-approve](photos/part-f_step-5-part-6.png)
The picture above shows the `terraform apply -auto-approve` is being executed to deploy the new advisor page. I also did check the `curl` to see if the advisor page responded.

Question: Write down the difference from lab06's `ensure_target_group`, which found the group already existing and said "skipping" **without checking that the health check was still right**.\
Answer: Terraform has its own drift detection which is a bonus. It evaluates live configurations against code state which is `terraform.tfstate` tracking file. 

## Step 6: Who can do what? (least priviege, proved)
![Screenshot of role with least privilege](photos/part-f_step-6.png)
The picture above shows which role have "allowed" or "implicitDeny".

Question: Write one sentence on what an attacker who takes over the **advisor** tier gets, and what they do not get.\
Answer: An attacker only gains permission to read the Gemini API key and the attacker do not get access to read or write or modify any data in the weather database.

## Step 7: The key never touched Terraform
![Screenshot of check the key in terraform part1](photos/part-f_step-7-part-1.png)
![Screenshot of check the key in terraform part2](photos/part-f_step-7-part-2.png)
The pictures above show that I likely missed `--type SecureString` but I went to fix it before checking again. After fixing the missing type, it now `terraform.tfstate` doesn't have the key which is a success.

Question: Remove `ignore_changes` in your head: write two sentences on what the next `terraform apply` would do to your key, and what would then be in the state.\
Answer: If `ignore_changes` was removed, the `terraform apply` would overwrite the live Gemini API key and replace it with the default placeholder string `"not-set-yet"`. Additionally, if a real key was passed through variables block without this protective rule, the secret key would be saved and leaked in plain text inside the `terraform.tfstate` tracking file.

## Step 8: Break the key and watch the fallback
![Screenshot of break gemini api key](photos/part-f_step-8.png)
The picture above shows I changed the value for API key to break on purpose. The advisor detected there is no API key to call so it went to fallback to print same sentence. Via SSH to the advisor instance, it tells you there is an error for gemini api key.

Question: Write down one problem with a design where users never see an error and the only evidence is a log line that nobody reads.\
Answer: A silent fallback that is easily overlooked that nobody reads in the log file. A silent fallback can be caused by expired API key(s), or misconfiguration issue(s).

## Step 9: The Lambda exercise (no resources, written answer)
Question 1: List every resource in `compute.tf`, `iam.tf`, `network.tf`, `alb.tf` that exists **only because the advisor runs on an EC2 instance**.\
Answer: `aws_launch_template.tier`, `user-data.sh-tftpl`, `aws_autoscaling_group.tier`, `aws_iam_instance_profile.tier`, `aws_vpc_security_group_ingress_rule`.

Question 2: List what would **stay** (the parameter, the policy, the listener, the load balancer, and so on).\
Answer: `aws_ssm_parameter.gemini`, `aws_iam_role.tier`, `aws_iam_role_policy.advisor`, `aws_lb.main`, `aws_lb_listener.tier`, `aws_lb_target_group.tier`.

Question 3: List what would be **new** (a function resource, a permission that lets the load balancer call it, and the work of changing the code to handle a Lambda event).\
Answer: `aws_lambda_function.advisor`, `aws_lambda_permission.allow_alb`, modify app.js to parse raw incoming JSON event objects.

Question 4: For each of your three lists, say whether Terraform or Lambda removed the effort. What did you gain, and what new problem did you take on (think: cold starts, time limits, how you would test it)?\
Answer:
- **Who removed the effort**: Lambda removed the effort of managing OS, systemd services, and infrastructure scaling thresholds. Terraform lets an user use simple blocks to upload the code function (`aws_lambda_function`) then give the load balancer permission to trigger it (`aws_lambda_permission`).
- **What gains**: No pay for idle time. AWS provides security because there is no OS/active server/open ports for hackers/attackers to break into. AWS handles scaling automatically.
- **What new problem**: Cold starts, if an app haven't been used in a time period, then first user would experience a short delay because AWS needs to wake up the new environment for the code. Time limits, AWS Lambda has a strict 15-minute time limit so if a backend query or an external API takes too long, a function will get cut off automatically. Permission errors such as SSH access because no physical server box for troubleshooting or check files.

| Advisor | Advisor on Lambda | Effort moved to |
| ------------- | ------------- | ------------- |
| Launch template and user-data | None | Lambda, the user provides only the application code function for Lambda to execute implicitly. |
| Auto Scaling Group and instance refresh | None | Lambda, Automatic - Lambda creates and destroys execution environments in response to traffic, scaling to zero when idle. |
| App security group rule for port 3000 | None | Lambda, AWS implements a native IAM function invocation permission boundary instead of open TCP ports. |
| Instance profile and role | Simplified | Terraform, Declare a basic IAM execution role block to manage your active deployment permissions slip. |
| Node.js install and systemd service | None | Lambda, AWS provides a pre-configured native runtime environment, removing manual installation and service management overhead. |
| Health check and grace period | None | Lambda, AWS manages health validations automatically at the native function invocation layer. |

## Step 10: Destroy, and prove nothing is left
![Screenshot of terraform destroy part 1](photos/part-f_step-10-part-1.png)
![Screenshot of terraform destroy part 2](photos/part-f_step-10-part-2.png)
![Screenshot of terraform destroy part 3](photos/part-f_step-10-part-3.png)
The pictures above show that the command `terraform destroy` is being executed to remove everything that was deployed.

![Screenshot of ensure everything is cleaned](photos/part-f_step-10-part-4.png)
The picture above shows that I had to delete likely older files behind. After deleting last 2 files, everything is cleaned and nothing is left behind to charge AWS credits.

Question: Work out how many hours the stack ran, and multiply by the hourly cost in Section 4.1. That is your estimate for the lab.\
Answer:
- Time started: Thu Nov 5 21:03:00 UTC 2026
- Time ended: Thu Nov 5 22:59:14 UTC 2026
- Time duration: 1 hour, 56 minutes, 14 seconds; or 1.9372 hours
- Total Spend = 1.9372 hours X $0.07 hourly = $0.135604

# 13. Review Questions and Troubleshooting
## 13.1 Review Questions
1. Question: Give one thing the imperative bash version could do that is hard in Terraform, and one thing Terraform did that the bash version never did.
  - Answer: One thing the imperative bash version could do: the bash script could easily pause execution to perform a one-off, conditional runtime check (like typing `read -rs -p` to get user input on the fly) mid-script.
  - One thing Terraform did that the bash version never did: Terraform tracked actual state changes and automatically handled the safe deletion of the environment on destroy without needing a single manually coded cleanup step.
2. Question: What would happen if you lost it? What would happen if two people applied from different copies? How do teams solve this?
  - Answer: Terraform would lose its track of what it built. It means that doing `terraform apply` would build new everything causing duplicate name errors.
  - If two people applied from different copies, this would cause an overwrite on each other changes to cause a deployment become corrupted.
  - Teams solve this by storing the state file in a single shared remote location (such as Amazon S3 Bucket) equipped with state locking (like a DynamoDB table) so only one person can apply changes at a time.
3. Question: Where else could a secret reach the state or a plan file? Why is a plan file also sensitive?
  - Answer: A secret becomes leaked if the secret goes as a plain text string inside a regular environment variable, a default block inside variables.tf, or directly inside un-ignored resource attributes.
  - A plan file is also sensitive because it captures exact changes and metadata parameters of your cloud account in plain text, making it a blueprint map for attackers if leaked.
4. Question: What does reading a plan protect you from? Which plan symbol worries you most, and why?
  - Answer: Reading a plan protects you from accidental data deletion, wrong resource sizing costs, and unexpected dependency modifications before committing any actual changes to AWS. 
  - The "-/+" plan symbol worries most because it means Terraform is going to permanently delete an existing resource and its underlying data to change a setting that AWS does not allow to be updated in place.
5. Question: What could go wrong with no version pin, why do we commit `.terraform.lock.hcl`?
  - Answer: Without a version pin, a routine initialization could download a newer major version of the AWS provider that changes how resources are written in files.
  - We commit the lock file to guarantee that every developer or pipeline runner on the team uses the exact same provider dependency versions, preventing hidden configuration errors.
6. Question: Why does `for_each` handle removing one tier better than `count` would?
  - Answer: The `for_each` identifies resources by their unique string keys (such as weather or advisor), so removing one entry only touches that specific tier.
7. Question: What goes wrong when a tool and a person both edit the same resource?
  - Answer: The tool will see the human's manual edits as unexpected "drift" and will try to automatically overwrite or erase those changes on the very next plan execution to match the code repository.
8. Question: How could a team find drift automatically and regularly? Who should be allowed to change things by hand?
  - Answer: A team can set up an automated CI/CD pipeline (like GitHub Actions) to run a scheduled cron job that executes `terraform plan -detailed-exitcode` and alerts the team if any differences are caught. Reference: https://developer.hashicorp.com/terraform/cli/commands/plan
  - In a production environment, nobody should be allowed to change things by hand; all changes must pass through code previews and deployment pipelines to keep reality matching the codebase.
9. Question: What decides how much one change touches, and how could you shrink it further?
  - Answer: The blast radius is decided by the structural references and arrows inside the dependency graph; any resources that references a changing block must update as well.
  - You can shrink it by splitting your large architecture infrastructure into separate, independent sub-folders with their own completely isolated state files.
10. Question: Why is a reference safer than a typed-in ARN?
  - Answer: A reference lets Terraform dynamically discover the actual resource path directly from AWS at runtime, removing the risk of fatal typos or copy-paste errors that create security holes or access denials.
11. Question: In your own words: What does Terraform have in common with Lambda, and what is the one difference that matters most for how you would use each?
  - Answer: Terraform and Lambda share the core concept of abstraction: supply a small, self-contained declaration piece of work, and let the platform automate the repetitive machinery around it.
  - One difference between Terraform and Lambda: Lambda is a runtime application service that executes code dynamically while Terraform is a pre-deployment engine tool that runs once to set up infrastructure and then completely exits.
12. Question: Which resources would you protect from a careless `destroy` in a real environment, and how (look up `prevent_destroy`)?
  - Answer: I would protect DynamoDB or RDS instances, and storage drives containing company or customer information. 
  - To prevent destroy by adding `lifecycle { prevent_destroy = true }` parameter inside a specific resource.
  - Reference: https://developer.hashicorp.com/terraform/tutorials/state/resource-lifecycle
13. Question: What did Terraform not make easier?
  - Answer: While Terraform automates creation order, cleanup, and drift detection, you must master a completely new syntax (HCL) and workflow. Additionally, it introduces the heavy operational burden of protecting a state file (`terraform.tfstate`) that contains plain-text secrets, and it still requires you to use traditional imperative CLI commands for one-time actions like injecting the real Gemini API key into Parameter Store.

## 13.2 Troubleshooting
URL: Go to this [page for troubleshooting](troubleshooting/README.md) to see a list of troubleshoots I've been through.
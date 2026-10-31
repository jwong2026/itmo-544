# Troubleshooting and Solutions
![hadn't installed pip requirements](missing-pip-installation-requirements-txt.png)
![installed pip requirements](pip-requirements-installed.png)
The pictures above show missing requirements via pip so I had to install in the lab 06.

![ssm parameter store denied](part-c3_ssm-parameter-store-denied.png)
The picture above shows that IAM role got denied to do a `ssm:PutParameter` action. Solution is to add this specific permission to the IAM Role.

![rds denied create DBSubnetGroup](part-e_rds-denied.png)
The picture above shows that IAM role got denied to do a `rds:CreateDBSubnetGroup` action. Solution is to add this specific permission to the IAM Role.

![missing 'sts' in clients.py](part-f_execute-create-weather-stack-py-fail-1.png)
The picture above shows that my clients.py forgot to include `sts: Object` and `sts=session.client("sts")`.

![typo detected](part-f_execute-create-weather-stack-py-fail-2.png)
The picture above shows I made a typo in create_weather_stack.py. I fixed that typo from *advisir* to *advisor*.

![Detected 'uploader'](part-f_execute-create-weather-stack-py-fail-3.png)
![solution for 'uploader' role](stack-compute-py-wrong-role.png)
The pictures above show that I didn't change the role or overlooked the role. I changed from *uploader* to *weather*.

![linux detected spacings and tabs](advisor-app-js-detected-tabs-spacings.png)
The picture above shows that python detected tabs and spacings misaligned IN the advisor instance via SSH. 

![Gemini API Key is not connected.](advisor-website-gemini-failed.png)
![Solution for gemini API key not connected](advisor-website-grep-troubleshoot-port.png)
The pictures above show that the port is wrong. This got discovered in the advisor instance via SSH to `grep` the *WEATHER_URL* to see if the port is right or wrong.

![app_smoke_test.py showing blank results](app-smoke-test-py-fail-printed-blank.png)
The picture above shows that the python printing blank results. I had to troubleshoot through the python file and discovered misaligned tabs or spacings.

![no create_weather_stack.py](pytest-m-chaos-no-weather-stack.png)
The picture above shows obvious answer that I needed to execute the *create_weather_stack.py*.

![without try-except statement](test-infrastructure-added-try-except-dbinstanceautomatedbackupnotfound.png)
![with try-except statement](test-infrastructure-added-try-except.png)
The pictures above show that I didn't include try-except statement for `DBInstanceAutomatedBackupNotFound`. 

![tried with 30second timeout](pytest-integration-timeout-error-30000.png)
![tried with 15second timeout](pytest-integration-timeout-error-15000.png)
The pictures above show that timeout failed while running `pytest -m integration -v`. I decided to wait for a bit before I ran again starting from: `test_smoke.py` -> `pytest -v` -> `pytest -m integration -v` -> `pytest -m chaos -v` -> `pytest -v -m "not integration and not chaos"`. After executing those pytests and test_smoke.py, the results are showing all passes without a single failure.
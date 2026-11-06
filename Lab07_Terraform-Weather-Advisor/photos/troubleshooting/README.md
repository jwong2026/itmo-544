# Troubleshooting and Solutions
![Screenshot of made a typo in filename](user-data.sh.tftpl_TYPO.png)
The picture above shows that I made a typo while naming the file, `user-data.sh.tfpl` --> `user-data.sh.tftpl`.

![Screenshot of denied permission - AddTagsToResource](ssm-AddTagsToResource.png)
The picture above shows that the IAM user is denied to do this permission: `ssm:AddTagsToResource`.

![Screenshot of denied permission - ListTagsForResource](ssm-ListTagsForResource.png)
The picture above shows that the IAM user is denied to do this permission: `ssm:ListTagsForResource`.

![Screenshot of terraform fmt detected errors](terraform-fmt-detected-errors.png)
The picture above shows the `terraform fmt` discovered a list of errors being displayed in the picture. I noticed I was missing a double-quote in the first error. So I fixed it and all of errors in the picture went clear.

![Screenshot of terraform validate missing init ](terraform-validate-missing-init.png)
The picture above shows the error is telling me it is missing the required provider which is `terraform init` so I went to execute the command, `terraform init`.
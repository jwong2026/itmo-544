Jimmy Wong\
September 27, 2026\
ITMO-544\
Lab 03 - EC2, S3 Two-Tier File Upload Display

# Part C -- The Two Node.js Apps (Written Locally)
![Screenshot of Uploader & Viewer folders](photos/part-c_uploader-viewer-folders.png)

## Part C -- C2. Viewer App Logic
Question: Explain in one sentence: why the viewer's IAM role does not need "s3:PutObject".
Answer: ?

# Part G -- End-to-End Test
Screenshots of whatever
![Screenshot of Run create-app-stack.sh](photos/part-g_run-create-app-stack-sh.png) 1
![Screenshot of Display websites of Uploader and Viewer](photos/part-g_uploader-viewer-websites-successful.png) 2
![Screenshot of Upload .txt file Part 1](photos/part-g_upload-txtfile-part-1.png) 3
![Screenshot of Upload .txt file Part 2](photos/part-g_upload-txtfile-part-2.png) 4
![Screenshot of Viewer displayed .txt file successfully](photos/part-g_viewer-display-txtfile-successful.png) 5
![Screenshot of Uploader tried a .txt file that is greater than 1MB Part 1](photos/part-g_upload-gt-1mb-txtfile-part-1.png) 6
![Screenshot of Uploader tried a .txt file that is greater than 1MB Part 2](photos/part-g_upload-gt-1mb-txtfile-part-2.png) 7
![Screenshot of Uploader tried a .txt file that is greater than 1MB Part 3](photos/part-g_upload-gt-1mb-txtfile-part-3.png) 8
![Screenshot of Uploader tried a non .txt file Part 1](photos/part-g_upload-non-txtfile-part-1.png) 9 
![Screenshot of Uploader tried a non .txt file Part 2](photos/part-g_upload-non-txtfile-part-2.png) 10
![Screenshot of Uploader's app.js file 'h1' tag is edited](photos/part-g_app-js-edit-h1.png) 11
![Screenshot of ?](photos/part-g_rerun-create-app-stack-sh-after-app-js-edited-part-1.png) 12
![Screenshot of ?](photos/part-g_rerun-create-app-stack-sh-after-app-js-edited-part-2.png) 13
![Screenshot of ?](photos/part-g_run-delete-app-stack-sh.png) 14
![Screenshot of ?](photos/aws-ec2-describe-launch-templates.png) 15
![Screenshot of ?](photos/aws-ec2-describe-launch-template-versions-v1.png) 16
![Screenshot of ?](photos/aws-ec2-describe-launch-template-versions-v2.png) 17
![Screenshot of ?](photos/aws-ec2-describe-launch-template-versions-v3.png) 18
![Screenshot of ?](photos/aws-iam-get-role-policy-uploader-viewer.png) 19

# Q&A
Question: One paragraph explaining why the uploader and viewer use **separate** IAM roles instead of one shared role with both permissions.
Answer: ?

Question: One or two sentences explaining why embedding code directly into user-data means the instance never needs a Git or S3 credential just to fetch its own coe.
Answer: ?

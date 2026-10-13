Jimmy Wong\
October 2, 2026\
ITMO-544\
Lab 03 - EC2, S3 Two-Tier File Upload Display

# Part C -- The Two Node.js Apps (Written Locally)
![Screenshot of Uploader & Viewer folders](photos/part-c_uploader-viewer-folders.png) 
1 - This picture above shows folder hierarchy which is best way to read easily and human readable. 

## Part C -- C2. Viewer App Logic
**Question: Explain in one sentence: why the viewer's IAM role does not need "s3:PutObject".**\
**Answer:** The viewer's IAM role does not need "s3:PutObject" is because the viewer's purpose only needs to display a result of an uploaded file coming from the uploader's server and the viewer does not need to add any objects to the s3 bucket.\
Reference: https://docs.aws.amazon.com/cli/latest/reference/s3api/put-object.html

# Part G -- End-to-End Test
![Screenshot of Run create-app-stack.sh](photos/part-g_run-create-app-stack-sh.png) 
2 - This picture above shows the screenshot of ***create_app_stack.sh*** output showing both instances running with public IP addresses.

![Screenshot of Display websites of Uploader and Viewer](photos/part-g_uploader-viewer-websites-successful.png) 
3 - This picture above shows the screenshot of the Uploader & Viewer pages being shown properly and successful. 

![Screenshot of Upload .txt file Part 1](photos/part-g_upload-txtfile-part-1.png) 
4 - This picture above shows the screenshot of the Uploader page have uploaded a txt file within 1MB file size. FYI, the txt file has a line of full generated random data to get a worth of about 1MB. 

![Screenshot of Upload .txt file Part 2](photos/part-g_upload-txtfile-part-2.png) 
5 - This picture above shows the screenshot of the Uploader page have uploaded a txt file within 1MB file size and it was a success. 

![Screenshot of Viewer displayed .txt file successfully](photos/part-g_viewer-display-txtfile-successful.png) 
6 - This picture above shows the screenshot of the Viewer page have refreshed its page and successfully displayed the txt file is uploaded by the Uploader. 

![Screenshot of Uploader tried a .txt file that is greater than 1MB Part 1](photos/part-g_upload-gt-1mb-txtfile-part-1.png) 
7 - This picture above shows the screenshot of the Uploader page have uploaded a txt file with greater than 1MB file size. 

![Screenshot of Uploader tried a .txt file that is greater than 1MB Part 2](photos/part-g_upload-gt-1mb-txtfile-part-2.png) 
8 - This picture above shows the screenshot of the Uploader page detected the file has a greater than 1MB file size which caused an error and to display the error. 

![Screenshot of Uploader tried a .txt file that is greater than 1MB Part 3](photos/part-g_upload-gt-1mb-txtfile-part-3.png) 
9 - This picture above shows the screenshot of the Viewer page remained same content from the previous txt file uploaded. 

![Screenshot of Viewer displays two different txt files](photos/part-g_upload-second-txtfile-part-1.png) 
10 - This picture above shows the screenshot of the second txt file being uploaded by Uploader. 

![Screenshot of Viewer displays two different txt files](photos/part-g_upload-second-txtfile-part-2.png) 
11 - This picture above shows the screenshot of the second txt file being uploaded successfully. 

![Screenshot of Viewer displays two different txt files](photos/part-g_upload-second-txtfile-part-3.png) 
12 - This picture above shows the screenshot of the second txt file can be seen on the Viewer website after clicking the *Refresh* button. 

![Screenshot of Uploader tried a non .txt file Part 1](photos/part-g_upload-non-txtfile-part-1.png) 
13 - This picture above shows the screenshot of the Uploader page have uploaded a non txt file.

![Screenshot of Uploader tried a non .txt file Part 2](photos/part-g_upload-non-txtfile-part-2.png) 
14 - This picture above shows the screenshot of the Uploader page detected the file is not .txt extension, therefore the Uploader page informed that the error is the file extension is not met. 

![Screenshot of Uploader's app.js file 'h1' tag is edited](photos/part-g_app-js-edit-h1.png) 
15 - This picture above shows the screenshot of the Uploader's app.js file has been edited and the edited part is focused on *h1* for a simple display and comparison. *The edited part can be seen via highlight yellow colored.*

![Screenshot of ?](photos/part-g_rerun-create-app-stack-sh-after-app-js-edited-part-1.png) 
16 - This picture above shows the screenshot of the Uploader's create_app_stack.sh being executed without an error to throw. 

![Screenshot of ?](photos/part-g_rerun-create-app-stack-sh-after-app-js-edited-part-2.png) 
17 - This picture above shows the screenshot of the Uploader's app.js being updated and displayed on the website properly. 

![Screenshot of ?](photos/part-g_run-delete-app-stack-sh.png) 
18 - This picture above shows the screenshot of the ***delete_app_stack.sh*** showing a success output. 

![Screenshot of ?](photos/aws-ec2-describe-launch-templates.png) 
19 - This picture above shows the command line to display what launch templates are available. 

![Screenshot of ?](photos/aws-ec2-describe-launch-template-versions-v1.png) 
20 - This picture above shows the command line to display that the launch template has their own versions which can be seen in the screenshot. This picture is shown for version 1.

![Screenshot of ?](photos/aws-ec2-describe-launch-template-versions-v2.png) 
21 - This picture above shows the command line to display that the launch template has their own versions which can be seen in the screenshot. This picture is shown for version 2.

![Screenshot of ?](photos/aws-ec2-describe-launch-template-versions-v3.png) 
22 - This picture above shows the command line to display that the launch template has their own versions which can be seen in the screenshot. This picture is shown for version 3.

![Screenshot of ?](photos/aws-iam-get-role-policy-uploader-viewer.png) 
23 - This picture above shows the screenshot of the command line to display both roles, showing each has only it's one intended action on the exact *shared.txt* key. 

# Q&A
**Question: One paragraph explaining why the uploader and viewer use **separate** IAM roles instead of one shared role with both permissions.**\
**Answer:** Both of the Uploader and Viewer should have their own IAM roles for security, safety, and practical. Each role gets one purpose for their own intentions to do and do not cross a different role's intention. To be logical, things need to be simple and secured to prevent attackers to break in and discover limited abilities to do. 

**Question: One or two sentences explaining why embedding code directly into user-data means the instance never needs a Git or S3 credential just to fetch its own code.**\
**Answer:** A launch template's user-data can hold the entire boot script including app code(s) is because when you create a launch template with app code(s), the codes from *app.js* and *package.json* locally, will be buried or embedded into the launch template, so the launch template will have everything it needs to start at boot startup without calling a Git or S3 credentials. 

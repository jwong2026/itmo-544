Jimmy Wong\
October 13, 2026\
ITMO-544\
Lab 04 - Multi-AZ Resilience: ALB, Auto Scaling, Groups, and Recovery-Time SLOs

# Part B -- ALB Security Group and Tightening the App Security Group
Question: You can explain, in one sentence, why *--source-group* is a tighter rule than *--cidr 0.0.0.0/0*, even though both currently let traffic on port 3000 through.\
Answer: ?

# Part C -- Target Groups, Load Balancer, and Listeners
Question: You can explain, in one sentence, the difference between a target group and a listener.\
Answer: ?

# Part D -- Auto Scaling Groups: The Recovery Mechanism
Question: You can explain, in one sentence, why *--health-check-type ELB* matters more here than it would for a single standalone instance.\
Answer: ?

# Part G -- Run the Experiment
![Screenshot of the create_app_stack.sh being executed](photos/part-g_create-app-stack-sh-part-1.png)
The picture above shows the create_app_stack.sh is being executed. In this picture, first lines are from the previous lab, lab 03.

![Screenshot of the create_app_stack.sh being executed](photos/part-g_create-app-stack-sh-part-2.png)
The picture above shows the create_app_stack.sh is being executed. In this picture, new lines from the lab 04 instruction to focus on application load balance and auto scaling group. 

![Screenshot of the http servers for uploader and viewer](photos/part-g_http-uploader-viewer-part-1.png)
The picture above shows the uploader and viewer pages are showing success properly along with the DNS. 

![Screenshot of a txt file being uploaded on the uploader](photos/part-g_http-uploader-viewer-part-2.png)
The picture above shows the txt file is being attached/uploaded to the uploader web.

![Screenshot of the txt file uploaded successfully on the uploader](photos/part-g_http-uploader-viewer-part-3.png)
The picture above shows the txt file is uploaded successfully. 

![Screenshot of the viewer web successfully displayed the txt file](photos/part-g_http-uploader-viewer-part-4.png)
The picture above shows the viewer is able to read the txt file that is uploaded from the uploader web.

![Screenshot of chaos_test.py being executed to display an output which is "PASS"](photos/part-g_chaos-test-py-uploader-PASS.png)
The picture above shows the chaos-test.py for uploader is executed and made an output in .csv file.\
URL to .csv file: [Chaos Test Uploader PASS in CSV file](chaos_test_uploader_2463.csv)

![Screenshot of chaos_test.py being executed to display an output which is "PASS"](photos/part-g_chaos-test-py-viewer-PASS.png)
The picture above shows the chaos-test.py for viewer is executed and made an output in .csv file.\
URL to .csv file: [Chaos Test Viewer PASS in CSV file](chaos_test_viewer_2644.csv)

![Screenshot of chaos_test.py being executed with shorter time on recovery SLO, to display an output which is "FAIL"](photos/part-g_chaos-test-py-uploader-FAIL.png)
The picture above shows the chaos-test.py for uploader is executed and made an output in .csv file.\ 
One thing is changed in this picture is to change the "*RECOVERY_SLO_SECONDS*" from 180 seconds to 60 seconds to tighten the timer.\
URL to .csv file: [Chaos Test Uploader PASS in CSV file](chaos_test_uploader_2840.csv)

![Screenshot of the delete_app_stack.sh being executed](photos/part-g_delete-app-stack.png)
The picture above shows the delete_app_stack.sh is being executed properly before any of those services start charging credits. 

# Q & A
Question: One paragraph explaining, using your own recovery-time numbers, what dominates the recovery window (health-check timing vs. boot/npm install time vs. something else).\
Answer: ??

Question: One paragraph explaining what changed in create_app_stack.sh/delete_app_stack.sh between the previous lab and this one — specifically, what replaced the old run-instances call and why.\
Answer: ??

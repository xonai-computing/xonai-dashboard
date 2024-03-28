# Dashboard Installation and Cluster Bootstrapping for EMR
The [prerequisites](./prerequ-emr.md) chapter covers the configuration of the instance that hosts the Xonai Dashboard. After all steps have been completed,
we can [SSH](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-to-linux-instance.html) into this UI server and execute the installation script.

## UI Installation
A few optional environment variables that influence the installation process and enable specific Grafana functionalities can be declared, they are described in the [addendum](./misc.md/#additional-installation-settings).
We recommend the definition of the `AWS_REGIONS` [variable](./misc.md/#limiting-aws-regions) that encodes the AWS region(s) where clusters will be launched. If unset, the script accesses cost data for 
all AWS regions which prolongs its completion.

The script [install-ui-emr.sh](../scripts/install-ui-emr.sh) can now be downloaded and executed, it manages all installation and configuration steps:
``` bash
[ec2-user@ip-123 ~]$ wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/scripts/install-ui-emr.sh # Download script
[ec2-user@ip-123 ~]$ bash install-ui-emr.sh
```

The final message "Installation of Xonai Dashboard completed" indicates that our Grafana dashboards can be accessed as described in the [usage](./usage.md) document, several post installation checks are
mentioned in the testing [chapter](./checks.md). Cluster metadata and cost estimations should already be displayed in the cluster list boards but no node-level or Spark metrics are available yet. This will 
change after bootstrapping an EMR cluster with our script which is the topic of the next section.

## Monitoring EMR clusters
The cluster bootstrap scripts automate the configuration of Spark's internal metric system as well as the installation of collector daemons that periodically transmit or publish telemetry data. The 
script choice depends on which ingestion mode was activated during the UI installation, [bootstrap-emr-push.sh](../scripts/bootstrap-emr-push.sh) is the relevant file for the default mode which was
used in the installation section above. The bootstrap script should be copied into an S3 bucket that tracked clusters are able to access. [This](https://docs.aws.amazon.com/emr/latest/ManagementGuide/emr-plan-bootstrap.html)
AWS guide explores cluster bootstrapping in more detail.

### Bootstrap Action for Default Push Mode
The [bootstrap-emr-push.sh](../scripts/bootstrap-emr-push.sh) script needs to be referenced in a bootstrap action: When creating a cluster, paste its S3
URI into the "Script location" field of the "Add bootstrap action" window. Specify the value of `$UI_IP4_DNS` (i.e., the IPv4 DNS of the Grafana instance) in the "Arguments" section. For example:

<img src="../images/BootstrapPush.png" width="528" height="114" />

The bootstrap configuration for pull ingestion is described in the [addendum](./misc.md#pull-mode-activation).

# Containerized Usage
All dashboard components can be installed locally by executing commands similar to those in the cloud setup scripts. However, it is more convenient to containerize the application as multiple
dependencies and configuration steps are involved. The only software requirements for running the commands in the next sections are [Docker](https://docs.docker.com/engine/install/) and
Docker Compose. The latter is natively available in Docker Desktop and can be manually [added](https://docs.docker.com/compose/install/) in case an unbundled Docker engine was installed.

## Building Dashboard Images
Most container images referenced in the compose files below were published by the creators of the respective components and get pulled from public Docker registries. The UI containers are spawned 
from a customized image `dashboard-grafana` that adds multiple dashboards and data sources to an official Grafana image. This custom image for tracking local apps and EMR clusters can be built 
with the [DockerfileGrafana](../docker/DockerfileGrafana) template and the following command:
```shell
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/DockerfileGrafana
docker build -t dashboard-grafana -f DockerfileGrafana .
```
If remote Databricks clusters should be tracked, an additional build argument needs to be supplied:
```shell
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/DockerfileGrafana
docker build --build-arg="ACTIVE_PLATFORM=AWS_DBX" -t dashboard-grafana -f DockerfileGrafana .
```

The Docker apps in the "Monitoring Remote Applications" section utilize an API server for retrieving cloud infrastructure and cost information. An image for this component can be created with the 
[DockerfileApp](../docker/DockerfileApp) file which adds a layer with the server
[code](https://github.com/xonai-computing/xonai-dashboard/tree/main/xonai-grafana) to an official Python image:
```shell
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/DockerfileApp
docker build -t dashboard-app -f DockerfileApp .
```
The final artefact is tagged with the name `dashboard-app`.

## Monitoring Local Applications
After building the custom Grafana image, the dashboard can be started in local mode with the service file [compose-local.yaml](../docker/compose-local.yaml)
and the following compose command:
```shell
# download compose file and config files for metric collector:
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/compose-local.yaml
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/resources/write_relabel.yaml
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/resources/scrape_config.yaml
docker compose -p dashboard-local -f compose-local.yaml up
```

Upon invocation, five containers in total are launched:
- Two containers (`victoriametrics` and `vmagent`) for database and metric ingestion processes
- A Grafana container which is backed by the custom image described [above](#building-dashboard-images)
- A container named `node_exporter` that collects hardware metrics of the Docker host
- A transient container `spark_app` in which a Spark application runs, its metrics are written to the database container

<details>
<summary>This multi-container application is visualized in the diagram below: (click me)</summary>
<img src="https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/images/ArchiLocal.svg" width="382" height="351"/>
</details>

The Grafana web interface can now be accessed by pasting `localhost:3000` into a browser's address bar. The visitor will be directly forwarded to the welcome screen as authentication was disabled during
the creation of the custom image, modifications to panels and dashboards can be made after signing in with the username and password `admin`.

Many dashboard panels are blank since local runs do not produce executor metrics or capture cloud infrastructure information. The `Cluster Overview` board visualizes the Docker host as a single-node cluster
and displays its system metrics. These are captured by the node_exporter container for which a dedicated `Node Exporter` dashboard is available, it displays the host metrics in more detail. The `Spark Info`
dashboard summarizes the application metrics that are emitted from the Spark container. The aforementioned boards should be visited a few minutes after the docker compose command was 
issued and "Last 5 minutes" should be chosen in the time range selector in the top right corner.

The Spark container will automatically terminate after its job has completed which should take a few minutes. Metrics of a non-containerized application can also be ingested if a Spark 
[runtime](https://spark.apache.org/downloads.html) is available on the machine where the Docker daemon runs and the configuration properties mentioned in the next paragraph are set.

<details>
<summary>Spark configuration properties for metric ingestion: (click me)</summary>

```
spark.metrics.conf.*.sink.graphite.class org.apache.spark.metrics.sink.GraphiteSink
spark.metrics.conf.*.sink.graphite.host localhost
spark.metrics.conf.*.sink.graphite.port 2003
spark.metrics.conf.*.source.jvm.class org.apache.spark.metrics.source.JvmSource
spark.metrics.appStatusSource.enabled true
spark.executor.processTreeMetrics.enabled true
```

Below is a sample spark-submit command with these properties:

``` shell
$SPARK_HOME/bin/spark-submit --master "local[2]" \
--class org.apache.spark.examples.SparkPi \
--conf "spark.metrics.conf.*.sink.graphite.class"="org.apache.spark.metrics.sink.GraphiteSink" \
--conf "spark.metrics.conf.*.sink.graphite.host"="localhost" \
--conf "spark.metrics.conf.*.sink.graphite.port"=2003 \
--conf "spark.metrics.conf.*.source.jvm.class"="org.apache.spark.metrics.source.JvmSource" \
--conf spark.metrics.appStatusSource.enabled=true \
--conf spark.executor.processTreeMetrics.enabled=true \
$SPARK_HOME/examples/jars/spark-examples_2.12-3.5.1.jar 50000
```

</details>

## Monitoring Remote Applications
The containerized version of the Xonai Dashboard can also be used to track distributed applications. If the Docker host resides outside the cloud network, two challenges arise: Cost and 
infrastructure information is fetched from cloud APIs and these requests that originate from the `dashboard-app` container need to be authenticated without IAM roles. Furthermore, establishing a 
connection between metric collectors running on remote cluster nodes and a local database is not as straightforward as the inter-container communication setup from the previous scenario where all services 
run on the same machine.

There are multiple solutions for both challenges: Cloud SDKs like boto3 or the Databricks SDK check various locations such as config files or
environment variables for authentication attributes. The container API calls can therefore be authenticated by dynamically [bind](https://docs.docker.com/storage/bind-mounts/)-mounting a credential
file from the Docker host into the container or by injecting relevant environment variables. <br>
Metrics generated on cluster nodes can be ingested into a network-external database via SSH tunneling: The container with the time-series database listens on port `8428` and a number of tools exist
that facilitate remote port forwarding. For example, Pinggy only requires the execution of an [SSH command](https://pinggy.io/docs/) like `ssh -p 443 -R0:localhost:8428 a.pinggy.io` for starting a 
tunnel to local port `8428`. This provides a temporary https URL that can be used as the remote endpoint for the metric collectors, their outputs will then be forwarded to `localhost:8428` until 
the remote SSH tunnel is closed.

<details>
<summary>The following diagram depicts the interplay of the various components that have been described: (click me)</summary>
<img src="https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/images/ArchiLocal2.svg" width="616" height="364"/>
</details>


### Monitoring EMR Clusters
The [compose-emr.yaml](../docker/compose-emr.yaml) file configures three dashboard containers for tracking EMR clusters and references the two custom images whose creation is specified 
[above](#building-dashboard-images). Similar to the non-dockerized version described on the EMR setup [page](setup-emr.md#ui-installation), all cost estimations rely on data fetched from cloud APIs 
prior to the start of the UI components. For this purpose, a dedicated script is used and its output gets mounted into the `dashboard-app` container. The `AWS_REGIONS` [variable](misc.md#limiting-aws-regions) 
encodes the AWS region(s) where clusters will be launched. If unset, the script accesses cost data for all AWS regions which prolongs its completion:
```shell
export AWS_REGIONS=us-east-1 # relevant region 
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/xonai-grafana/xonai_grafana/cost_estimation/fetch_cost_info.py # download helper script
mkdir -p resources/emr && mkdir resources/ec2
python3 fetch_cost_info.py $AWS_REGIONS
```

The boto3 requests of the `dashboard-app` container can be authenticated by [bind](https://docs.docker.com/storage/bind-mounts/)-mounting an existing AWS credentials file (default location `~/.aws/credentials`)
from the docker host's filesystem. If such a credentials profile has not already been created, it can be set up manually which is described [here](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#configuration).
To use this authentication strategy, the last [line](../docker/compose-emr.yaml#L31) in the compose file's 
`volumes` section needs to be uncommented and the local path before the first colon may require modification.

<details>

<summary>Alternatively, the AWS API calls can be verified by adding two environment variables AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (which are also supported
by the AWS CLI) to the environment section of compose-emr.yaml: (click me)</summary>

```
[...]
    environment:
      - AWS_REGIONS=${AWS_REGIONS}
      - ACTIVE_PLATFORM=AWS_EMR
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}      
[...]
```
</details>

The Compose configuration can now be executed:
```shell
export AWS_REGIONS=us-east-1 # initial region for cluster dashboards
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/compose-emr.yaml
# modify volumes or environment section as required
docker compose -p dashboard-emr -f compose-emr.yaml up
```

To ingest metrics from an EMR cluster, a database destination URL needs to be provided as an argument to the bootstrap script, this initialization process is described in the EMR setup 
[document](setup-emr.md#bootstrap-action-for-default-push-mode). If the Docker host is outside the cloud network, an open tunnel connection for local port `8428` may be required and the tunnel URL can be 
used as the bootstrap argument instead of the IPv4 DNS of an EC2 instance for example. A sample command for remote port forwarding has already been mentioned in the previous 
[section](#monitoring-remote-applications), the https URL that it returns can be used as the bootstrap argument.

### Monitoring Databricks Clusters
The [compose-dbx.yaml](../docker/compose-dbx.yaml) file defines three dashboard containers for tracking Databricks clusters and references the two custom images whose creation is specified [above](#building-dashboard-images).
Similar to the non-dockerized version described on the Databricks setup [page](setup-emr.md#ui-installation), the EC2 cost estimations rely on data fetched from cloud APIs prior to the start of the UI 
components. For this purpose, a dedicated script is used and its output gets mounted into the `dashboard-app` container. The `AWS_REGIONS` [variable](misc.md#limiting-aws-regions) encodes the AWS
region(s) where clusters will be launched. If unset, the script accesses cost data for all AWS regions which prolongs its completion:
```shell
export AWS_REGIONS=us-east-1 # relevant region
export ACTIVE_PLATFORM=AWS_DBX
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/xonai-grafana/xonai_grafana/cost_estimation/fetch_cost_info.py # download helper script
mkdir -p resources/ec2
python3 fetch_cost_info.py $AWS_REGIONS
```

The Databricks SDK requests of the `dashboard-app` container can be authenticated via [native authentication](https://databricks-sdk-py.readthedocs.io/en/latest/authentication.html#databricks-native-authentication) 
with a personal access token, the token creation process is described [here](https://docs.databricks.com/en/dev-tools/auth/pat.html#databricks-personal-access-tokens-for-workspace-users). Under this 
approach, two environment variables that were declared on the Docker host get dynamically injected into the `dashboard-app` container upon launch:
```shell
export DATABRICKS_HOST=... # holds the Dbx workspace instance URL
export DATABRICKS_TOKEN=... # holds the access token
```

The Compose configuration can now be executed:
```shell
export AWS_REGIONS=us-east-1 # initial region for cluster dashboards
wget https://raw.githubusercontent.com/xonai-computing/xonai-dashboard/main/docker/compose-dbx.yaml
docker compose -p dashboard-dbx -f compose-dbx.yaml up
```

To ingest metrics from a Databricks cluster, a database destination URL needs to be specified as the value for the `UI_SERVER` variable, this initialization process is described in the Databricks 
setup [document](setup-aws-dbx.md#databricks-cluster-configuration). If the Docker host is outside the cloud network, an open tunnel connection for local port `8428` may be required and the tunnel URL
can be used as the variable value instead of the IPv4 DNS of an EC2 instance for example. A sample command for remote port forwarding has already been mentioned in the previous 
[section](#monitoring-remote-applications), the https URL that it returns can be assigned to `UI_SERVER`.

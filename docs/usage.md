# Using Xonai's Dashboard
After completing the setup steps, the Grafana web interface is available on the UI instance through port `3000`. The
dashboards can be accessed by pasting one of the following URLs into a browser window:
- The public IPv4 address of the Grafana instance with port `3000`. For example, _1.23.456.789:3000_
- The public IPv4 domain name of the Grafana instance (`$UI_IP4_DNS`) with port `3000`. For example, _ec2-1-23-456-789.compute-1.amazonaws.com:3000_

If the port `3000` has been enabled as described on the prerequisites pages, the Grafana UI will appear and ask for authentication
credentials unless anonymous access was [activated](./misc.md#anonymous-access-and-embeddings) during the installation. In the login page, `admin` needs to be entered into both the "Email or username" 
and "Password" fields. The subsequent credential update page can be skipped. Navigating to our cloud dashboards from the Grafana home screen is easy: After expanding the "Open menu" icon in the upper
left corner, a "Dashboards" link appears that needs to be clicked. The cloud boards are pre-installed and listed in the "Dashboards" window.

## General Functionality
Grafana's main navigational mechanism in a dashboard is a time range window and moving to different days to view different clusters or apps can be cumbersome. Therefore, the first three boards mentioned 
in the dashboard list below are intended to serve as entry points: Users can quickly jump from them to the summary boards of individual clusters or applications. Their various time series will
automatically be in scope and the elements of drop-down lists (like cluster IDs) will be set to the correct values. Of course, all dashboards can be used in isolation.
<br> Time ranges that become too coarse-grained (e.g., "Last 90 days") can affect some plots and quantities as their underlying database queries might for example use functions that operate on
interval lengths. To avoid this, the cluster overview and Spark info dashboards have special top panels that serve as visual aides, they plot the active nodes and tasks over time.

Some dashboards like cluster overviews contain drop-down lists that act as global filters. For example, the `cluster` variable removes all time series from the panels that are not labelled with
the provided cluster ID(s). The `region` list is special, it only affects panels that display region-dependent cost estimations. Its value must be set to the region (e.g., "us-east-1") of the
cluster(s) whose metrics are currently visualized. This region variable signals the backend to switch the cost information that was configured and downloaded during the UI installation. Likewise,
the Databricks-specific `plan` variable affects DBU cost estimations as it encodes the platform tier of the workspace.

## Cloud Dashboards
The following dashboards are automatically imported during the installation:
- `Cluster List Extended`: Displays a list of clusters that were launched during the selected time region. Their core metadata, estimated costs, and max/average CPU and memory utilizations are
  displayed. For clusters that were not bootstrapped with our scripts, the CPU and memory cells are blank. Clicking on a cluster ID link opens and customizes the `Cluster Overview` dashboard for
  the respective cluster. 
- `Cluster List`: Contains similar elements as the previous dashboard except for the cost column. AWS throttles API requests which might happen when large time ranges are chosen or the
  internal cost cache hasn't been populated yet, so this dashboard is suitable for quickly listing clusters that were launched a longer time ago.
- `General Overview`: Displays summary metrics, cluster cost estimations, active resources, and a list of Spark applications with links to the `Spark Info` and `Cluster Overview` dashboards.
- `Cluster Overview`: The summary page for one or more clusters. Cross-links to the dashboards for specific nodes, Spark applications, and instance types. The panels after the "Cluster Overview"
 row plot various utilization and saturation metrics for the cluster nodes and are inspired by an AWS [board](https://aws.amazon.com/blogs/big-data/monitor-and-optimize-analytic-workloads-on-amazon-emr-with-prometheus-and-grafana/).
- `Spark Info`: Shows the [Spark metrics](https://spark.apache.org/docs/latest/monitoring.html#list-of-available-metrics-providers) for a specific Spark application.
- `Node Exporter`: Integrates the node exporter [dashboard](https://github.com/rfmoz/grafana-dashboards) for visualizing the hardware and OS metrics of a single EC2 instance. Our bootstrap script deactivates several [default](https://github.com/prometheus/node_exporter#enabled-by-default) collectors 
and ignores irrelevant mount points which significantly reduces the number of time series that are ingested. As a consequence, most panels after the "Network Traffic" row will be empty. The 
[appendix](./misc.md#activated-node-exporter-collectors) contains more detailed information and explains how this setting can be changed.
- `Instance Type Info`: Shows the machine specs and pricing for a specific instance type.
- `Test Setup`: A special test dashboard that queries a single time series for sanity checks and debugging purposes, see the test [chapter](./checks.md#ui-connection-checks).

## Changing Grafana Variables
Some Grafana dashboards define one or more variables that act as global filters or pass relevant information to the UI backend. The region of clusters or apps is important for
cost estimations and can be selected from drop-down lists that include all entries in the first column of the region [table](./misc.md#aws-regions) by default. These lists can be modified by opening
the settings window of a dashboard with the wheel icon and navigating to the "Variables" panel. A click on the "region" name opens a detail page where
all values are defined in the "Custom options" box. This list should be truncated so that it only contains the region(s) of tracked clusters.

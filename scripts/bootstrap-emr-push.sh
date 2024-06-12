#!/bin/bash
# Xonai Dashboard bootstrap script EMR push (https://github.com/xonai-computing/xonai-dashboard)

AGENT_CMD=${AGENT_CMD:-'/usr/local/bin/vmagent-prod -remoteWrite.tmpDataPath /tmp/vmagent-remotewrite-data -remoteWrite.url=METRIC_SERVER/api/v1/write -enableTCP6 -promscrape.config /tmp/scrape_config.yaml -graphiteListenAddr localhost:2003 -remoteWrite.relabelConfig /tmp/write_relabel.yaml'}
MOUNT_BLACKLIST=${MOUNT_BLACKLIST:-'--collector.filesystem.mount-points-exclude=^/(mnt/tmp|dbfs|Workspace|dev|proc|run/credentials/.+|sys|var/lib/docker/.+|var/lib/containers/storage/.+)($|/)'}
FS_BLACKLIST=${FS_BLACKLIST:-'--collector.filesystem.fs-types-exclude=^(tmpfs|autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|iso9660|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tracefs)$'}
DISABLED_COLLECTORS=${DISABLED_COLLECTORS:-'--web.disable-exporter-metrics --no-collector.arp --no-collector.bonding --no-collector.btrfs --no-collector.conntrack --no-collector.dmi --no-collector.entropy --no-collector.fibrechannel --no-collector.hwmon --no-collector.mdadm --no-collector.netstat --no-collector.os --no-collector.powersupplyclass --no-collector.pressure --no-collector.rapl --no-collector.schedstat --no-collector.selinux --no-collector.sockstat --no-collector.softnet --no-collector.stat --no-collector.tapestats --no-collector.textfile --no-collector.thermal_zone --no-collector.time --no-collector.timex --no-collector.udp_queues --no-collector.xfs --no-collector.zfs'}

echo 'Starting main bootstrap script (push EMR)'
ARCHI=$(uname -m) # x86_64 or aarch64
if [ "$ARCHI" != 'x86_64' ] && [ "$ARCHI" != 'aarch64' ]; then
    echo "Unknown platform $ARCHI, exiting"
    exit 1
fi
if [ $# -eq 0 ]
  then
    echo "Error: No metric server URL specified"
    exit 1
fi
UI_SERVER=$1
if [[ ! "$UI_SERVER" =~ ^http  ]]; then
  UI_SERVER="http://$UI_SERVER:8428" # augment an EC2 IPv4 DNS
fi
echo "Metric server URL used: ${UI_SERVER}"

function activate_node_exporter() { # setting up Prometheus node exporter
  echo 'Installing node exporter'
  sudo useradd --no-create-home --shell /bin/false node_exporter
  cd /tmp || exit 1
  if [ "$ARCHI" = "x86_64" ]
  then
	  wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
  elif [ "$ARCHI" = "aarch64" ]
  then
    wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-arm64.tar.gz
  fi
  tar -xvzf node_exporter-*
  sudo mv node_exporter-*/node_exporter /usr/local/bin/
  sudo chown node_exporter:node_exporter /usr/local/bin/node_exporter
  rm -rf node_exporter-*
  cat <<EOF >> /tmp/node_exporter.service
[Unit]
Description=Node Exporter

[Service]
User=node_exporter
Group=node_exporter
ExecStart=/usr/local/bin/node_exporter $MOUNT_BLACKLIST $FS_BLACKLIST $DISABLED_COLLECTORS

[Install]
WantedBy=multi-user.target
EOF
  sudo cp node_exporter.service /etc/systemd/system/node_exporter.service
  sudo chown node_exporter:node_exporter /etc/systemd/system/node_exporter.service
  sudo systemctl daemon-reload && sudo systemctl start node_exporter && sudo systemctl enable node_exporter
  echo 'Node exporter has been activated'
}

function prepare_metrics_agent() { # setting up VM metrics agent
  echo 'Installing VM agent'
  sudo useradd --no-create-home --shell /bin/false metrics_agent
  cd /tmp || exit 1
  if [ "$ARCHI" = "x86_64" ]
  then
    wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.98.0/vmutils-linux-amd64-v1.98.0.tar.gz
  elif [ "$ARCHI" = "aarch64" ]
  then
    wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.98.0/vmutils-linux-arm64-v1.98.0.tar.gz
  fi
  tar -xvzf vmutils*
  cat <<EOF >> /tmp/metrics_agent.service
[Unit]
Description=Metrics Agent

[Service]
User=metrics_agent
Group=metrics_agent
ExecStart=$AGENT_CMD

[Install]
WantedBy=multi-user.target
EOF
  sudo sed -i "s|METRIC_SERVER|$UI_SERVER|g" /tmp/metrics_agent.service

  cat << 'EOF' >> /tmp/scrape_config.yaml
global:
  scrape_interval: 10s
scrape_configs:
  - job_name: node_scraper
    static_configs:
    - targets: ['localhost:9100']
      labels:
        job: 'node_scraper'
        cluster_id: 'CLUSTER_ID'
        instance: 'CONTAINER_IP'
        instance_type: 'INSTANCE_TYPE'
        role: 'NODE_ROLE'
EOF

  cat << 'EOF' >> /tmp/write_relabel.yaml
- action: drop
  if:
  - '{__name__=~".*(DAGScheduler|BlockManager|LiveListenerBus|HiveExternalCatalog|CodeGenerator|NettyBlockTransfer).*"}'
- action: graphite
  match: "*.*.*.*.*.*"
  labels:
        __name__: "spark_${4}_${5}_${6}"
        app_id: "$1"
        agent: "$2"
        ns: "$3"
        job: "spark_scraper"
        cluster_id: "CLUSTER_ID"
        instance: "CONTAINER_IP"
- action: graphite
  match: "*.*.*.*.*"
  labels:
        __name__: "spark_${4}_${5}"
        app_id: "$1"
        agent: "$2"
        ns: "$3"
        job: "spark_scraper"
        cluster_id: "CLUSTER_ID"
        instance: "CONTAINER_IP"
- action: graphite
  match: "*.*.*.*"
  labels:
        __name__: "spark_${4}"
        app_id: "$1"
        agent: "$2"
        ns: "$3"
        job: "spark_scraper"
        cluster_id: "CLUSTER_ID"
        instance: "CONTAINER_IP"
EOF
}

function activate_metrics_agent() { # activating metrics agent and creating a metrics.properties file for Spark
  cat << 'EOF' >> /tmp/emr_metrics_setup.sh
#!/bin/bash

while [ ! -e /mnt/var/lib/info/job-flow-state.txt ] || [ "$(grep -o 'extraInstanceData {' /mnt/var/lib/info/job-flow-state.txt | wc -l)" -lt 1 ];do
  sleep 2
done
echo "Job flow file has become available"

EMR_CLUSTER_ID=$(grep jobFlowId /mnt/var/lib/info/job-flow-state.txt | awk '{gsub(/"/, ""); print $2}')
NODE_ROLE=$(grep instanceRole /mnt/var/lib/info/job-flow-state.txt | awk '{gsub(/"/, ""); print $2}')
INSTANCE_TYPE=$(grep instanceGroupInstanceType /mnt/var/lib/info/job-flow-state.txt | awk '{gsub(/"/, ""); print $2}')
sudo sed -i "s|CLUSTER_ID|$EMR_CLUSTER_ID|g" /tmp/scrape_config.yaml
sudo sed -i "s|CONTAINER_IP|$HOSTNAME|g" /tmp/scrape_config.yaml
sudo sed -i "s|NODE_ROLE|$NODE_ROLE|g" /tmp/scrape_config.yaml
sudo sed -i "s|INSTANCE_TYPE|$INSTANCE_TYPE|g" /tmp/scrape_config.yaml
sudo sed -i "s|CLUSTER_ID|$EMR_CLUSTER_ID|g" /tmp/write_relabel.yaml
sudo sed -i "s|CONTAINER_IP|$HOSTNAME|g" /tmp/write_relabel.yaml
sudo mv /tmp/vmagent-prod /usr/local/bin/
sudo chown metrics_agent:metrics_agent /usr/local/bin/vmagent-prod
rm /tmp/vm*-prod
rm vmutils-*.gz
sudo mv /tmp/metrics_agent.service /etc/systemd/system/metrics_agent.service
sudo chown metrics_agent:metrics_agent /etc/systemd/system/metrics_agent.service
sudo systemctl daemon-reload && sudo systemctl start metrics_agent && sudo systemctl enable metrics_agent
echo 'Finished installing metrics agent'

if grep isMaster /mnt/var/lib/info/instance.json | grep false; then
  echo "Finished second observability script on worker node, exiting"
  exit 0
fi

# Modifying Spark's metrics.properties file:
while [ ! -e /usr/lib/spark/conf/metrics.properties ];do
  sleep 2
done
echo "EMR Spark has become available"
echo "*.sink.graphite.class=org.apache.spark.metrics.sink.GraphiteSink" | sudo tee -a /usr/lib/spark/conf/metrics.properties
echo "*.source.jvm.class=org.apache.spark.metrics.source.JvmSource" | sudo tee -a /usr/lib/spark/conf/metrics.properties
echo "*.sink.graphite.host=localhost" | sudo tee -a /usr/lib/spark/conf/metrics.properties
echo "*.sink.graphite.port=2003" | sudo tee -a /usr/lib/spark/conf/metrics.properties
echo "*.sink.graphite.period=10" | sudo tee -a /usr/lib/spark/conf/metrics.properties
echo "*.sink.graphite.unit=seconds" | sudo tee -a /usr/lib/spark/conf/metrics.properties
echo "Created a metrics.properties file"

echo "Activating additional metric sources"
while [ ! -e /usr/lib/spark/conf/spark-defaults.conf ];do
  sleep 2
done
echo "Configuration file has become available"
echo "spark.metrics.appStatusSource.enabled true" | sudo tee -a /usr/lib/spark/conf/spark-defaults.conf
echo "spark.executor.processTreeMetrics.enabled true" | sudo tee -a /usr/lib/spark/conf/spark-defaults.conf
echo "Activated additional metric sources"

echo 'Finished auxiliary bootstrap script'
exit 0
EOF
}

activate_node_exporter
prepare_metrics_agent
activate_metrics_agent
chmod +x /tmp/emr_metrics_setup.sh
echo 'Starting auxiliary bootstrap script (push EMR)'
sudo nohup /tmp/emr_metrics_setup.sh &
echo 'Finished main bootstrap script (push EMR)'
exit 0

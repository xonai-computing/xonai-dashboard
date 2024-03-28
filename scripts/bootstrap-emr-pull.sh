#!/bin/bash
# Xonai Dashboard bootstrap script EMR pull (https://github.com/xonai-computing/xonai-dashboard)

MOUNT_BLACKLIST=${MOUNT_BLACKLIST:-'--collector.filesystem.mount-points-exclude=^/(mnt/tmp|dbfs|Workspace|dev|proc|run/credentials/.+|sys|var/lib/docker/.+|var/lib/containers/storage/.+)($|/)'}
FS_BLACKLIST=${FS_BLACKLIST:-'--collector.filesystem.fs-types-exclude=^(tmpfs|autofs|binfmt_misc|bpf|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|iso9660|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tracefs)$'}
DISABLED_COLLECTORS=${DISABLED_COLLECTORS:-'--web.disable-exporter-metrics --no-collector.arp --no-collector.bonding --no-collector.btrfs --no-collector.conntrack --no-collector.dmi --no-collector.entropy --no-collector.fibrechannel --no-collector.hwmon --no-collector.mdadm --no-collector.netstat --no-collector.os --no-collector.powersupplyclass --no-collector.pressure --no-collector.rapl --no-collector.schedstat --no-collector.selinux --no-collector.sockstat --no-collector.softnet --no-collector.stat --no-collector.tapestats --no-collector.textfile --no-collector.thermal_zone --no-collector.time --no-collector.timex --no-collector.udp_queues --no-collector.xfs --no-collector.zfs'}

echo 'Starting main bootstrap script (pull EMR)'
ARCHI=$(uname -m) # x86_64 or aarch64
if [ "$ARCHI" != 'x86_64' ] && [ "$ARCHI" != 'aarch64' ]; then
    echo "Unknown platform $ARCHI, exiting"
    exit 1
fi

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

function activate_metrics_agent() {  # setting up Telegraf metrics agent
  echo 'Installing Telegraf agent'
  cd /tmp || exit 1
  if [ "$ARCHI" = "x86_64" ]
  then
	  wget https://dl.influxdata.com/telegraf/releases/telegraf-1.29.5-1.x86_64.rpm
	  yes | sudo yum localinstall telegraf-1.29.5-1.x86_64.rpm
  elif [ "$ARCHI" = "aarch64" ]
  then
	  wget https://dl.influxdata.com/telegraf/releases/telegraf-1.29.5-1.aarch64.rpm
	  yes | sudo yum localinstall telegraf-1.29.5-1.aarch64.rpm
  fi

  cat << 'EOF' >> /tmp/telegraf.conf
[agent]
  omit_hostname = true # using `instance` tag instead

[[outputs.prometheus_client]]
  listen = ":9102" # address to listen on
  path = "/metrics" # Path to publish the metrics on.
  expiration_interval = "16s" # expiration interval for each metric. 0 == no expiration
  collectors_exclude = ["gocollector", "process"] # disabled collectors, valid entries are "gocollector" and "process"

# Socket listener for Spark metrics
[[inputs.socket_listener]]
  service_address = "tcp://:2003"
  data_format = "graphite"
  separator = "_"
  templates = [
        "*.*.*.*.* measurement.app_id.agent.ns.measurement*", # spark_local-1670697562387_driver_appStatus_tasks_completedTasks_count
  ]
  [inputs.socket_listener.tagdrop]
    ns = ["DAGScheduler", "BlockManager", "LiveListenerBus", "HiveExternalCatalog", "CodeGenerator", "NettyBlockTransfer"]

# Generic HTTP write listener
[[inputs.http_listener_v2]]
  service_address = ":8080" # address and port to host HTTP listener on
  paths = ["/telegraf"] # paths to listen to
  methods = ["POST"]
  data_format = "prometheus"
EOF
  sudo mv telegraf.conf /etc/telegraf/telegraf.conf
  sudo systemctl daemon-reload && sudo systemctl enable --now telegraf
}


function configure_spark_metrics() { # creating a metrics.properties file for Spark
  cat << 'EOF' >> /tmp/emr_metrics_setup.sh
#!/bin/bash
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
echo "*.sink.graphite.prefix=spark" | sudo tee -a /usr/lib/spark/conf/metrics.properties
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
activate_metrics_agent
if grep isMaster /mnt/var/lib/info/instance.json | grep false; then
  echo 'Finished main bootstrap script (pull EMR) on worker node, exiting'
  exit 0
fi
configure_spark_metrics
chmod +x /tmp/emr_metrics_setup.sh
echo 'Starting auxiliary bootstrap script (pull EMR)'
sudo nohup /tmp/emr_metrics_setup.sh &
echo 'Finished main bootstrap script (pull EMR)'
exit 0

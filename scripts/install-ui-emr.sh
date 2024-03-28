#!/bin/bash
# Xonai Dashboard installation script for EMR (https://github.com/xonai-computing/xonai-dashboard)

echo 'Starting installation of Xonai Dashboard'
export ACTIVE_PLATFORM='AWS_EMR'
ARCHI=$(uname -m) # EC2 instance architecture, x86_64 or aarch64
if [ "$ARCHI" != 'x86_64' ] && [ "$ARCHI" != 'aarch64' ]; then
    echo "Unknown platform $ARCHI, exiting"
    exit 1
fi
INGESTION='push'  # default value
if [ "$INGESTION_MODE" != "" ]
  then
  INGESTION=$(echo "$INGESTION_MODE" | tr '[:upper:]' '[:lower:]')
fi
if [ "$INGESTION" != 'pull' ] && [ "$INGESTION" != 'push' ]; then
  echo "Unknown ingestion mode $INGESTION supplied, value of $INGESTION_MODE must be 'push' or 'pull'"
  exit 1
fi
echo "Enabled $ACTIVE_PLATFORM using architecture $ARCHI"
echo "Ingestion mode: $INGESTION"
echo "Supplied AWS regions (optional): $AWS_REGIONS"  # for example us-east-1
echo "Allow anonymous access (optional): $ALLOW_ANONYMOUS"
echo "Allow embeddings (optional): $ALLOW_EMBEDDING"
SERVER_CMD=${SERVER_CMD:-'python3.11 -m uvicorn xonai_grafana.main:app'}
DB_CMD=${DB_CMD:-'/usr/local/bin/victoria-metrics-prod -storageDataPath /var/lib/victoria -retentionPeriod=4'}  # for default push mode
if [ "$INGESTION" = 'pull' ]; then
  DB_CMD='/usr/local/bin/victoria-metrics-prod -promscrape.config /etc/victoria/conf/scrape_config.yaml --enableTCP6 -storageDataPath /var/lib/victoria -retentionPeriod=4'
fi
# Downloading relevant repo items
yes | sudo yum install git
cd /tmp || exit 1
git clone -n --depth=1 --filter=tree:0 https://github.com/xonai-computing/xonai-dashboard
cd xonai-dashboard || exit 1
git sparse-checkout set --no-cone xonai-grafana dashboards/emr
git checkout
mv dashboards/emr/* dashboards/ && rm -rf dashboards/emr
rm -rf .git

function install_db() { # setting up time-series DB feeding Grafana
  echo 'Starting database installation'
  EC2_REGION=$(echo $AWS_REGIONS | cut -d "," -f 1)  # only relevant for pull mode, take first region if multiple were specified
  if [ "$INGESTION_MODE" = 'pull' ]; then  # determine scrape region, exit immediately if insufficient info supplied
      if [ "$EC2_REGION" = "" ]  # no AWS regions were supplied
        then
          # determine via API call, see https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instancedata-data-retrieval.html
          TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
          EC2_AVAIL_ZONE=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/placement/availability-zone)
          EC2_REGION=$(echo "$EC2_AVAIL_ZONE" | sed 's/[a-z]$//')
          AWS_REGIONS=$EC2_REGION
      fi
      if [ "$EC2_REGION" = "" ]
        then
          echo "Error: Unable to determine scrape region, please supply it via the AWS_REGIONS environment variable"
          exit 1
      fi
      echo "Using scrape region $EC2_REGION for scrape_config.yaml file, supplied region was $AWS_REGIONS"
  fi
  cd /tmp || exit 1
  if [ "$ARCHI" = "x86_64" ]
  then
    wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.98.0/victoria-metrics-linux-amd64-v1.98.0.tar.gz
  elif [ "$ARCHI" = "aarch64" ]
  then
    wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.98.0/victoria-metrics-linux-arm64-v1.98.0.tar.gz
  fi
  tar xvf victoria-*
  rm victoria-*.tar.gz
  sudo useradd --no-create-home --shell /bin/false victoria
  sudo cp victoria-metrics-prod /usr/local/bin/
  sudo chown victoria:victoria /usr/local/bin/victoria-metrics-prod
  # create directory that will store metric data:
  sudo mkdir -p /var/lib/victoria
  sudo chown -R victoria:victoria /var/lib/victoria
  if [ "$INGESTION_MODE" = 'pull' ]; then
    # create scrape configuration for VictoriaMetrics in pull mode, only relevant for EMR currently
    sudo mkdir -p /etc/victoria/conf
    sudo chown -R victoria:victoria /etc/victoria
    cat << 'EOF' >> /tmp/scrape_config.yaml
global:
  scrape_interval: 10s # How frequently to scrape targets
scrape_configs:
  - job_name: 'spark_scraper'
    ec2_sd_configs:
    - region: REGION
      port: 9102
      filters:
      - name: instance-state-name
        values:
        - running
      - name: tag:aws:elasticmapreduce:instance-group-role
        values:
        - MASTER
        - CORE
        - TASK
    relabel_configs:
    - source_labels: [__meta_ec2_tag_aws_elasticmapreduce_job_flow_id]
      target_label: cluster_id
    - source_labels: [__meta_ec2_private_ip]
      target_label: instance
  - job_name: 'node_scraper'
    ec2_sd_configs:
    - region: REGION
      port: 9100
      filters:
      - name: instance-state-name
        values:
        - running
      - name: tag:aws:elasticmapreduce:instance-group-role
        values:
        - MASTER
        - CORE
        - TASK
    relabel_configs:
    - source_labels: [__meta_ec2_tag_aws_elasticmapreduce_job_flow_id]
      target_label: cluster_id
    - source_labels: [__meta_ec2_private_ip]
      target_label: instance
    - source_labels: [__meta_ec2_instance_type]
      target_label: instance_type
    - source_labels: [__meta_ec2_tag_aws_elasticmapreduce_instance_group_role]
      target_label: role
EOF
    sudo sed "s/REGION/${EC2_REGION}/g" /tmp/scrape_config.yaml | sudo tee /etc/victoria/conf/scrape_config.yaml
    sudo chown victoria:victoria /etc/victoria/conf/scrape_config.yaml
  fi
  # set up daemon:
  cat << EOF >> /tmp/victoria.service
[Unit]
Description=VictoriaMetrics
Wants=network-online.target
After=network-online.target

[Service]
User=victoria
Group=victoria
ExecStart=$DB_CMD
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  sudo mv /tmp/victoria.service /etc/systemd/system/victoria.service
  sudo chown victoria:victoria /etc/systemd/system/victoria.service
  sudo systemctl daemon-reload && sudo systemctl enable --now victoria
  rm /tmp/victoria-metrics-prod
  echo 'Finished installing database'
}

function install_server() { # setting up web server feeding Grafana
  echo 'Starting web server installation'
  cd /tmp || exit 1
  # set up Python environment:
  yes | sudo yum install python3.11
  python3.11 -m ensurepip
  python3.11 -m pip install --upgrade pip
  python3.11 -m pip install -r /tmp/xonai-dashboard/xonai-grafana/requirements.txt
  echo "Calling helper script fetch_cost_info.py to download cost info from AWS APIs"
  python3.11 /tmp/xonai-dashboard/xonai-grafana/xonai_grafana/cost_estimation/fetch_cost_info.py "$AWS_REGIONS"
  echo "Finished helper script fetch_cost_info.py to download cost info, installing the module now"
  python3.11 -m pip install --user /tmp/xonai-dashboard/xonai-grafana/.
  # set up daemon:
  cat << EOF >> /tmp/xonai_grafana.service
[Unit]
Description=Web Server for Xonai Dashboard
Wants=network-online.target
After=network-online.target

[Service]
User=ec2-user
Group=ec2-user
ExecStart=$SERVER_CMD
Environment="AWS_REGIONS=$AWS_REGIONS"
Environment="ACTIVE_PLATFORM=$ACTIVE_PLATFORM"
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  sudo cp /tmp/xonai_grafana.service /etc/systemd/system/xonai_grafana.service
  sudo chown ec2-user:ec2-user /etc/systemd/system/xonai_grafana.service
  sudo systemctl daemon-reload && sudo systemctl enable --now xonai_grafana
  rm -rf /tmp/xonai-dashboard/xonai-grafana/
  echo 'Finished installing web server'
}

function install_grafana() { # setting up Grafana UI with cloud dashboards and Prometheus & JSON data sources
  echo 'Starting Grafana installation'
  cd /tmp || exit 1
  if [ "$ARCHI" = "x86_64" ]
  then
    sudo yum install -y https://dl.grafana.com/oss/release/grafana-10.3.3-1.x86_64.rpm
  elif [ "$ARCHI" = "aarch64" ]
  then
    sudo yum install -y https://dl.grafana.com/oss/release/grafana-10.3.3-1.aarch64.rpm
  fi
  sudo grafana-cli plugins install simpod-json-datasource
  # configuring data sources:
  cat << 'EOF' >> /tmp/prometheus_datasource.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:8428
    editable: true
    uid: prometheusdatasource
    jsonData:
      timeInterval: 10s
EOF
  # access value `direct` would corresponds to "Browser"
  cat << 'EOF' >> /tmp/json_datasource.yaml
apiVersion: 1
datasources:
  - name: JSON
    type: simpod-json-datasource
    url: http://localhost:8000
    access: proxy
    editable: true
    uid: jsondatasource
EOF
  sudo mkdir -p /etc/grafana/provisioning/datasources
  sudo mv /tmp/prometheus_datasource.yaml /etc/grafana/provisioning/datasources/prometheus.yaml
  sudo mv /tmp/json_datasource.yaml /etc/grafana/provisioning/datasources/json_datasource.yaml
  # configuring cloud dashboards:
  sudo mkdir -p /etc/grafana/provisioning/dashboards
  cat << 'EOF' >> /tmp/dashboard_provider.yaml
apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: ''
    folderUid: ''
    type: file
    disableDeletion: false
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
EOF
  sudo mv /tmp/dashboard_provider.yaml /etc/grafana/provisioning/dashboards/default.yaml
  # download cloud dashboards:
  sudo mkdir -p /var/lib/grafana/dashboards
  sudo mv /tmp/xonai-dashboard/dashboards/* /var/lib/grafana/dashboards
  sudo chown -R grafana:grafana /var/lib/grafana
  if [ "$ALLOW_ANONYMOUS" = "true" ] # must match within [auth.anonymous] section
    then
      sudo perl -i -pe 'BEGIN{undef $/;} s/\[auth\.anonymous\]\n# enable anonymous access\n;enabled = false/\[auth\.anonymous\]\n# enable anonymous access\nenabled = true/smg' /etc/grafana/grafana.ini
  fi
  if [ "$ALLOW_EMBEDDING" = "true" ]
    then
      if [ "$ALLOW_ANONYMOUS" != "true" ] # login page cannot be passed when access is not anonymous => samesite setting change required
        then
          sudo sed -i 's|;cookie_samesite = lax|cookie_samesite = disabled|' /etc/grafana/grafana.ini
      fi
    sudo sed -i 's|;allow_embedding = false|allow_embedding = true|' /etc/grafana/grafana.ini
  fi
  # start Grafana daemon:
  sudo systemctl daemon-reload && sudo systemctl enable --now grafana-server.service
  rm -rf /tmp/xonai-dashboard/dashboards/
  echo 'Finished installing Grafana'
}

# invoking all installation procedures:
install_db
install_server
install_grafana
echo 'Installation of Xonai Dashboard completed'

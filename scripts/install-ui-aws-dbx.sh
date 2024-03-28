#!/bin/bash
# Xonai Dashboard installation script for AWS Databricks (https://github.com/xonai-computing/xonai-dashboard)

echo 'Starting installation of Xonai Dashboard'
export ACTIVE_PLATFORM='AWS_DBX'
ARCHI=$(uname -m) # EC2 instance architecture, x86_64 or aarch64
if [ "$ARCHI" != 'x86_64' ] && [ "$ARCHI" != 'aarch64' ]; then
    echo "Unknown platform $ARCHI, exiting"
    exit 1
fi
if [[  "$DATABRICKS_HOST" = "" || "$DATABRICKS_TOKEN" = ""  ]]; then
 echo "AWS DBX activated but native authentication credentials (DATABRICKS_HOST and DATABRICKS_TOKEN) not set:"
  echo "DATABRICKS_HOST: $DATABRICKS_HOST"
  echo "DATABRICKS_TOKEN: $DATABRICKS_TOKEN"
 exit 1
fi
echo "Enabled $ACTIVE_PLATFORM using architecture $ARCHI"
echo "Ingestion mode: push"
echo "Supplied AWS regions (optional): $AWS_REGIONS"  # for example us-east-1
echo "Allow anonymous access (optional): $ALLOW_ANONYMOUS"
echo "Allow embeddings (optional): $ALLOW_EMBEDDING"
SERVER_CMD=${SERVER_CMD:-'python3.11 -m uvicorn xonai_grafana.main:app'}
DB_CMD=${DB_CMD:-'/usr/local/bin/victoria-metrics-prod -storageDataPath /var/lib/victoria -retentionPeriod=4'}
# Downloading relevant repo items
yes | sudo yum install git
cd /tmp || exit 1
git clone -n --depth=1 --filter=tree:0 https://github.com/xonai-computing/xonai-dashboard
cd xonai-dashboard || exit 1
git sparse-checkout set --no-cone xonai-grafana dashboards/aws-dbx
git checkout
mv dashboards/aws-dbx/* dashboards/ && rm -rf dashboards/aws-dbx
rm -rf .git

function install_db() { # setting up time-series DB feeding Grafana
  echo 'Starting database installation'
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
Environment="DATABRICKS_HOST=$DATABRICKS_HOST"
Environment="DATABRICKS_TOKEN=$DATABRICKS_TOKEN"
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  sudo mv /tmp/xonai_grafana.service /etc/systemd/system/xonai_grafana.service
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

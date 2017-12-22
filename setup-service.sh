#!/bin/bash
set -x

mkdir -p /var/log/speedtestrebooter
chown pi.pi /var/log/speedtestrebooter
touch /var/log/speedtestrebooter/speedtestrebooter.log
chown pi.pi /var/log/speedtestrebooter/speedtestrebooter.log
cp speedtestrebooter.service /lib/systemd/system/speedtestrebooter.service
chmod 644 /lib/systemd/system/speedtestrebooter.service
systemctl daemon-reload
systemctl enable speedtestrebooter.service
systemctl start speedtestrebooter.service
systemctl status speedtestrebooter.service

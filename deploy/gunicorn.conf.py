bind = "127.0.0.1:8000"
workers = 2  # Revisit after measuring the actual droplet and classroom pilot.
worker_class = "sync"
timeout = 60
accesslog = None
errorlog = "-"
loglevel = "warning"
capture_output = False
# Django handles the proxy scheme after verifying the peer; Gunicorn must keep REMOTE_ADDR.
forwarded_allow_ips = ""
forwarder_headers = ""
control_socket_disable = True

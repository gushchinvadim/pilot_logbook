import os

bind = '127.0.0.1:8010'
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = 2
worker_class = 'gthread'
timeout = 120
accesslog = '-'
errorlog = '-'
capture_output = True
# Nginx is the sole public entry point.
forwarded_allow_ips = '127.0.0.1,::1'

# Managed through systemd; the worker must not create a management socket in its home/code parent.
control_socket_disable = True

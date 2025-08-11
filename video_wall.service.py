[Unit]
Description=Video Wall Control Panel Backend
After=network.target

[Service]
Type=simple
User=videowall
Group=videowall
WorkingDirectory=/opt/video-wall-control
Environment=PATH=/opt/video-wall-control/venv/bin
ExecStart=/opt/video-wall-control/venv/bin/python video_wall_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
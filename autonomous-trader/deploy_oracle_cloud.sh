#!/bin/bash
# deploy_oracle_cloud.sh

# Install dependencies
sudo apt update
sudo apt install -y python3.11 python3-pip nodejs npm nginx certbot

# Clone your repo
git clone https://github.com/yourusername/autonomous-trader.git
cd autonomous-trader

# Setup Python backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup frontend
cd dashboard
npm install
npm run build

# Setup Nginx reverse proxy
sudo cp nginx.conf /etc/nginx/sites-available/autonomous-trader
sudo ln -s /etc/nginx/sites-available/autonomous-trader /etc/nginx/sites-enabled/
sudo systemctl restart nginx

# Setup free SSL (Let's Encrypt)
sudo certbot --nginx -d yourdomain.com

# Setup systemd service (auto-restart)
sudo cp autonomous-trader.service /etc/systemd/system/
sudo systemctl enable autonomous-trader
sudo systemctl start autonomous-trader

echo '✅ Deployed to Oracle Cloud (FREE FOREVER)'

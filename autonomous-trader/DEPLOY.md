# ORACLE CLOUD DEPLOYMENT (100% FREE FOREVER)

## 1. Sign Up for Oracle Cloud
https://www.oracle.com/cloud/free/
- No credit card required after trial
- FREE FOREVER: 2 VMs with 4 CPUs + 24GB RAM EACH
- 200GB storage, 10TB bandwidth/month

## 2. Create Ubuntu VM
- Shape: Ampere A1 (ARM, free forever)
- Image: Ubuntu 22.04
- Boot volume: 100GB
- Open ports: 80, 443, 8000, 3000

## 3. Connect via SSH
ssh ubuntu@<your-vm-ip>

## 4. Install Dependencies
sudo apt update
sudo apt install -y python3.11 python3-pip nodejs npm nginx certbot git

## 5. Clone Your Project
git clone https://github.com/yourusername/ai-stock-advisor.git
cd ai-stock-advisor

## 6. Setup Python Backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

## 7. Setup Frontend
cd dashboard
npm install
npm run build

## 8. Configure Nginx
sudo nano /etc/nginx/sites-available/ai-stock-advisor

Add:
server {
    listen 80;
    server_name yourdomain.com;
    
    location /api {
        proxy_pass http://localhost:8000;
    }
    
    location / {
        root /home/ubuntu/ai-stock-advisor/dashboard/dist;
        try_files \ /index.html;
    }
}

sudo ln -s /etc/nginx/sites-available/ai-stock-advisor /etc/nginx/sites-enabled/
sudo systemctl restart nginx

## 9. Setup Free SSL (Let's Encrypt)
sudo certbot --nginx -d yourdomain.com

## 10. Setup Auto-Start Service
sudo nano /etc/systemd/system/ai-stock-advisor.service

Add:
[Unit]
Description=AI Stock Advisor Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/ai-stock-advisor
ExecStart=/home/ubuntu/ai-stock-advisor/venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target

sudo systemctl enable ai-stock-advisor
sudo systemctl start ai-stock-advisor

## ✅ DEPLOYED! Access at https://yourdomain.com

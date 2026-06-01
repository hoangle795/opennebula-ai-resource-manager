#!/bin/bash

# ==============================================================================
# Tên script: deploy.sh
# Chức năng: Triển khai tự động hệ thống NebulaStack (Phân tách Frontend & Host)
# Cú pháp:   ./deploy.sh [frontend | host]
# ==============================================================================

set -e # Dừng script nếu có lỗi

ROLE=$1

if [ -z "$ROLE" ]; then
    echo "❌ Lỗi: Bạn chưa chọn loại máy chủ cần triển khai."
    echo "💡 Hướng dẫn sử dụng:"
    echo "   Dành cho máy Frontend: ./deploy.sh frontend"
    echo "   Dành cho máy Host:     ./deploy.sh host"
    exit 1
fi

echo "🚀 BẮT ĐẦU CẬP NHẬT GÓI HỆ THỐNG CƠ BẢN..."
sudo apt-get update -y
sudo apt-get install -y git curl wget ufw

# ==============================================================================
# 1. TRIỂN KHAI CHO MÁY FRONTEND (API NODE)
# ==============================================================================
if [ "$ROLE" == "frontend" ]; then
    echo "🖥️ [FRONTEND] ĐANG TRIỂN KHAI TRUNG TÂM ĐIỀU KHIỂN & AI AGENT..."
    
    # 1.1 Cài đặt Python & Docker
    sudo apt-get install -y python3 python3-pip python3-venv
    if ! command -v docker &> /dev/null; then
        echo "🐋 Đang cài đặt Docker..."
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
        rm get-docker.sh
    fi
    if ! command -v docker-compose &> /dev/null; then
        sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
    fi

    # 1.2 Dựng Monitoring Stack
    echo "📊 Đang khởi động Prometheus, Grafana..."
    if [ -d "monitoring" ] && [ -f "monitoring/docker-compose.yml" ]; then
        cd monitoring && sudo docker-compose up -d && cd ..
    else
        echo "⚠️ Không tìm thấy cấu hình monitoring."
    fi

    # 1.3 Dựng AI Backend
    echo "🧠 Đang cấu hình AI Backend..."
    if [ -d "backend" ]; then
        cd backend
        python3 -m venv venv
        source venv/bin/activate
        pip install --upgrade pip
        if [ -f "requirements.txt" ]; then pip install -r requirements.txt; fi
        
        # Reset port và chạy ngầm Backend
        sudo fuser -k 8000/tcp || true
        nohup uvicorn main:app --host 0.0.0.0 --port 8000 > backend_api.log 2>&1 &
        deactivate
        cd ..
    fi

    # 1.4 Mở port tường lửa Frontend
    echo "🌐 Đang mở port tường lửa cho Frontend..."
    sudo ufw allow 8000/tcp # Backend API & Dashboard
    sudo ufw allow 3000/tcp # Grafana
    sudo ufw allow 9090/tcp # Prometheus
    sudo ufw allow 2633/tcp # OpenNebula XML-RPC (Nếu cần)

    echo "🎉 [FRONTEND] ĐÃ TRIỂN KHAI HOÀN TẤT!"
    echo "👉 Dashboard: http://$(hostname -I | awk '{print $1}'):8000"

# ==============================================================================
# 2. TRIỂN KHAI CHO MÁY HOST (COMPUTE NODE)
# ==============================================================================
elif [ "$ROLE" == "host" ]; then
    echo "💻 [HOST NODE] ĐANG TRIỂN KHAI NÚT TÍNH TOÁN..."

    # 2.1 Cài đặt Node Exporter để Prometheus thu thập metric
    echo "📈 Đang cài đặt Prometheus Node Exporter..."
    sudo apt-get install -y prometheus-node-exporter
    sudo systemctl enable prometheus-node-exporter
    sudo systemctl restart prometheus-node-exporter

    # 2.2 Các gói phụ trợ cho môi trường ảo hóa (KVM / Libvirt / OpenvSwitch)
    echo "⚙️ Đang đảm bảo các gói ảo hóa (KVM/QEMU)..."
    # Giả định bạn dùng KVM cho OpenNebula
    sudo apt-get install -y qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils

    # 2.3 Mở port tường lửa Host Node
    echo "🌐 Đang mở port tường lửa cho Host Node..."
    sudo ufw allow 9100/tcp # Cực kỳ quan trọng: Cho phép Frontend vào lấy log Node Exporter
    sudo ufw allow 22/tcp   # Cho phép Frontend SSH qua cấu hình (yêu cầu của OpenNebula)

    echo "🎉 [HOST NODE] ĐÃ TRIỂN KHAI HOÀN TẤT SẴN SÀNG ĐÓN MÁY ẢO!"
    echo "👉 IP của Node này: $(hostname -I | awk '{print $1}') (Hãy thêm IP này vào cấu hình Prometheus trên máy Frontend)"

else
    echo "❌ Lỗi: Tham số không hợp lệ. Chỉ chấp nhận 'frontend' hoặc 'host'."
    exit 1
fi
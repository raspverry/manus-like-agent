FROM ubuntu:22.04

# 必要なパッケージをインストール
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    nodejs npm curl wget git \
    ca-certificates sudo libnss3 libxss1 libasound2 libatk1.0-0 libatk-bridge2.0-0 \
    libx11-xcb1 libgtk-3-0 libdrm2 libgbm1 xvfb \
    && rm -rf /var/lib/apt/lists/*

# 非特権ユーザーを作成
RUN useradd -m -s /bin/bash ubuntu && \
    echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu

# Pythonパッケージのインストールは後ほど requirements.txt 経由で
# Node関係などはPlaywrightで使う

# 作業ディレクトリを作成
WORKDIR /home/ubuntu

# ユーザーを切り替え
USER ubuntu

# ワークスペースディレクトリを作成
RUN mkdir -p /home/ubuntu/workspace

WORKDIR /home/ubuntu/workspace

# コンテナが終了しないように
CMD ["bash", "-c", "sleep infinity"]

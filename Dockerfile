# Menggunakan Python 3.11 versi slim untuk performa yang ringan dan cepat
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# Menginstal dependensi sistem (ditambah libmagic1) dan langsung membersihkan cache apt
RUN apt-get -qq update && \
    apt-get -qq install -y ffmpeg wget unzip p7zip-full curl busybox aria2 fontconfig libmagic1 && \
    rm -rf /var/lib/apt/lists/*

COPY . /app
WORKDIR /app
RUN chmod 777 /app

# Mengunduh dan menginstal rclone, lalu menghapus file instalasinya agar bersih
RUN wget https://rclone.org/install.sh && \
    chmod 777 ./install.sh && \
    bash install.sh && \
    rm ./install.sh

# Meng-upgrade pip dan menginstal library dari requirements.txt
RUN pip3 install --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt

ENV PORT=8000
EXPOSE 8000

CMD sh start.sh

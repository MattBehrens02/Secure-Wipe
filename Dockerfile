FROM debian:12

# Prevent apt-get from asking for user input
ENV DEBIAN_FRONTEND=noninteractive 

# Install necessary packages
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    git \
    util-linux \
    smartmontools \
    coreutils \
    scrub \
    cryptsetup \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

# Install Python dependencies directly into the container
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

RUN useradd -m -s /bin/bash developer && \
    chown -R developer:developer /app

USER developer

CMD ["/bin/bash"]


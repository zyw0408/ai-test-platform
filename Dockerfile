FROM python:3.11-slim

# 设置中文编码与无缓冲输出
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# 安装系统基础工具与时区支持
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    && ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# 安装 Python 测试框架依赖
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
       requests \
       pytest \
       pytest-xdist \
       allure-pytest

# 复制代码到容器
COPY . /workspace

# 暴露局域网访问端口
EXPOSE 8080

# 默认启动 Web 控制台与报告服务器
CMD ["python3", "web_server.py"]

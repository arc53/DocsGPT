# Etapa de Construção
FROM ubuntu:mantic as builder

# Configura o modo não interativo para evitar prompts
ENV DEBIAN_FRONTEND=noninteractive

# Instala os pacotes necessários e o Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc curl wget unzip libc6-dev python3.11 python3-pip python3.11-venv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* 

# Verifica a instalação do Python e configura um link simbólico
RUN if [ ! -f /usr/bin/python3.11 ]; then \
        echo "Python 3.11 not found"; exit 1; \
    fi && \
    ln -s /usr/bin/python3.11 /usr/bin/python

# Baixa e descompacta o modelo
RUN wget https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip && \
    unzip mpnet-base-v2.zip -d model && \
    rm mpnet-base-v2.zip

# Instala o Rust
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

# Limpa para reduzir o tamanho do container
RUN apt-get purge -y wget unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copia o requirements.txt
COPY requirements.txt .

# Configura o ambiente virtual Python
RUN python3.11 -m venv /venv

# Ativa o ambiente virtual e instala os pacotes Python
ENV PATH="/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir tiktoken && \
    pip install --no-cache-dir -r requirements.txt

# Etapa Final
FROM ubuntu:mantic as final

# Instala o Python
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3.11 python3.11-venv && \
    ln -s /usr/bin/python3.11 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho
WORKDIR /app

# Cria um usuário não root: `appuser`
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

# Copia o ambiente virtual e o modelo da etapa de construção
COPY --from=builder /venv /venv
COPY --from=builder /model /app/model

# Copia o código da aplicação
COPY . /app/application

# Muda a propriedade do diretório /app para o appuser
RUN mkdir -p /app/application/inputs/local && \
    chown -R appuser:appuser /app

# Configura variáveis de ambiente
ENV FLASK_APP=app.py \
    FLASK_DEBUG=true \
    PATH="/venv/bin:$PATH"

# Expõe a porta em que o app roda
EXPOSE 7091

# Altera para o usuário não root
USER appuser

# Inicia o Gunicorn
CMD ["gunicorn", "-w", "2", "--timeout", "120", "--bind", "0.0.0.0:7091", "application.wsgi:app"]

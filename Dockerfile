FROM python:3.11-slim
WORKDIR /srv
COPY Seizo_Learn_Web.tar.xz /srv/Seizo_Learn_Web.tar.xz
COPY railway_host.py /srv/railway_host.py
RUN python -c "import tarfile; t=tarfile.open('/srv/Seizo_Learn_Web.tar.xz','r:xz'); t.extractall('/srv'); t.close()" \
    && rm /srv/Seizo_Learn_Web.tar.xz \
    && pip install --no-cache-dir 'numpy>=1.24,<3'
ENV PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
EXPOSE 8080
CMD ["python", "/srv/railway_host.py"]

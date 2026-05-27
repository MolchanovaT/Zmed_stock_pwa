FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Flask-админка слушает 5101
EXPOSE 5101

CMD ["python", "admin_app.py"]

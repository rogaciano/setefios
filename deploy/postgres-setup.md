# PostgreSQL setup

Use este roteiro no servidor para criar o banco e usuário do projeto `setefios`.

## Via psql

```bash
sudo -u postgres psql
```

```sql
CREATE USER setefios WITH PASSWORD '*Marien2012';
CREATE DATABASE setefios WITH OWNER setefios ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE setefios TO setefios;
```

## Aplicar arquivo SQL

```bash
sudo -u postgres psql -f /var/www/setefios/deploy/postgres_setup.sql
```

## Variáveis esperadas no `.env`

```env
DB_ENGINE=postgres
DB_NAME=setefios
DB_USER=setefios
DB_PASSWORD=troque-por-uma-senha-forte
DB_HOST=127.0.0.1
DB_PORT=5432
```

## Validar conexão

```bash
source /var/www/setefios/.venv/bin/activate
python manage.py check
python manage.py migrate
```

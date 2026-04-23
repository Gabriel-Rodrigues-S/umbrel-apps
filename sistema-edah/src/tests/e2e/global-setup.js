const { execSync } = require('node:child_process')

async function globalSetup() {
  const adminPassword = process.env.BOOTSTRAP_ADMIN_PASSWORD || 'admin123'
  const env = {
    ...process.env,
    BOOTSTRAP_ADMIN_PASSWORD: adminPassword,
    DJANGO_SECRET_KEY: process.env.DJANGO_SECRET_KEY || 'ci-e2e-secret-key',
    DJANGO_DEBUG: process.env.DJANGO_DEBUG || 'True',
    DJANGO_ALLOWED_HOSTS: process.env.DJANGO_ALLOWED_HOSTS || '127.0.0.1,localhost',
    DJANGO_CSRF_TRUSTED_ORIGINS:
      process.env.DJANGO_CSRF_TRUSTED_ORIGINS || 'http://127.0.0.1:8000,http://localhost:8000',
  }

  execSync('uv run python manage.py migrate --noinput', { stdio: 'inherit', env })
  execSync('uv run python manage.py bootstrap_sys_edah', { stdio: 'inherit', env })
  execSync(
    `uv run python manage.py shell -c "from church.models import User; u=User.objects.get(email='admin@igreja.com'); u.set_password('${adminPassword}'); u.save()"`,
    { stdio: 'inherit', env }
  )
}

module.exports = globalSetup

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python manage.py reset_sales_test_data --force

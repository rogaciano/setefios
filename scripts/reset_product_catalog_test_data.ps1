$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python manage.py reset_product_catalog_test_data --force

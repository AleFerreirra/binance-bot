param(
    [switch]$NoInstall
)

$ErrorActionPreference = "Stop"

if (-not $NoInstall) {
    python -m pip install -r requirements.txt
}

python -m pytest -q --cov=. --cov-report=term-missing

# Check for Administrator privileges
$IsElevated = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# Skip Scoop install if already present
if (Get-Command scoop -ErrorAction SilentlyContinue) {
    Write-Host "Scoop is already installed. Skipping installation."
} else {
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
    if ($IsElevated) {
        Invoke-Expression "& {$(Invoke-RestMethod get.scoop.sh)} -RunAsAdmin"
    } else {
        Invoke-WebRequest -useb get.scoop.sh | Invoke-Expression
    }
}

scoop install git uv
if (Test-Path -LiteralPath "./web.py") {
    # Already in target directory
}
elseif (Test-Path -LiteralPath "./agybridge/web.py") {
    Set-Location ./agybridge
}
else {
    $repoUrl = if ($env:REPO_URL) { $env:REPO_URL } else { "https://github.com/your-username/agybridge.git" }
    git clone $repoUrl agybridge
    Set-Location ./agybridge
}

# Create virtual environment
$env:UV_VENV_CLEAR = "1"
uv venv --relocatable
uv sync
.venv/Scripts/activate.ps1
python web.py

$projectRoot = Get-Location
$zipPath = Join-Path $projectRoot "..\async_4x_sim.zip"

Get-ChildItem . -Recurse -File |
Where-Object {
    $_.FullName -notmatch '\\(.git|__pycache__|\.venv|node_modules|dist|build)\\'
} |
Compress-Archive -DestinationPath $zipPath -Force

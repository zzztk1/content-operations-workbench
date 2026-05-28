$ErrorActionPreference = "Stop"

$pgBin = "C:\Program Files\PostgreSQL\16\bin"
$pgLib = "C:\Program Files\PostgreSQL\16\lib"
$dataDir = "F:\codex\codex1\projects\media-agent\data\postgresql16\data"

$env:PATH = "$pgBin;$pgLib;$env:PATH"

& "$pgBin\pg_ctl.exe" -D $dataDir stop

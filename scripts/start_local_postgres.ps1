$ErrorActionPreference = "Stop"

$pgBin = "C:\Program Files\PostgreSQL\16\bin"
$pgLib = "C:\Program Files\PostgreSQL\16\lib"
$dataDir = "F:\codex\codex1\projects\media-agent\data\postgresql16\data"
$logFile = "F:\codex\codex1\projects\media-agent\data\postgresql16\run\postgresql.log"

$env:PATH = "$pgBin;$pgLib;$env:PATH"

& "$pgBin\pg_ctl.exe" -D $dataDir -l $logFile -o '"-p 65432 -h 127.0.0.1"' start

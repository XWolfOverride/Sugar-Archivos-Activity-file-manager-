# Genera dist\Archivos-<version>.xo (un .zip con la carpeta Archivos.activity/).
#
# Uso (desde cualquier carpeta, en Windows con PowerShell):
#     powershell -ExecutionPolicy Bypass -File tools\package.ps1
#
# No necesita Python ni Sugar ni git: recorre las carpetas y comprime. Los
# ficheros de texto se guardan con saltos de linea LF (el repositorio usa CRLF
# y un \r rompe los scripts de Linux). No se incluyen pruebas, herramientas,
# documentacion de desarrollo ni ficheros de git.
# (En un Sugar con git tambien vale: python setup.py dist_xo.)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$info = [IO.File]::ReadAllText((Join-Path $root 'activity\activity.info'))
if ($info -notmatch '(?m)^activity_version\s*=\s*(\S+)') { throw 'no encuentro activity_version' }
$version = $Matches[1]
$dist = Join-Path $root 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$xo = Join-Path $dist ("Archivos-$version.xo")
if (Test-Path $xo) { Remove-Item $xo -Force }

$skipDirs = 'dist', '.git', 'tests', 'tools', 'DOC', '__pycache__'
$skipFiles = '.gitignore', 'AGENTS.md', 'CLAUDE.md'
$skipExt = '.pyc', '.pyo', '.xo'
$textExt = '.py', '.info', '.svg', '.md', '.txt', '.po', '.pot', '.xml', '.sh', '.json', '.cfg'
$utf8 = New-Object Text.UTF8Encoding $false

function Add-Folder($zip, [string]$dir, [string]$rel) {
    foreach ($item in Get-ChildItem -LiteralPath $dir -Force) {
        $name = if ($rel) { "$rel/$($item.Name)" } else { $item.Name }
        if ($item.PSIsContainer) {
            if ($rel -eq '' -and ($skipDirs -contains $item.Name)) { continue }
            if ($item.Name -eq '__pycache__') { continue }
            Add-Folder $zip $item.FullName $name
            continue
        }
        if ($rel -eq '' -and ($skipFiles -contains $item.Name)) { continue }
        $ext = $item.Extension.ToLower()
        if ($skipExt -contains $ext) { continue }
        $bytes = [IO.File]::ReadAllBytes($item.FullName)
        if ($textExt -contains $ext) {
            $bytes = $utf8.GetBytes($utf8.GetString($bytes).Replace("`r`n", "`n"))
        }
        $entry = $zip.CreateEntry("Archivos.activity/$name", [IO.Compression.CompressionLevel]::Optimal)
        $stream = $entry.Open()
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Close()
        $script:count++
    }
}

$script:count = 0
$zip = [IO.Compression.ZipFile]::Open($xo, 'Create')
try { Add-Folder $zip $root '' } finally { $zip.Dispose() }
"{0}: {1} ficheros, {2:N0} KB" -f $xo, $script:count, ((Get-Item $xo).Length / 1KB)

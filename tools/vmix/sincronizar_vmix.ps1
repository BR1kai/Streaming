# Sincronizar vMix (version PowerShell, sin Python). Solo LEE vMix (GET a /api).
param([string]$Archivo = "", [switch]$Adoptar)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Norm($t){ $t = "$t".ToLower() -replace "\.(mp4|mov|jpg|png|mp3|wav)$","" -replace "[_\u2013\u2014-]"," " -replace "\s+"," "; return $t.Trim() }
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$espPath = Join-Path $aqui "esperado.json"
$esp = Get-Content $espPath -Raw -Encoding UTF8 | ConvertFrom-Json

try {
  if ($Archivo) { $xmlTxt = Get-Content $Archivo -Raw -Encoding UTF8 }
  else { $xmlTxt = (Invoke-WebRequest -Uri $esp.api -UseBasicParsing -TimeoutSec 5).Content }
} catch {
  Write-Host "No puedo leer vMix: $($_.Exception.Message)"
  Write-Host "Esta vMix abierto y el Web Controller activado (Settings > Web Controller)?"
  exit 2
}
[xml]$x = $xmlTxt
$v = $x.vmix
$ins = @{}
foreach ($e in $v.inputs.input) {
  $capas = @()
  foreach ($o in @($e.overlay)) { if ($o) { $capas += "$($o.key)" } }
  $t = $e.title; if (-not $t) { $t = $e.'#text' }
  $ins["$($e.number)"] = @{ clave = "$($e.key)"; crudo = $e.InnerXml; titulo = "$t".Trim(); tipo = "$($e.type)"; capas = $capas }
}

$porClave = @{}
foreach ($k in $ins.Keys) { $porClave[$ins[$k].clave] = $k }
foreach ($k in @($ins.Keys)) { $ins[$k].capas = @($ins[$k].capas | ForEach-Object { if ($porClave.ContainsKey($_)) { $porClave[$_] } else { "?" } }) }
$snap = Join-Path $aqui "instantaneas"
New-Item -ItemType Directory -Force -Path $snap | Out-Null
$marca = Get-Date -Format "yyyyMMdd-HHmmss"
Set-Content (Join-Path $snap "vmix-$marca.xml") $xmlTxt -Encoding UTF8

$dif = New-Object System.Collections.ArrayList
$avisos = New-Object System.Collections.ArrayList
$ok = 0
if ($ins.Count -ne $esp.total_inputs) { [void]$dif.Add("Hay $($ins.Count) inputs y la guia dice $($esp.total_inputs).") } else { $ok++ }
foreach ($p in $esp.inputs.PSObject.Properties) {
  $n = $p.Name; $titulo = $p.Value
  if (-not $ins.ContainsKey($n)) { [void]$dif.Add("Input ${n}: falta (la guia dice '$titulo').") }
  elseif (-not ((Norm $ins[$n].titulo).Contains((Norm $titulo)) -or (Norm $titulo).Contains((Norm $ins[$n].titulo)))) { [void]$dif.Add("Input ${n}: se llama '$($ins[$n].titulo)' y la guia dice '$titulo'.") }
  else { $ok++ }
}
foreach ($n in $ins.Keys) { if (-not ($esp.inputs.PSObject.Properties.Name -contains $n)) { [void]$dif.Add("Input ${n} '$($ins[$n].titulo)': existe en vMix y no esta en la guia.") } }
$cont = @($esp.ndi_contenedores)
$ndi = @($ins.Keys | Where-Object { $ins[$_].tipo -ieq "NDI" } | ForEach-Object { [int]$_ } | Where-Object { $cont -notcontains $_ } | Sort-Object)
$ndiEsp = @($esp.ndi | Sort-Object)
if (($ndi -join ",") -ne ($ndiEsp -join ",")) { [void]$dif.Add("Inputs NDI en vMix: $($ndi -join ', '); la guia dice $($ndiEsp -join ', ').") } else { $ok++ }
foreach ($p in $esp.mixes.PSObject.Properties) {
  if ($ins.ContainsKey($p.Name)) {
    if ($ins[$p.Name].tipo -ine "Mix") { [void]$dif.Add("Input $($p.Name) deberia ser un Mix y es '$($ins[$p.Name].tipo)'.") } else { $ok++ }
  }
}
foreach ($p in $esp.presets.PSObject.Properties) {
  $n = $p.Name
  if (-not $ins.ContainsKey($n)) { continue }
  if ($ins[$n].capas.Count -eq 0) { [void]$avisos.Add("Input ${n}: no pude leer sus capas por la API; comprueba a mano ($(@($p.Value) -join ', ')).") }
  else {
    $reales = @($ins[$n].capas | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ } | Sort-Object -Unique)
    if (($reales -join ",") -ne (@($p.Value | Sort-Object) -join ",")) { [void]$dif.Add("Input ${n}: sus capas son $($reales -join ', ') y la guia dice $(@($p.Value) -join ', ').") } else { $ok++ }
  }
}
if ($esp.inputs.'7' -eq $esp.inputs.'14') { [void]$avisos.Add("Los inputs 7 y 14 figuran en la guia con el mismo nombre; aclara cual es el chyron de la sala.") }

Write-Host "vMix $($v.version) $($v.edition) - proyecto: $($v.preset)"
Write-Host "Comprobaciones correctas: $ok`n"
if ($dif.Count) { Write-Host "DIFERENCIAS CON LA GUIA ($($dif.Count)):"; $dif | ForEach-Object { Write-Host "  X $_" } } else { Write-Host "OK: vMix coincide con la guia." }
if ($avisos.Count) { Write-Host "`nAVISOS:"; $avisos | ForEach-Object { Write-Host "  ! $_" } }
Write-Host "`nLISTADO (numero | tipo | titulo):"
foreach ($k in ($ins.Keys | Sort-Object { [int]$_ })) { Write-Host ("  {0} | {1} | {2}" -f $k, $ins[$k].tipo, $ins[$k].titulo) }
Write-Host "`nCAPAS CRUDAS de 4, 5 y 6:"
foreach ($k in "4","5","6") { if ($ins.ContainsKey($k)) { $c = $ins[$k].crudo; if ($c.Length -gt 500) { $c = $c.Substring(0,500) }; Write-Host "  $k [$($ins[$k].tipo)] capas (inputs): $($ins[$k].capas -join ', ')" } }
Write-Host "`nInstantanea guardada en: instantaneas\vmix-$marca.xml"
if ($Adoptar -and $dif.Count) {
  $nuevo = [ordered]@{}
  foreach ($k in ($ins.Keys | Sort-Object { [int]$_ })) { $nuevo[$k] = $ins[$k].titulo }
  $esp.inputs = [pscustomobject]$nuevo; $esp.total_inputs = $ins.Count; $esp.ndi = $ndi
  $esp | ConvertTo-Json -Depth 6 | Set-Content $espPath -Encoding UTF8
  Write-Host "Guardado como nuevo esperado."
}

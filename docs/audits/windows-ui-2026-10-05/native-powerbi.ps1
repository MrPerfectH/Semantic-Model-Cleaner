param([int]$OwnedProcessId, [string]$AdomdAssembly, [switch]$Refresh, [string]$ExpectedMissingMeasure, [string]$OutputPath)
$ErrorActionPreference='Stop'
$owned=Get-CimInstance Win32_Process -Filter "ProcessId=$OwnedProcessId"
if($owned.CommandLine -notlike '*smc-*\.playwright-mcp*' -and $owned.CommandLine -notlike '*smc-*/.playwright-mcp*'){throw 'Not an owned synthetic project'}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -Path $AdomdAssembly
$root=[System.Windows.Automation.AutomationElement]::FromHandle((Get-Process -Id $OwnedProcessId).MainWindowHandle)
$engine=Get-CimInstance Win32_Process -Filter "ParentProcessId=$OwnedProcessId" | Where-Object Name -eq 'msmdsrv.exe'
$folder=[regex]::Match($engine.CommandLine,'-s "([^"]+)"').Groups[1].Value
$port=(Get-Content -LiteralPath (Join-Path $folder 'msmdsrv.port.txt') -Encoding Unicode).Trim()
$connection=New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port")
$connection.Open()
try{
 if($Refresh){
  $db=$connection.GetSchemaDataSet('DBSCHEMA_CATALOGS',$null).Tables[0].Rows[0].CATALOG_NAME
  $refreshCommand=$connection.CreateCommand()
  $refreshCommand.CommandText=(@{refresh=@{type='full';objects=@(@{database=$db})}} | ConvertTo-Json -Depth 5 -Compress)
  [void]$refreshCommand.ExecuteNonQuery()
 }
 $command=$connection.CreateCommand()
 $command.CommandText='EVALUATE ROW("Revenue", [Revenue], "Rows", COUNTROWS(Sales))'
 $reader=$command.ExecuteReader();$rows=@()
 while($reader.Read()){$rows+=@{Revenue=$reader.GetValue(0);Rows=$reader.GetValue(1)}}
 $reader.Close()
 $command.CommandText='SELECT [Name] FROM $SYSTEM.TMSCHEMA_MEASURES'
 $reader=$command.ExecuteReader();$measures=@();while($reader.Read()){$measures+=$reader.GetString(0)};$reader.Close()
 $errors=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.Name -like '*. Visual error:*'} | ForEach-Object {$_.Current.Name} | Select-Object -Unique)
 if($rows.Count -ne 1 -or $rows[0].Revenue -ne 1 -or $rows[0].Rows -ne 1){throw 'Unexpected native DAX results'}
 if($errors.Count){throw ('Power BI visual errors: '+($errors -join '; '))}
 if($ExpectedMissingMeasure -and $ExpectedMissingMeasure -in $measures){throw 'Deleted measure remains in native model'}
 $result=@{powerbi_process=$OwnedProcessId;query_rows=$rows;measures=$measures;visual_errors=$errors}
 $json=$result | ConvertTo-Json -Depth 6
 if($OutputPath){$json | Set-Content -LiteralPath $OutputPath -Encoding utf8}
 $json
}finally{$connection.Close()}

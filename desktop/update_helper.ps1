param(
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$MarkerPath,
    [Parameter(Mandatory = $true)][string]$LogPath,
    [string]$ReadyPath = '',
    [ValidateRange(1, 120)][int]$WaitTimeoutSeconds = 45,
    [ValidateRange(1, 30)][int]$MaxSwapAttempts = 12,
    [ValidateRange(1, 600)][int]$HealthTimeoutSeconds = 120,
    [switch]$Headless,
    [switch]$SkipRelaunch,
    [switch]$TestFailAfterBackup,
    [switch]$TestFailAfterActivation,
    [switch]$TestHealthConfirmation,
    [switch]$TestConfirmHealth
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

function Write-UpdateLog([string]$Message) {
    try {
        $stamp = [DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss.fff')
        Add-Content -LiteralPath $LogPath -Value "$stamp  $Message" -Encoding UTF8
    } catch { }
}

function Start-AlphaPOS([string]$InstallDirectory) {
    $executable = Join-Path $InstallDirectory 'AlphaPOS.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "AlphaPOS.exe is missing from $InstallDirectory"
    }
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $executable
    $info.WorkingDirectory = $InstallDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    return [Diagnostics.Process]::Start($info)
}

function Move-Bounded([string]$From, [string]$To) {
    $lastError = $null
    for ($attempt = 1; $attempt -le $MaxSwapAttempts; $attempt += 1) {
        try {
            Move-Item -LiteralPath $From -Destination $To
            return
        } catch {
            $lastError = $_.Exception
            if ($attempt -lt $MaxSwapAttempts) { Start-Sleep -Milliseconds 250 }
        }
    }
    throw "Move failed after $MaxSwapAttempts bounded attempts: $($lastError.Message)"
}

function Remove-Bounded([string]$Target) {
    $lastError = $null
    for ($attempt = 1; $attempt -le $MaxSwapAttempts; $attempt += 1) {
        try {
            if (Test-Path -LiteralPath $Target) {
                Remove-Item -LiteralPath $Target -Recurse -Force
            }
            return
        } catch {
            $lastError = $_.Exception
            if ($attempt -lt $MaxSwapAttempts) { Start-Sleep -Milliseconds 250 }
        }
    }
    throw "Removal failed after $MaxSwapAttempts bounded attempts: $($lastError.Message)"
}

function Stop-AlphaPOSProcess([Diagnostics.Process]$Process) {
    if ($null -eq $Process) { return }
    try {
        $Process.Refresh()
        if ($Process.HasExited) { return }
        # First ask the GUI to close normally so Django/Postgres release their
        # resources. Give that path time before forcing the entire child tree.
        [void]$Process.CloseMainWindow()
        if ($Process.WaitForExit(8000)) { return }
    } catch { }
    try {
        # Windows PowerShell 5's Process.Kill has no process-tree overload.
        # taskkill /T also terminates embedded Postgres before rollback tries
        # to remove the new bundle directory.
        $taskkill = Join-Path $env:SystemRoot 'System32\taskkill.exe'
        & $taskkill /PID $Process.Id /T /F *> $null
        try { [void]$Process.WaitForExit(5000) } catch { }
    } catch {
        Write-UpdateLog "Could not stop failed new process: $($_.Exception.Message)"
    }
}

# Headless mode runs the exact directory-swap contract against disposable
# folders. It exists for release smoke tests; the production launcher never
# passes these switches. TestFailAfterBackup proves rollback without risking a
# real installation.
if ($Headless) {
    $backup = Join-Path (Split-Path -Parent $Destination) ('.' + (Split-Path -Leaf $Destination) + '.previous')
    $backedUpCurrent = $false
    try {
        $pendingVersion = if (Test-Path -LiteralPath $MarkerPath) {
            (Get-Content -LiteralPath $MarkerPath -Raw).Trim()
        } else { '' }
        if ($pendingVersion -ne $Version) {
            throw "Pending update marker does not match version $Version."
        }
        $deadline = [DateTime]::UtcNow.AddSeconds($WaitTimeoutSeconds)
        while ($null -ne (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Parent did not exit within $WaitTimeoutSeconds seconds."
            }
            Start-Sleep -Milliseconds 100
        }
        if (Test-Path -LiteralPath $backup) { Remove-Bounded $backup }
        Move-Bounded $Destination $backup
        $backedUpCurrent = $true
        if ($TestFailAfterBackup) { throw 'Simulated activation failure after backup.' }
        Move-Bounded $Source $Destination
        if ($TestFailAfterActivation) { throw 'Simulated failure after new-version activation.' }
        Get-ChildItem -LiteralPath $backup -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'unins*' } |
            Copy-Item -Destination $Destination -Force
        if ($TestHealthConfirmation) {
            # Simulate the production contract without executing an arbitrary
            # fixture binary: the healthy new app confirms by deleting exactly
            # this marker after its backend binds.
            if ($TestConfirmHealth) {
                Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue
            }
            $healthDeadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
            while (Test-Path -LiteralPath $MarkerPath) {
                if ([DateTime]::UtcNow -ge $healthDeadline) {
                    throw "New version did not confirm backend health within $HealthTimeoutSeconds seconds."
                }
                Start-Sleep -Milliseconds 50
            }
        }
        if (-not $SkipRelaunch) { Start-AlphaPOS $Destination }
        Write-UpdateLog "Headless simulation installed version $Version successfully."
        exit 0
    } catch {
        Write-UpdateLog "Headless simulation failed: $($_.Exception.Message)"
        try {
            if ($backedUpCurrent -and (Test-Path -LiteralPath $backup)) {
                if (Test-Path -LiteralPath $Destination) {
                    Remove-Bounded $Destination
                }
                Move-Bounded $backup $Destination
                $backedUpCurrent = $false
            }
        } catch {
            Write-UpdateLog "Headless rollback failed: $($_.Exception.Message)"
        }
        try { Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue } catch { }
        [Console]::Error.WriteLine($_.Exception.Message)
        exit 1
    }
}

[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Alpha POS Update" Width="480" Height="300"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        ShowInTaskbar="True" Topmost="True">
  <Border CornerRadius="22" BorderThickness="1" BorderBrush="#25374A" Background="#101923">
    <Border.Effect>
      <DropShadowEffect Color="#000000" BlurRadius="34" ShadowDepth="10" Opacity="0.55" />
    </Border.Effect>
    <Grid>
      <Grid.Background>
        <LinearGradientBrush StartPoint="0,0" EndPoint="1,1">
          <GradientStop Color="#172838" Offset="0" />
          <GradientStop Color="#101923" Offset="0.58" />
          <GradientStop Color="#0C121A" Offset="1" />
        </LinearGradientBrush>
      </Grid.Background>
      <Ellipse Width="220" Height="220" Fill="#15355D70" HorizontalAlignment="Right"
               VerticalAlignment="Top" Margin="0,-120,-90,0" IsHitTestVisible="False" />
      <Grid Margin="32,28,32,26">
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto" />
          <RowDefinition Height="*" />
          <RowDefinition Height="Auto" />
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0" Orientation="Horizontal">
          <Border Width="45" Height="45" CornerRadius="13" Background="#2ED3A3">
            <TextBlock Text="A" Foreground="#07130F" FontFamily="Segoe UI Semibold"
                       FontSize="22" HorizontalAlignment="Center" VerticalAlignment="Center" />
          </Border>
          <StackPanel Margin="14,1,0,0">
            <TextBlock Text="ALPHA POS" Foreground="#F3F7FA" FontFamily="Segoe UI Semibold"
                       FontSize="15" />
            <TextBlock Text="SECURE UPDATE" Foreground="#7F94A7" FontFamily="Segoe UI"
                       FontSize="10" Margin="0,4,0,0" />
          </StackPanel>
        </StackPanel>

        <StackPanel Grid.Row="1" VerticalAlignment="Center" Margin="0,13,0,8">
          <TextBlock x:Name="Heading" Text="Installing your update" Foreground="#F4F7FA"
                     FontFamily="Segoe UI Semibold" FontSize="23" />
          <TextBlock x:Name="Status" Text="Closing Alpha POS safely…" Foreground="#9CAFC0"
                     FontFamily="Segoe UI" FontSize="13" Margin="0,8,0,18" TextWrapping="Wrap" />
          <ProgressBar x:Name="Progress" Height="7" Minimum="0" Maximum="100" Value="6"
                       IsIndeterminate="True" Foreground="#2ED3A3" Background="#243442"
                       BorderThickness="0" />
          <Grid Margin="0,9,0,0">
            <TextBlock x:Name="Detail" Text="Verified and ready" Foreground="#71879A"
                       FontFamily="Segoe UI" FontSize="11" HorizontalAlignment="Left" />
            <TextBlock x:Name="Percent" Text="" Foreground="#71879A"
                       FontFamily="Consolas" FontSize="11" HorizontalAlignment="Right" />
          </Grid>
        </StackPanel>

        <Button x:Name="Action" Grid.Row="2" Content="Open Alpha POS" Visibility="Collapsed"
                Height="38" Padding="18,0" HorizontalAlignment="Left" Foreground="#07130F"
                Background="#2ED3A3" BorderThickness="0" FontFamily="Segoe UI Semibold"
                FontSize="12" Cursor="Hand" />
      </Grid>
    </Grid>
  </Border>
</Window>
'@

$reader = [System.Xml.XmlNodeReader]::new($xaml)
$window = [Windows.Markup.XamlReader]::Load($reader)
$heading = $window.FindName('Heading')
$status = $window.FindName('Status')
$progress = $window.FindName('Progress')
$detail = $window.FindName('Detail')
$percent = $window.FindName('Percent')
$action = $window.FindName('Action')

$script:allowClose = $false
$script:phase = 'wait'
$script:waitTicks = 0
$script:swapAttempts = 0
$script:backup = Join-Path (Split-Path -Parent $Destination) ('.' + (Split-Path -Leaf $Destination) + '.previous')
$script:backedUpCurrent = $false
$script:launchedProcess = $null
$script:healthTicks = 0
$script:actionMode = 'open'
$script:markerChecked = $false
$script:successCloser = $null
$script:timer = [Windows.Threading.DispatcherTimer]::new()
$script:timer.Interval = [TimeSpan]::FromMilliseconds(250)

function Set-Progress([int]$Value, [string]$Message, [string]$Small) {
    $progress.IsIndeterminate = $false
    $progress.Value = $Value
    $status.Text = $Message
    $detail.Text = $Small
    $percent.Text = "$Value%"
}

function Restore-PreviousInstall {
    try {
        if ($script:backedUpCurrent) {
            if (-not (Test-Path -LiteralPath $script:backup -PathType Container)) {
                Write-UpdateLog 'Rollback source is missing; refusing to call the new install recovered.'
                return $false
            }
            if (Test-Path -LiteralPath $Destination) {
                Remove-Bounded $Destination
            }
            Move-Bounded $script:backup $Destination
            $script:backedUpCurrent = $false
            Write-UpdateLog 'Previous install restored after update failure.'
        }
        return (Test-Path -LiteralPath (Join-Path $Destination 'AlphaPOS.exe') -PathType Leaf)
    } catch {
        Write-UpdateLog "Rollback failed: $($_.Exception.Message)"
        return $false
    }
}

function Stop-WithError([string]$Message) {
    Write-UpdateLog "FAILED: $Message"
    $script:timer.Stop()
    $restored = Restore-PreviousInstall
    try { Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue } catch { }
    $heading.Text = 'Update could not finish'
    $status.Text = $Message
    $detail.Text = if ($restored) { 'Your previous installation was kept.' } else { 'Automatic recovery failed. Please run the Alpha POS Setup installer.' }
    $percent.Text = ''
    $progress.IsIndeterminate = $false
    $progress.Value = 0
    $progress.Foreground = '#F07B68'
    if ($restored) {
        $script:actionMode = 'open'
        $action.Content = 'Open Alpha POS'
        $action.Visibility = 'Visible'
    } else {
        $script:actionMode = 'close'
        $action.Content = 'Close'
        $action.Visibility = 'Visible'
    }
    $script:allowClose = $true
}

function Rollback-UnhealthyVersion([string]$Message) {
    Write-UpdateLog "NEW VERSION UNHEALTHY: $Message"
    $script:timer.Stop()
    Stop-AlphaPOSProcess $script:launchedProcess
    $restored = Restore-PreviousInstall
    try { Remove-Item -LiteralPath $MarkerPath -Force -ErrorAction SilentlyContinue } catch { }
    $heading.Text = if ($restored) { 'Update rolled back safely' } else { 'Automatic recovery failed' }
    $status.Text = $Message
    $percent.Text = ''
    $progress.IsIndeterminate = $false
    $progress.Value = 0
    $progress.Foreground = '#F07B68'
    if ($restored) {
        try {
            $script:launchedProcess = Start-AlphaPOS $Destination
            $detail.Text = 'The previous version has been reopened.'
            Write-UpdateLog 'Previous version relaunched after failed health confirmation.'
        } catch {
            $detail.Text = 'The previous version was restored. Use the button to open it.'
            Write-UpdateLog "Previous-version relaunch failed: $($_.Exception.Message)"
            $script:actionMode = 'open'
            $action.Content = 'Open Alpha POS'
            $action.Visibility = 'Visible'
            $script:allowClose = $true
            return
        }
        $script:actionMode = 'close'
        $action.Content = 'Close'
        $action.Visibility = 'Visible'
    } else {
        $detail.Text = 'Run the Alpha POS Setup installer to repair this installation.'
        $script:actionMode = 'close'
        $action.Content = 'Close'
        $action.Visibility = 'Visible'
    }
    $script:allowClose = $true
}

$action.Add_Click({
    if ($script:actionMode -eq 'open') {
        try { $script:launchedProcess = Start-AlphaPOS $Destination } catch { Write-UpdateLog "Fallback launch failed: $($_.Exception.Message)" }
    }
    $window.Close()
})

$window.Add_Closing({
    param($sender, $eventArgs)
    if (-not $script:allowClose) { $eventArgs.Cancel = $true }
})

$script:timer.Add_Tick({
    try {
        switch ($script:phase) {
            'wait' {
                if (-not $script:markerChecked) {
                    $pendingVersion = if (Test-Path -LiteralPath $MarkerPath) {
                        (Get-Content -LiteralPath $MarkerPath -Raw).Trim()
                    } else { '' }
                    if ($pendingVersion -ne $Version) {
                        Stop-WithError "Pending update marker does not match version $Version."
                        return
                    }
                    $script:markerChecked = $true
                }
                $script:waitTicks += 1
                $running = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
                if ($null -eq $running) {
                    Write-UpdateLog 'Alpha POS exited; beginning atomic swap.'
                    $script:phase = 'remove-old-backup'
                    $progress.IsIndeterminate = $false
                    Set-Progress 18 'Installing the verified update…' 'Preparing rollback protection'
                } elseif ($script:waitTicks -ge ($WaitTimeoutSeconds * 4)) {
                    Stop-WithError "Alpha POS did not close within $WaitTimeoutSeconds seconds. Please reopen it and try again."
                } else {
                    $detail.Text = 'Waiting for open files to close'
                }
            }
            'remove-old-backup' {
                if (Test-Path -LiteralPath $script:backup) {
                    Remove-Bounded $script:backup
                }
                $script:phase = 'backup-current'
                $script:swapAttempts = 0
                Set-Progress 30 'Installing the verified update…' 'Saving the current version'
            }
            'backup-current' {
                try {
                    if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
                        throw "The current install directory is missing."
                    }
                    Move-Item -LiteralPath $Destination -Destination $script:backup
                    $script:backedUpCurrent = $true
                    $script:phase = 'activate-new'
                    $script:swapAttempts = 0
                    Set-Progress 54 'Installing the verified update…' ('Activating version ' + $Version)
                } catch {
                    $script:swapAttempts += 1
                    if ($script:swapAttempts -ge $MaxSwapAttempts) {
                        Stop-WithError "Windows kept an application file open after $MaxSwapAttempts bounded attempts."
                    }
                }
            }
            'activate-new' {
                try {
                    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
                        throw 'The verified staging directory is missing.'
                    }
                    Move-Item -LiteralPath $Source -Destination $Destination
                    $script:phase = 'preserve-installer'
                    Set-Progress 78 'Finishing up…' 'Preserving installer support'
                } catch {
                    $script:swapAttempts += 1
                    if ($script:swapAttempts -ge $MaxSwapAttempts) {
                        Stop-WithError "The verified update could not be activated after $MaxSwapAttempts bounded attempts."
                    }
                }
            }
            'preserve-installer' {
                Get-ChildItem -LiteralPath $script:backup -File -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -like 'unins*' } |
                    Copy-Item -Destination $Destination -Force
                $script:phase = 'launch'
                Set-Progress 94 'Update installed' 'Opening Alpha POS'
            }
            'launch' {
                $script:launchedProcess = Start-AlphaPOS $Destination
                $script:phase = 'verify-health'
                $script:healthTicks = 0
                Set-Progress 97 'Verifying the new version…' 'Waiting for the POS backend to become ready'
                Write-UpdateLog "Version $Version launched; waiting up to $HealthTimeoutSeconds seconds for backend confirmation."
            }
            'verify-health' {
                $script:healthTicks += 1
                if (-not (Test-Path -LiteralPath $MarkerPath)) {
                    Write-UpdateLog "Version $Version confirmed backend health."
                    Set-Progress 100 'You’re all set' ('Alpha POS ' + $Version + ' is ready')
                    $script:timer.Stop()
                    $script:allowClose = $true
                    $script:successCloser = [Windows.Threading.DispatcherTimer]::new()
                    $script:successCloser.Interval = [TimeSpan]::FromMilliseconds(1100)
                    $script:successCloser.Add_Tick({
                        $script:successCloser.Stop()
                        $window.Close()
                    })
                    $script:successCloser.Start()
                    return
                }

                $exited = $false
                try {
                    $script:launchedProcess.Refresh()
                    $exited = $script:launchedProcess.HasExited
                } catch { $exited = $true }
                if ($exited) {
                    Rollback-UnhealthyVersion 'The new Alpha POS process closed before its backend became ready.'
                } elseif ($script:healthTicks -ge ($HealthTimeoutSeconds * 4)) {
                    Rollback-UnhealthyVersion "The new POS backend did not become ready within $HealthTimeoutSeconds seconds."
                } else {
                    $detail.Text = 'Checking database, migrations and local server'
                }
            }
        }
    } catch {
        Stop-WithError $_.Exception.Message
    }
})

Write-UpdateLog "Helper started for version $Version (parent PID $ParentPid)."
$window.Add_ContentRendered({
    try {
        $pendingVersion = if (Test-Path -LiteralPath $MarkerPath) {
            (Get-Content -LiteralPath $MarkerPath -Raw).Trim()
        } else { '' }
        if ($pendingVersion -ne $Version) {
            throw "Pending update marker does not match version $Version."
        }
        $script:markerChecked = $true
        if ($ReadyPath) {
            Set-Content -LiteralPath $ReadyPath -Value 'ready' -Encoding ASCII -NoNewline
        }
        # Only now may the parent close the live POS: the visible helper and its
        # dispatcher/timer are known to be operational.
        $script:timer.Start()
    } catch {
        Write-UpdateLog "Helper readiness handshake failed: $($_.Exception.Message)"
        $script:allowClose = $true
        $window.Close()
    }
})
[void]$window.ShowDialog()

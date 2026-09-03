# KooviLight - the quiet way Koovi tells you which session needs you, on Windows.
#
# Draws a pulsing coloured frame along the edges of every screen, plus the waiting
# session named in a corner. Click-through, always on top, no taskbar button. It only
# reads the JSON file koovi.py writes; it never decides anything itself. Each item
# carries its own end time: a flash of a few seconds, then it is gone. Hides when
# nothing is left and quits after being idle for a while. One copy runs at a time.
#
# Run:  powershell -ExecutionPolicy Bypass -File KooviLight.ps1 <path to light.json>
#
# This is the Windows half of light/KooviLight.swift. It has not been tested on a real
# Windows machine yet: if it misbehaves, please open an issue.

param([string]$JsonPath = "$env:USERPROFILE\.koovi\light.json")

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

# one helper at a time: the second copy simply leaves
$mutex = New-Object System.Threading.Mutex($false, "Local\KooviLight")
if (-not $mutex.WaitOne(0)) { exit 0 }

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class KooviWin {
  [DllImport("user32.dll", SetLastError = true)]
  public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
  [DllImport("user32.dll")]
  public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
}
"@

$GWL_EXSTYLE = -20
$CLICK_THROUGH = 0x80000 -bor 0x20 -bor 0x80 -bor 0x8000000  # layered, transparent, tool window, no activate
$IDLE_QUIT_SECONDS = 90

function ConvertFrom-Hex([string]$hex) {
    $h = $hex.Trim().TrimStart('#')
    if ($h.Length -ne 6) { return [System.Drawing.Color]::FromArgb(255, 59, 48) }
    try {
        return [System.Drawing.Color]::FromArgb(
            [Convert]::ToInt32($h.Substring(0, 2), 16),
            [Convert]::ToInt32($h.Substring(2, 2), 16),
            [Convert]::ToInt32($h.Substring(4, 2), 16))
    } catch { return [System.Drawing.Color]::FromArgb(255, 59, 48) }
}

$state = [pscustomobject]@{
    Items      = @()
    Pulse      = $true
    Corner     = 'top-right'
    Bright     = $true
    EmptySince = [DateTime]::UtcNow
    LastRaw    = ''
}

$forms = @()
foreach ($screen in [System.Windows.Forms.Screen]::AllScreens) {
    $form = New-Object System.Windows.Forms.Form
    $form.FormBorderStyle = 'None'
    $form.ShowInTaskbar = $false
    $form.TopMost = $true
    $form.StartPosition = 'Manual'
    $form.Bounds = $screen.Bounds
    $form.BackColor = [System.Drawing.Color]::FromArgb(1, 1, 1)
    $form.TransparencyKey = $form.BackColor
    $form.Tag = $screen
    $form.Add_Shown({
        $style = [KooviWin]::GetWindowLong($this.Handle, $GWL_EXSTYLE)
        [void][KooviWin]::SetWindowLong($this.Handle, $GWL_EXSTYLE, $style -bor $CLICK_THROUGH)
    })
    $form.Add_Paint({
        param($sender, $e)
        if ($state.Items.Count -eq 0) { return }
        $g = $e.Graphics
        $g.SmoothingMode = 'AntiAlias'
        $g.TextRenderingHint = 'ClearTypeGridFit'
        $tint = ConvertFrom-Hex $state.Items[0].color
        $alpha = if ($state.Pulse -and -not $state.Bright) { 70 } else { 255 }
        $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb($alpha, $tint), 14)
        $edge = $sender.ClientRectangle
        $g.DrawRectangle($pen, 7, 7, $edge.Width - 14, $edge.Height - 14)
        $pen.Dispose()

        $bold = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
        $plain = New-Object System.Drawing.Font('Segoe UI', 13)
        $lines = @()
        foreach ($item in $state.Items) { $lines += "$([char]0x25CF) $($item.label)   $($item.text)" }
        $text = $lines -join "`n"
        $size = $g.MeasureString($text, $bold)
        $boxWidth = [Math]::Ceiling($size.Width) + 36
        $boxHeight = [Math]::Ceiling($size.Height) + 24
        $margin = 26
        switch ($state.Corner) {
            'top-left'     { $x = $margin; $y = $margin }
            'bottom-left'  { $x = $margin; $y = $edge.Height - $margin - $boxHeight }
            'bottom-right' { $x = $edge.Width - $margin - $boxWidth; $y = $edge.Height - $margin - $boxHeight }
            default        { $x = $edge.Width - $margin - $boxWidth; $y = $margin }
        }
        $box = New-Object System.Drawing.Rectangle($x, $y, $boxWidth, $boxHeight)
        $fill = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(210, 13, 13, 13))
        $g.FillRectangle($fill, $box)
        $border = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(150, $tint), 1)
        $g.DrawRectangle($border, $box)
        $white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
        $g.DrawString($text, $plain, $white, ($x + 18), ($y + 12))
        $fill.Dispose(); $border.Dispose(); $white.Dispose(); $bold.Dispose(); $plain.Dispose()
    })
    $forms += $form
}

function Update-Light {
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
    $raw = ''
    try { $raw = [IO.File]::ReadAllText($JsonPath) } catch { $raw = '' }

    $expired = $false
    foreach ($item in $state.Items) { if ($item.until -gt 0 -and $item.until -le $now) { $expired = $true } }
    if ($raw -ne $state.LastRaw -or $expired) {
        $state.LastRaw = $raw
        $items = @()
        if ($raw) {
            try {
                $data = $raw | ConvertFrom-Json
                $state.Pulse = if ($null -ne $data.pulse) { [bool]$data.pulse } else { $true }
                if ($data.corner) { $state.Corner = [string]$data.corner }
                foreach ($item in @($data.items)) {
                    if ($null -eq $item) { continue }
                    $until = if ($item.until) { [double]$item.until } else { 0 }
                    if ($until -gt 0 -and $until -le $now) { continue }   # its few seconds are over
                    $items += $item
                }
            } catch { $items = @() }
        }
        $state.Items = $items
        foreach ($form in $forms) {
            if ($items.Count -eq 0) { $form.Hide() }
            else { if (-not $form.Visible) { $form.Show() }; $form.Invalidate() }
        }
        if ($items.Count -eq 0) {
            if ($null -eq $state.EmptySince) { $state.EmptySince = [DateTime]::UtcNow }
        } else {
            $state.EmptySince = $null
        }
    }

    if ($state.Items.Count -gt 0 -and $state.Pulse) {
        $state.Bright = -not $state.Bright
        foreach ($form in $forms) { $form.Invalidate() }
    }

    if ($null -ne $state.EmptySince -and ([DateTime]::UtcNow - $state.EmptySince).TotalSeconds -gt $IDLE_QUIT_SECONDS) {
        foreach ($form in $forms) { $form.Close() }
        [System.Windows.Forms.Application]::Exit()
    }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 375
$timer.Add_Tick({ Update-Light })
$timer.Start()

try {
    [System.Windows.Forms.Application]::Run()
} finally {
    $timer.Stop()
    $mutex.ReleaseMutex()
}

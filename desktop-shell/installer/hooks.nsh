; Alpha POS NSIS installer hooks (Tauri 2).
;
; - Installs into the 1.0.x location %LOCALAPPDATA%\Programs\AlphaPOS so an
;   upgrade replaces the old Inno Setup install in place instead of creating a
;   second copy that would fight over the same database and port.
; - Stops whatever runs from the install folder (old launcher, its orphaned
;   postgres.exe, the new shell and backend) before files are replaced.
; - Removes the old Inno Setup registration and runtime after a successful copy.
; - Never touches %LOCALAPPDATA%\AlphaPOS (database, settings, logs).

!define ALPHAPOS_LEGACY_DIR "$LOCALAPPDATA\Programs\AlphaPOS"
!define ALPHAPOS_DATA_DIR "$LOCALAPPDATA\AlphaPOS"
!define ALPHAPOS_INNO_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F3A1C2E-7B44-4E2D-9A1F-1A2B3C4D5E6F}_is1"
!define ALPHAPOS_FIREWALL_RULE "Alpha POS (LAN)"

; Terminate processes whose executable lives under $INSTDIR. $0 = name filter
; for Get-Process ("*" for all).
!macro ALPHAPOS_KILL_UNDER_INSTDIR NAMES
  nsExec::Exec `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$$root = [IO.Path]::GetFullPath('$INSTDIR').TrimEnd('\') + '\'; Get-Process -Name ${NAMES} -ErrorAction SilentlyContinue | Where-Object { $$_.Id -ne $$PID -and $$_.Path -and $$_.Path.StartsWith($$root, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"`
  Pop $0
  ; PowerShell can be blocked by policy or antivirus: fall back to taskkill
  ; for the app's own executables so files are never replaced under them.
  ${If} $0 != 0
    nsExec::Exec `taskkill.exe /F /T /IM AlphaPOS.exe /IM AlphaPOSBackend.exe`
    Pop $0
  ${EndIf}
!macroend

; Stop embedded PostgreSQL cleanly with whichever bundled pg_ctl exists.
!macro ALPHAPOS_STOP_POSTGRES
  ${If} ${FileExists} "${ALPHAPOS_DATA_DIR}\pgdata\postmaster.pid"
    ${If} ${FileExists} "$INSTDIR\backend\_internal\pgsql\bin\pg_ctl.exe"
      nsExec::Exec `"$INSTDIR\backend\_internal\pgsql\bin\pg_ctl.exe" stop -D "${ALPHAPOS_DATA_DIR}\pgdata" -m fast -w -t 30`
      Pop $0
    ${ElseIf} ${FileExists} "$INSTDIR\_internal\pgsql\bin\pg_ctl.exe"
      nsExec::Exec `"$INSTDIR\_internal\pgsql\bin\pg_ctl.exe" stop -D "${ALPHAPOS_DATA_DIR}\pgdata" -m fast -w -t 30`
      Pop $0
    ${EndIf}
  ${EndIf}
!macroend

!macro ALPHAPOS_STOP_EVERYTHING
  DetailPrint "Stopping Alpha POS…"
  ; A clean database stop first: the 1.1 shell's job object would otherwise
  ; take postgres.exe down hard with it and the next start runs crash recovery.
  !insertmacro ALPHAPOS_STOP_POSTGRES
  ; Then the launchers, so no supervisor can restart the database...
  !insertmacro ALPHAPOS_KILL_UNDER_INSTDIR "AlphaPOS,AlphaPOSBackend"
  ; ...and stop it again in case a 1.0.x supervisor did in the meantime.
  !insertmacro ALPHAPOS_STOP_POSTGRES
  ; Anything left from the install folder (postgres, ssh, helpers).
  !insertmacro ALPHAPOS_KILL_UNDER_INSTDIR "*"
!macroend

!macro NSIS_HOOK_PREINSTALL
  ; Tauri's per-user default is %LOCALAPPDATA%\Alpha POS; keep the 1.0.x folder.
  ${If} $INSTDIR == "$LOCALAPPDATA\${PRODUCTNAME}"
    StrCpy $INSTDIR "${ALPHAPOS_LEGACY_DIR}"
    SetOutPath $INSTDIR
    ; The template already created the default folder; remove it if empty.
    RMDir "$LOCALAPPDATA\${PRODUCTNAME}"
  ${EndIf}

  !insertmacro ALPHAPOS_STOP_EVERYTHING

  ; A fresh backend copy: stale loose migration files must never survive.
  RMDir /r "$INSTDIR\backend"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; --- Retire the 1.0.x Inno Setup install that lived in this folder ---
  ReadRegStr $1 HKCU "${ALPHAPOS_INNO_KEY}" "Inno Setup: App Path"
  ${If} $1 == $INSTDIR
    DeleteRegKey HKCU "${ALPHAPOS_INNO_KEY}"
  ${EndIf}
  Delete "$INSTDIR\unins000.exe"
  Delete "$INSTDIR\unins000.dat"
  Delete "$INSTDIR\unins000.msg"
  ; Old PyInstaller launcher runtime (the new backend lives in backend\_internal).
  RMDir /r "$INSTDIR\_internal"
  Delete "$SMPROGRAMS\Alpha POS\Uninstall Alpha POS.lnk"

  ; --- Start with Windows so the POS is up after every reboot ---
  CreateDirectory "$SMSTARTUP"
  CreateShortCut "$SMSTARTUP\Alpha POS.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"

  ; --- LAN access for waiter tablets / terminals (best effort without admin) ---
  nsExec::Exec `netsh advfirewall firewall delete rule name="${ALPHAPOS_FIREWALL_RULE}"`
  Pop $0
  nsExec::Exec `netsh advfirewall firewall add rule name="${ALPHAPOS_FIREWALL_RULE}" dir=in action=allow protocol=TCP localport=8000 profile=any`
  Pop $0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro ALPHAPOS_STOP_EVERYTHING
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$SMSTARTUP\Alpha POS.lnk"
  ; During an update the new installer recreates the rule and shortcut.
  ${IfNot} $UpdateMode = 1
    nsExec::Exec `netsh advfirewall firewall delete rule name="${ALPHAPOS_FIREWALL_RULE}"`
    Pop $0
  ${EndIf}
!macroend

; Atlas Chat installs to F: when the PC has an F: drive (2026-11-09 rule), and to
; %LOCALAPPDATA%\atlas-chat\app when it has none (so it also installs on a laptop).
; Included by Tauri's NSIS template through bundle.windows.nsis.installerHooks.
; Folder names are lower case with no spaces on purpose (llama-swap command lines).

!define ATLAS_F_INSTALL_DIR "F:\APP-DEV\projects\atlas-chat\app"
!define ATLAS_F_ONLY_MSG "Atlas Chat installs on the F: drive when this PC has one."

; Runs after .onInit, so it also replaces an old C: location from the registry.
!define MUI_CUSTOMFUNCTION_GUIINIT AtlasForceInstallDirOnF
Function AtlasForceInstallDirOnF
  IfFileExists "F:\*.*" has_f no_f
  has_f:
    StrCpy $0 $INSTDIR 3
    StrCmp $0 "F:\" f_other 0
    StrCpy $INSTDIR "${ATLAS_F_INSTALL_DIR}"
    Goto done
  f_other:
    ; An upgrade reads the old install path from the registry. The old nested folder
    ; "...\Atlas Chat" (has a space) moves to the new default. Any other F: folder is kept.
    StrCpy $0 $INSTDIR 11 -11
    StrCmp $0 "\Atlas Chat" 0 done
    StrCpy $INSTDIR "${ATLAS_F_INSTALL_DIR}"
    Goto done
  no_f:
    ; No F: drive: replace only the template default, keep a folder the user chose.
    StrCmp $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}" 0 done
    StrCpy $INSTDIR "$LOCALAPPDATA\atlas-chat\app"
  done:
FunctionEnd

; With an F: drive, Next stays disabled on the folder page for anything off F:.
Function .onVerifyInstDir
  IfFileExists "F:\*.*" 0 ok
  StrCpy $0 $INSTDIR 3
  StrCmp $0 "F:\" ok 0
    Abort
  ok:
FunctionEnd

; Last check: covers silent installs and /D=, which skip the folder page.
!macro NSIS_HOOK_PREINSTALL
  IfFileExists "F:\*.*" 0 atlas_pre_ok
  StrCpy $0 $INSTDIR 3
  StrCmp $0 "F:\" atlas_pre_ok 0
    MessageBox MB_ICONSTOP|MB_OK "${ATLAS_F_ONLY_MSG}" /SD IDOK
    Quit
  atlas_pre_ok:
!macroend

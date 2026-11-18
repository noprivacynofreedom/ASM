; Atlas Chat installs to %LOCALAPPDATA%\atlas-chat\app on a new PC.
; An update keeps the folder of the old install: the template's RestorePreviousInstallLocation
; reads it from the registry before this runs, and this file then leaves it alone.
; Included by Tauri's NSIS template through bundle.windows.nsis.installerHooks.
; Folder names are lower case with no spaces on purpose (llama-swap command lines).

!define ATLAS_DEFAULT_INSTALL_DIR "$LOCALAPPDATA\atlas-chat\app"

; Replace only the template default ($LOCALAPPDATA\Atlas Chat, it has a space).
; Keep a folder from an old install or one the user chose.
!macro ATLAS_FIX_DEFAULT_INSTDIR
  StrCmp $INSTDIR "$LOCALAPPDATA\${PRODUCTNAME}" 0 +2
    StrCpy $INSTDIR "${ATLAS_DEFAULT_INSTALL_DIR}"
!macroend

; Runs after .onInit, before the folder page.
!define MUI_CUSTOMFUNCTION_GUIINIT AtlasSetDefaultInstallDir
Function AtlasSetDefaultInstallDir
  !insertmacro ATLAS_FIX_DEFAULT_INSTDIR
FunctionEnd

; Silent installs skip the pages, so check the default once more here.
!macro NSIS_HOOK_PREINSTALL
  !insertmacro ATLAS_FIX_DEFAULT_INSTDIR
!macroend

; Game files are changed only after the normal installer confirmation.
; No network dependencies, hidden elevation, guessed silent game path or fake success.
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!ifndef BUILD_UNINSTALLER
Var FA_GamePath
Var FA_GameFolder
Var FA_GameControl
Var FA_Page
Var FA_Browse
Var FA_Parameters
Var FA_ArgumentPath
Var FA_ResultFile
Var FA_ResultCode
Var FA_ExitCode
Var FA_Message
Var FA_SilentFlag

!macro customInit
  ReadRegStr $FA_GamePath HKCU "Software\FootballAssistant\Readers" "GamePath"
  ${GetParameters} $FA_Parameters
  ClearErrors
  ${GetOptions} "$FA_Parameters" "/FMPath=" $FA_ArgumentPath
  ${IfNot} ${Errors}
    StrCpy $FA_GamePath "$FA_ArgumentPath"
  ${EndIf}
!macroend

!macro customPageAfterChangeDir
  Page custom FA_SelectGamePage FA_SelectGameLeave
!macroend

Function FA_SelectGamePage
  ${If} ${Silent}
    Abort
  ${EndIf}
  StrCpy $FA_GameFolder "$FA_GamePath"
  ${GetFileName} "$FA_GamePath" $0
  ${If} $0 == "fm.exe"
    ${GetParent} "$FA_GamePath" $FA_GameFolder
  ${EndIf}
  nsDialogs::Create 1018
  Pop $FA_Page
  ${If} $FA_Page == error
    Abort
  ${EndIf}
  !insertmacro MUI_HEADER_TEXT "选择游戏目录" "安装后自动配置读取，无需再到设置安装组件"
  ${NSD_CreateLabel} 0 0 100% 42u "请选择包含 fm.exe 的 Football Manager 27 目录。点击安装即确认部署包内读取组件，并在首次启动游戏时离线生成互操作文件。请先退出游戏。"
  Pop $0
  ${NSD_CreateDirRequest} 0 48u 82% 13u "$FA_GameFolder"
  Pop $FA_GameControl
  ${NSD_CreateBrowseButton} 84% 47u 16% 15u "浏览…"
  Pop $FA_Browse
  ${NSD_OnClick} $FA_Browse FA_BrowseGame
  ${NSD_CreateLabel} 0 72u 100% 42u "已配置过游戏的更新可留空，继续沿用保存路径。未找到游戏不会报告安装完成；运行中的游戏、旧加载器或其他 Mod 冲突会明确提示，不会强制覆盖。"
  Pop $0
  nsDialogs::Show
FunctionEnd

Function FA_BrowseGame
  Pop $0
  ${NSD_GetText} $FA_GameControl $FA_GameFolder
  nsDialogs::SelectFolderDialog "选择包含 fm.exe 的游戏目录" "$FA_GameFolder"
  Pop $0
  ${If} $0 != error
    ${NSD_SetText} $FA_GameControl "$0"
  ${EndIf}
FunctionEnd

Function FA_SelectGameLeave
  ${NSD_GetText} $FA_GameControl $FA_GameFolder
  StrCpy $FA_GamePath ""
  ${If} $FA_GameFolder != ""
    IfFileExists "$FA_GameFolder\fm.exe" fa_game_path_valid
    MessageBox MB_OK|MB_ICONEXCLAMATION "所选目录没有 fm.exe，请选择正确游戏目录。"
    Abort
    fa_game_path_valid:
    StrCpy $FA_GamePath "$FA_GameFolder\fm.exe"
  ${EndIf}
FunctionEnd

!macro customInstall
  InitPluginsDir
  StrCpy $FA_ResultFile "$PLUGINSDIR\fa-readers-result.ini"
  Delete "$FA_ResultFile"
  StrCpy $FA_SilentFlag ""
  ${If} ${Silent}
    StrCpy $FA_SilentFlag "--silent"
  ${EndIf}
  DetailPrint "正在配置包内读取组件（不下载运行依赖）…"
  ClearErrors
  ExecWait '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" --fa-install-readers --game-path "$FA_GamePath" --result-file "$FA_ResultFile" $FA_SilentFlag' $FA_ExitCode
  ${If} ${Errors}
    StrCpy $FA_ExitCode 5
  ${EndIf}
  ReadINIStr $FA_ResultCode "$FA_ResultFile" "result" "code"
  ReadINIStr $FA_Message "$FA_ResultFile" "result" "message"
  ${If} $FA_ExitCode == 0
  ${AndIf} $FA_ResultCode != 0
    StrCpy $FA_ExitCode 5
  ${EndIf}
  ${If} $FA_ExitCode != 0
    ${If} $FA_Message == ""
      StrCpy $FA_Message "无法完成读取组件部署，请确认游戏已关闭、目录正确且当前用户有写入权限。"
    ${EndIf}
    DetailPrint "$FA_Message"
    ${IfNot} ${Silent}
      MessageBox MB_OK|MB_ICONSTOP "读取组件安装未完成。程序文件可能已写入，但不会报告开箱配置成功。$\r$\n$\r$\n$FA_Message$\r$\n$\r$\n请处理提示后重新运行安装器。"
    ${EndIf}
    SetErrorLevel $FA_ExitCode
    Quit
  ${EndIf}
  ReadINIStr $FA_GamePath "$FA_ResultFile" "result" "gamePath"
  WriteRegStr HKCU "Software\FootballAssistant\Readers" "GamePath" "$FA_GamePath"
  FileOpen $0 "$INSTDIR\installation.json" w
  FileWrite $0 '{"schema":1,"distribution":"nsis"}'
  FileClose $0
!macroend
!endif

!macro customUnInstall
  ; Keep user configuration and deployment journals for an explicit safe recovery.
  Delete "$INSTDIR\installation.json"
!macroend

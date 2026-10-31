; Channel metadata only, not a signature/trust credential. Never contains user data.
!macro customInstall
  FileOpen $0 "$INSTDIR\installation.json" w
  FileWrite $0 '{"schema":1,"distribution":"nsis"}'
  FileClose $0
!macroend

!macro customUnInstall
  Delete "$INSTDIR\installation.json"
!macroend

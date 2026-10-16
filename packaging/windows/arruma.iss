; Instalador do Arruma para Windows (Inno Setup 6).
; Uso: iscc /DAppVersion=0.2.0 packaging\windows\arruma.iss
; Espera a aplicação já construída em dist\Arruma (PyInstaller).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{18C83DB7-5EF6-4B5E-B0F4-8D1E10EE1738}
AppName=Arruma
AppVersion={#AppVersion}
AppVerName=Arruma {#AppVersion}
AppPublisher=Arruma
AppPublisherURL=https://github.com/franciscovazquezreis/Arruma
AppSupportURL=https://github.com/franciscovazquezreis/Arruma/issues
DefaultDirName={autopf}\Arruma
DefaultGroupName=Arruma
DisableProgramGroupPage=yes
; Instala só para o utilizador atual, sem pedir permissões de administrador (pode mudar-se).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=Arruma-{#AppVersion}-windows-instalador
SetupIconFile=..\icons\arruma.ico
UninstallDisplayIcon={app}\Arruma.exe
UninstallDisplayName=Arruma
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "contextmenu"; Description: "Acrescentar «Arrumar com o Arruma» ao menu do botão direito das pastas"
Name: "desktopicon"; Description: "Criar um atalho no Ambiente de Trabalho"; Flags: unchecked

[Files]
Source: "..\..\dist\Arruma\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Arruma"; Filename: "{app}\Arruma.exe"; Comment: "Organizador de ficheiros local e sem internet"
Name: "{autodesktop}\Arruma"; Filename: "{app}\Arruma.exe"; Tasks: desktopicon

[Registry]
; Clique direito numa pasta
Root: HKA; Subkey: "Software\Classes\Directory\shell\Arruma"; ValueType: string; ValueName: ""; ValueData: "Arrumar com o Arruma"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\Arruma"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\Arruma.exe"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\Arruma\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Arruma.exe"" ""%1"""; Tasks: contextmenu
; Clique direito no fundo de uma pasta aberta
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\Arruma"; ValueType: string; ValueName: ""; ValueData: "Arrumar esta pasta com o Arruma"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\Arruma"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\Arruma.exe"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\Arruma\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Arruma.exe"" ""%V"""; Tasks: contextmenu

[Run]
Filename: "{app}\Arruma.exe"; Description: "Abrir o Arruma"; Flags: nowait postinstall skipifsilent

; SPDX-License-Identifier: GPL-3.0-or-later
; Instalador do Arruma para Windows (Inno Setup 6.3 ou mais recente: lê o ficheiro em UTF-8).
; Uso: iscc /DAppVersion=0.2.1 packaging\windows\arruma.iss
; Espera a aplicação já construída em dist\Arruma (PyInstaller).
; Se o Arruma já estiver instalado, compara as versões: atualiza se a instalada for mais antiga,
; não faz nada se for a mesma e pede confirmação antes de a substituir por uma mais antiga.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{18C83DB7-5EF6-4B5E-B0F4-8D1E10EE1738}
AppName=Arruma
AppVersion={#AppVersion}
AppVerName=Arruma {#AppVersion}
AppPublisher=Francisco Reis
AppCopyright=Copyright © 2026 Francisco Reis
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

[InstallDelete]
; Numa atualização, retira as bibliotecas da versão anterior antes de copiar as novas.
Type: filesandordirs; Name: "{app}\_internal"

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

[Code]
const
  ChaveDesinstalacao = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#StringChange(SetupSetting("AppId"), "{{", "{")}_is1';
  VersaoNova = '{#AppVersion}';

{ Versão registada pela instalação anterior (vazia se o Arruma não estiver instalado). }
function VersaoInstalada(): String;
var
  Versao: String;
begin
  if not RegQueryStringValue(HKCU, ChaveDesinstalacao, 'DisplayVersion', Versao) then
    if not RegQueryStringValue(HKLM, ChaveDesinstalacao, 'DisplayVersion', Versao) then
      Versao := '';
  Result := Versao;
end;

{ Tira o número seguinte de uma versão como 0.2.1. }
function ProximoNumero(var Versao: String): Integer;
var
  Ponto: Integer;
begin
  Ponto := Pos('.', Versao);
  if Ponto = 0 then begin
    Result := StrToIntDef(Versao, 0);
    Versao := '';
  end else begin
    Result := StrToIntDef(Copy(Versao, 1, Ponto - 1), 0);
    Delete(Versao, 1, Ponto);
  end;
end;

{ -1, 0 ou 1, conforme A é anterior, igual ou posterior a B. }
function ComparaVersoes(A, B: String): Integer;
var
  I, X, Y: Integer;
begin
  Result := 0;
  for I := 1 to 4 do begin
    X := ProximoNumero(A);
    Y := ProximoNumero(B);
    if X <> Y then begin
      if X < Y then Result := -1 else Result := 1;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
var
  Instalada: String;
begin
  Result := True;
  Instalada := VersaoInstalada();
  if Instalada = '' then
    Exit;  { primeira instalação }
  case ComparaVersoes(Instalada, VersaoNova) of
    0: begin
         SuppressibleMsgBox('O Arruma ' + VersaoNova + ' já está instalado. Não há nada a atualizar.',
                            mbInformation, MB_OK, IDOK);
         Result := False;
       end;
    1: Result := SuppressibleMsgBox('Está instalado o Arruma ' + Instalada + ', mais recente do que este ' +
                                    'instalador (' + VersaoNova + ').' + #13#10#13#10 +
                                    'Queres mesmo substituí-lo pela versão mais antiga?',
                                    mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  else
    Result := SuppressibleMsgBox('Vai atualizar o Arruma da versão ' + Instalada + ' para a ' + VersaoNova + '.' +
                                 #13#10 + 'O histórico e as definições ficam.',
                                 mbInformation, MB_OKCANCEL, IDOK) = IDOK;
  end;
end;

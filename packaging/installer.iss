; اسکریپت Inno Setup برای ساخت فایل نصبی ویندوز «تکسایدک نبض»
; پیش‌نیاز: ابتدا با PyInstaller خروجی بگیرید (dist/TexayadakNabz)
; سپس این فایل را با Inno Setup Compiler باز و Compile کنید.

#define AppName "تکسایدک نبض"
#define AppVersion "1.0.0"
#define AppPublisher "Farshad Abolfathi"
#define AppExeName "TexayadakNabz.exe"

[Setup]
AppId={{8F3A2C10-TEXA-NABZ-0001-A1B2C3D4E5F6}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\TexayadakNabz
DefaultGroupName=تکسایدک نبض
DisableProgramGroupPage=yes
OutputBaseFilename=TexayadakNabz-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; رابط نصب راست‌به‌چپ فارسی
; (فایل زبان فارسی را از پوشهٔ Languages\Unofficial اینو‌ستاپ اضافه کنید)
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "ساخت آیکون روی دسکتاپ"; GroupDescription: "میان‌برها:"
Name: "startup"; Description: "اجرای خودکار برنامه هنگام روشن شدن ویندوز"; GroupDescription: "راه‌اندازی:"

[Files]
Source: "..\dist\TexayadakNabz\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\تکسایدک نبض"; Filename: "{app}\{#AppExeName}"
Name: "{group}\حذف تکسایدک نبض"; Filename: "{uninstallexe}"
Name: "{autodesktop}\تکسایدک نبض"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
; اجرای خودکار هنگام بوت ویندوز (برای سینک خودکار زمان‌بندی‌شده)
Name: "{userstartup}\تکسایدک نبض"; Filename: "{app}\{#AppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExeName}"; Description: "اجرای برنامه"; Flags: nowait postinstall skipifsilent

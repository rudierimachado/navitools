# Como adicionar o APK do NEXUS Financeiro

## 📱 Passos para disponibilizar o APK

### 1. Compile o APK do Flutter

No diretório do projeto Flutter (`finance_app`):

```bash
cd finance_app
flutter build apk --release
```

O APK será gerado em:
```
finance_app/build/app/outputs/flutter-apk/app-release.apk
```

### 2. Copie o APK para esta pasta

Renomeie e copie o APK compilado para esta pasta:

```bash
# Windows
copy finance_app\build\app\outputs\flutter-apk\app-release.apk navitools\static\downloads\finance-app.apk

# Linux/Mac
cp finance_app/build/app/outputs/flutter-apk/app-release.apk navitools/static/downloads/finance-app.apk
```

### 3. Faça deploy na AWS

Depois de copiar o APK, faça o deploy do projeto `navitools` na AWS normalmente.

O APK estará disponível em:
```
https://nexusrdr.com.br/gerenciamento-financeiro/download/apk
```

## 🌐 Página de apresentação

A página de apresentação do app está em:
```
https://nexusrdr.com.br/gerenciamento-financeiro/apresentacao
```

Ela mostra:
- Descrição do app
- Recursos principais
- Botão de download do APK
- Instruções de instalação

## ⚠️ Importante

- O arquivo APK deve se chamar **exatamente** `finance-app.apk`
- Tamanho típico do APK: 15-30 MB
- Certifique-se de que o APK está assinado (release build)

## 🔄 Atualizando o APK

Sempre que compilar uma nova versão:

1. Compile o novo APK: `flutter build apk --release`
2. Substitua o arquivo `finance-app.apk` nesta pasta
3. Faça deploy na AWS
4. Usuários podem baixar a nova versão

---

**Status atual:** Aguardando APK compilado

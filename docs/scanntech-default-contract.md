# Contrato Operacional do Aquafast IA

Este arquivo registra o padrao de trabalho que nao deve ser quebrado por mudancas futuras.

## Padrao imutavel

- O modelo visivel para o usuario no Open WebUI deve permanecer como `Scanntech Analyst`.
- O modelo interno do pipe continua sendo `qwen2.5:latest` e nao deve aparecer como porta de entrada principal.
- Alteracoes na API, ingestao, relatorios ou Metabase nao devem trocar esse padrao.
- Se o Open WebUI perder o estado, o padrao deve ser restaurado em vez de redefinir o fluxo.

## Regras de uso

- Perguntas analiticas devem passar pela `Scanntech API`.
- Respostas textuais livres podem usar o `qwen2.5` apenas como motor interno.
- Nao alterar o nome do pipe `Scanntech Analyst`.
- Nao alterar o `DEFAULT_MODELS=scanntech_analyst` do `docker-compose.yml` sem atualizar este contrato.

## Recuperacao

Se o Open WebUI voltar para outro modelo, rode:

```powershell
.\scripts\restore_scanntech_defaults.ps1
```

O script:

- reativa a pipe `Scanntech Analyst`
- sincroniza o conteudo atual da funcao para o banco interno do Open WebUI
- corrige o modelo salvo do chat mais recente para `Scanntech Analyst`
- reinicia o `open-webui`

## Validacao rapida

- Abrir `http://localhost:3000`
- Confirmar que o seletor do chat mostra `Scanntech Analyst`
- Confirmar que perguntas analiticas continuam consultando a base local

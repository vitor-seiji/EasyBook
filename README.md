# EasyBook

App desktop para buscar ebooks em canais do Telegram, salvar em biblioteca local e enviar para o Kindle.

## Funcionalidades

- Busca ebooks por título diretamente nos canais do Telegram
- Salva em banco de dados local
- Filtra por formato (EPUB, MOBI, PDF)
- Envia para o Kindle via SendGrid

## Requisitos

- Python 3.10+
- Calibre instalado (para conversão de formatos)

## Instalação

1. Clone o repositório
2. Instale as dependências:
pip install telethon sqlalchemy customtkinter sendgrid

3. Renomeie `config.exemplo.py` para `config.py` e preencha suas credenciais
4. Rode o app:
python app.py


## Configuração

Siga o guia completo de configuração para obter as credenciais do Telegram, SendGrid e o email do Kindle.

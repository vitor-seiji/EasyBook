import os
import asyncio
import smtplib
import subprocess
import pathlib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (Mail, Attachment, FileContent,
                                   FileName, FileType, Disposition)
import base64
from telethon import TelegramClient, events
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

from config import *

# ─── BANCO DE DADOS ───────────────────────────────────────────────────────────

Base = declarative_base()

class Ebook(Base):
    __tablename__ = "ebooks"
    id             = Column(Integer, primary_key=True)
    titulo         = Column(String)
    arquivo        = Column(String)
    formato        = Column(String)
    enviado_kindle = Column(Boolean, default=False)
    data_download  = Column(DateTime, default=datetime.now)

BASE_DIR = pathlib.Path(__file__).parent
engine = create_engine(f"sqlite:///{BASE_DIR}/ebooks.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# ─── FUNÇÕES DO KINDLE ────────────────────────────────────────────────────────

def converter_para_mobi(caminho_arquivo):
    saida = caminho_arquivo.rsplit(".", 1)[0] + ".mobi"
    subprocess.run(["ebook-convert", caminho_arquivo, saida], check=True)
    return saida

def enviar_para_kindle(caminho_arquivo):
    nome_arquivo = os.path.basename(caminho_arquivo)
    extensao = os.path.splitext(nome_arquivo)[1].lower()

    # Define o tipo do arquivo
    tipos = {
        ".epub": "application/epub+zip",
        ".mobi": "application/x-mobipocket-ebook",
        ".pdf":  "application/pdf",
        ".azw3": "application/vnd.amazon.ebook"
    }
    tipo = tipos.get(extensao, "application/octet-stream")

    # Lê e codifica o arquivo em base64
    with open(caminho_arquivo, "rb") as f:
        dados = base64.b64encode(f.read()).decode()

    # Monta o e-mail
    mensagem = Mail(
        from_email=HOTMAIL_REMETENTE,
        to_emails=KINDLE_EMAIL,
        subject="convert",
        plain_text_content=" "
    )

    # Anexa o arquivo
    anexo = Attachment(
        file_content=FileContent(dados),
        file_name=FileName(nome_arquivo),
        file_type=FileType(tipo),
        disposition=Disposition("attachment")
    )
    mensagem.attachment = anexo

    # Envia
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(mensagem)

# ─── FUNÇÕES DO BANCO DE DADOS ────────────────────────────────────────────────

def salvar_no_banco(titulo, arquivo, formato):
    session = Session()
    # Evita duplicatas
    existente = session.query(Ebook).filter_by(arquivo=arquivo).first()
    if existente:
        print(f"⚠️  '{titulo}' já está no banco de dados.")
        session.close()
        return
    ebook = Ebook(titulo=titulo, arquivo=arquivo, formato=formato)
    session.add(ebook)
    session.commit()
    session.close()
    print(f"📚 '{titulo}' salvo no banco de dados.")

def pesquisar_ebooks(termo):
    session = Session()
    resultados = session.query(Ebook).filter(
        Ebook.titulo.ilike(f"%{termo}%")
    ).all()
    session.close()
    return resultados

def listar_todos():
    session = Session()
    todos = session.query(Ebook).order_by(Ebook.data_download.desc()).all()
    session.close()
    return todos

def marcar_como_enviado(ebook_id):
    session = Session()
    ebook = session.query(Ebook).filter_by(id=ebook_id).first()
    if ebook:
        ebook.enviado_kindle = True
        session.commit()
    session.close()

def deletar_ebook(ebook_id):
    session = Session()
    ebook = session.query(Ebook).filter_by(id=ebook_id).first()
    if ebook:
        # Remove o arquivo físico também
        if os.path.exists(ebook.arquivo):
            os.remove(ebook.arquivo)
        session.delete(ebook)
        session.commit()
        print(f"🗑️  '{ebook.titulo}' removido.")
    session.close()

async def buscar_historico():
    limite = input("\nQuantas mensagens buscar por canal? (ex: 200): ").strip()
    try:
        limite = int(limite)
    except ValueError:
        limite = 100

    print(f"\n🔍 Varrendo histórico dos canais (últimas {limite} mensagens cada)...\n")
    encontrados = 0

    async with TelegramClient("sessao_kindle", TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        for canal in CANAIS:
            print(f"📡 Verificando: @{canal}")
            try:
                async for mensagem in client.iter_messages(canal, limit=limite):
                    if not mensagem.document:
                        continue

                    atributos = mensagem.document.attributes
                    nome_arquivo = next(
                        (a.file_name for a in atributos if hasattr(a, "file_name")), None
                    )
                    if not nome_arquivo:
                        continue

                    extensao = os.path.splitext(nome_arquivo)[1].lower()
                    if extensao not in FORMATOS_ACEITOS:
                        continue

                    encontrados += 1
                    titulo = os.path.splitext(nome_arquivo)[0]
                    print(f"  📖 [{encontrados}] {titulo} ({extensao.upper()})")

                    resposta = input("      Baixar? (s/n/parar): ").strip().lower()
                    if resposta == "parar":
                        return
                    if resposta != "s":
                        continue

                    caminho = os.path.join(PASTA_EBOOKS, nome_arquivo)
                    await mensagem.download_media(file=caminho)
                    salvar_no_banco(titulo, caminho, extensao)

            except Exception as e:
                print(f"  ⚠️  Erro no canal @{canal}: {e}")

    print(f"\n✅ Varredura concluída. {encontrados} ebook(s) encontrado(s).")

async def buscar_por_titulo():
    termo = input("\n🔍 Digite o título (ou parte dele) para buscar nos canais: ").strip().lower()
    limite = input("Quantas mensagens verificar por canal? (ex: 500): ").strip()
    try:
        limite = int(limite)
    except ValueError:
        limite = 500

    print(f"\n🔎 Buscando '{termo}' nos canais...\n")
    encontrados = []

    async with TelegramClient("sessao_kindle", TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        for canal in CANAIS:
            print(f"📡 Verificando: @{canal}")
            try:
                async for mensagem in client.iter_messages(canal, limit=limite, search=termo):
                    if not mensagem.document:
                        continue

                    atributos = mensagem.document.attributes
                    nome_arquivo = next(
                        (a.file_name for a in atributos if hasattr(a, "file_name")), None
                    )
                    if not nome_arquivo:
                        continue

                    extensao = os.path.splitext(nome_arquivo)[1].lower()
                    if extensao not in FORMATOS_ACEITOS:
                        continue

                    titulo = os.path.splitext(nome_arquivo)[0]
                    encontrados.append({
                        "canal": canal,
                        "titulo": titulo,
                        "extensao": extensao,
                        "nome_arquivo": nome_arquivo,
                        "mensagem": mensagem
                    })
                    print(f"  ✅ Encontrado: {titulo} ({extensao.upper()}) em @{canal}")

            except Exception as e:
                print(f"  ⚠️  Erro no canal @{canal}: {e}")

        # ⬇️ A escolha e o download agora ficam DENTRO do async with
        if not encontrados:
            print(f"\n❌ Nenhum ebook encontrado com '{termo}'.")
            return

        print(f"\n📚 {len(encontrados)} resultado(s) encontrado(s):\n")
        for i, item in enumerate(encontrados):
            print(f"  [{i+1}] {item['titulo']} ({item['extensao'].upper()}) — @{item['canal']}")

        escolha = input("\nDigite o número do livro para baixar (ou 0 para cancelar): ").strip()
        try:
            escolha = int(escolha)
        except ValueError:
            print("❌ Opção inválida.")
            return

        if escolha == 0 or escolha > len(encontrados):
            return

        selecionado = encontrados[escolha - 1]
        caminho = os.path.join(PASTA_EBOOKS, selecionado["nome_arquivo"])

        print(f"\n⬇️  Baixando '{selecionado['titulo']}'...")
        await selecionado["mensagem"].download_media(file=caminho)
        salvar_no_banco(selecionado["titulo"], caminho, selecionado["extensao"])
        print("✅ Salvo na biblioteca!")

# ─── INTERFACE DO TERMINAL ────────────────────────────────────────────────────

def exibir_ebook(ebook):
    status = "✅ Enviado" if ebook.enviado_kindle else "📱 Não enviado"
    print(f"  [{ebook.id}] {ebook.titulo}")
    print(f"       Formato: {ebook.formato.upper()}  |  {status}  |  Baixado em: {ebook.data_download.strftime('%d/%m/%Y')}")

def menu_principal():
    print("\n" + "="*50)
    print("       📚 MINHA BIBLIOTECA KINDLE")
    print("="*50)
    print("  [1] Monitorar Telegram (baixar novos ebooks)")
    print("  [2] Pesquisar livro")
    print("  [3] Ver toda a biblioteca")
    print("  [4] Enviar livro para o Kindle")
    print("  [5] Deletar livro")
    print("  [6] Buscar ebooks no histórico dos canais")
    print("  [7] Buscar título específico nos canais")
    print("  [0] Sair")
    print("="*50)
    return input("  Escolha uma opção: ").strip()

def opcao_pesquisar():
    termo = input("\n🔍 Digite o título (ou parte dele): ").strip()
    resultados = pesquisar_ebooks(termo)
    if not resultados:
        print("❌ Nenhum livro encontrado.")
        return
    print(f"\n📖 {len(resultados)} resultado(s) encontrado(s):\n")
    for ebook in resultados:
        exibir_ebook(ebook)

def opcao_listar():
    todos = listar_todos()
    if not todos:
        print("\n📭 Sua biblioteca está vazia. Monitore o Telegram para baixar ebooks.")
        return
    print(f"\n📚 Sua biblioteca ({len(todos)} livro(s)):\n")
    for ebook in todos:
        exibir_ebook(ebook)

def opcao_enviar():
    termo = input("\n🔍 Pesquise o livro que quer enviar: ").strip()
    resultados = pesquisar_ebooks(termo)

    if not resultados:
        print("❌ Nenhum livro encontrado com esse nome.")
        return

    print(f"\n{len(resultados)} resultado(s):\n")
    for ebook in resultados:
        exibir_ebook(ebook)

    try:
        escolha = int(input("\nDigite o número [ID] do livro para enviar: ").strip())
    except ValueError:
        print("❌ ID inválido.")
        return

    session = Session()
    ebook = session.query(Ebook).filter_by(id=escolha).first()
    session.close()

    if not ebook:
        print("❌ Livro não encontrado.")
        return

    if ebook.enviado_kindle:
        reenviar = input(f"⚠️  '{ebook.titulo}' já foi enviado antes. Reenviar? (s/n): ").strip().lower()
        if reenviar != "s":
            return

    # Converte se necessário
    caminho = ebook.arquivo
    if not caminho.endswith((".mobi", ".epub")):
        print("🔄 Convertendo formato...")
        caminho = converter_para_mobi(caminho)

    print(f"📤 Enviando '{ebook.titulo}' para o Kindle...")
    try:
        enviar_para_kindle(caminho)
        marcar_como_enviado(ebook.id)
        print(f"✅ Enviado com sucesso! Verifique seu Kindle em alguns minutos.")
    except Exception as e:
        print(f"❌ Erro ao enviar: {e}")

def opcao_deletar():
    termo = input("\n🔍 Pesquise o livro que quer deletar: ").strip()
    resultados = pesquisar_ebooks(termo)

    if not resultados:
        print("❌ Nenhum livro encontrado.")
        return

    for ebook in resultados:
        exibir_ebook(ebook)

    try:
        escolha = int(input("\nDigite o número [ID] do livro para deletar: ").strip())
    except ValueError:
        print("❌ ID inválido.")
        return

    confirmar = input(f"⚠️  Tem certeza? Isso apaga o arquivo também. (s/n): ").strip().lower()
    if confirmar == "s":
        deletar_ebook(escolha)

# ─── MONITORAMENTO DO TELEGRAM ────────────────────────────────────────────────

FORMATOS_ACEITOS = [".epub", ".mobi", ".pdf", ".azw3"]

async def monitorar_telegram():
    print("\n🚀 Conectando ao Telegram...")
    print("📡 Monitorando canais. Pressione Ctrl+C para voltar ao menu.\n")

    async with TelegramClient("sessao_kindle", TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:

        @client.on(events.NewMessage(chats=CANAIS))
        async def ao_receber(evento):
            mensagem = evento.message
            if not mensagem.document:
                return

            nome_arquivo = mensagem.document.attributes[-1].file_name
            extensao     = os.path.splitext(nome_arquivo)[1].lower()

            if extensao not in FORMATOS_ACEITOS:
                return

            print(f"\n📥 Novo ebook disponível: {nome_arquivo}")
            resposta = input("Baixar e salvar na biblioteca? (s/n): ").strip().lower()

            if resposta != "s":
                print("Ignorado.")
                return

            caminho = os.path.join(PASTA_EBOOKS, nome_arquivo)
            await mensagem.download_media(file=caminho)

            titulo  = os.path.splitext(nome_arquivo)[0]
            salvar_no_banco(titulo, caminho, extensao)

        await client.run_until_disconnected()

# ─── INÍCIO ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(PASTA_EBOOKS, exist_ok=True)
    while True:
        opcao = menu_principal()

        if opcao == "1":
            try:
                asyncio.run(monitorar_telegram())
            except KeyboardInterrupt:
                print("\n\n↩️  Voltando ao menu...")

        elif opcao == "2":
            opcao_pesquisar()

        elif opcao == "3":
            opcao_listar()

        elif opcao == "4":
            opcao_enviar()

        elif opcao == "5":
            opcao_deletar()
        elif opcao == "6":
            try:
                asyncio.run(buscar_historico())
            except KeyboardInterrupt:
                print("\n\n↩️  Voltando ao menu...")
        elif opcao == "7":
            try:
                asyncio.run(buscar_por_titulo())
            except KeyboardInterrupt:
                print("\n\n↩️  Voltando ao menu...")
        elif opcao == "0":
            print("\n👋 Até mais!\n")
            break

        else:
            print("❌ Opção inválida.")
import os
import json
from datetime import date

import base64
import feedparser
import re
from urllib.parse import urljoin, urlparse

import google.generativeai as genai
import requests
from dotenv import load_dotenv

from models import BlogPost, db
from administrador.routes import (
    _generate_unique_slug,
    _auto_summary,
    _estimate_reading_time,
    _extract_tags_from_text,
)


class TechNewsBot:
    """Robô que busca notícias no TechCrunch, processa com IA e publica no blog."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY não encontrada nas variáveis de ambiente.")

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    # ------------------------------------------------------------------
    # BUSCA DE NOTÍCIAS
    # ------------------------------------------------------------------
    def buscar_noticias_de_hoje(self) -> list[dict]:
        """Busca notícias do TechCrunch publicadas HOJE via RSS."""
        try:
            print("🔍 Buscando notícias de hoje no TechCrunch...")

            feed_url = "https://techcrunch.com/feed/"
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                print("❌ Nenhuma notícia encontrada no feed")
                return []

            hoje = date.today()
            noticias_hoje: list[dict] = []

            for entry in feed.entries:
                published_parsed = getattr(entry, "published_parsed", None)
                if not published_parsed:
                    continue

                published_date = date(
                    published_parsed.tm_year,
                    published_parsed.tm_mon,
                    published_parsed.tm_mday,
                )

                if published_date != hoje:
                    continue

                noticias_hoje.append(
                    {
                        "titulo": entry.title,
                        "link": entry.link,
                        "resumo": getattr(entry, "summary", ""),
                        "data": getattr(entry, "published", ""),
                        "autor": getattr(entry, "author", "TechCrunch"),
                        "raw": entry,
                    }
                )

            print(f"✅ Encontradas {len(noticias_hoje)} notícias de hoje")
            return noticias_hoje

        except Exception as e:
            print(f"❌ Erro ao buscar notícias: {e}")
            return []

    # ------------------------------------------------------------------
    # PROCESSAMENTO COM IA (GROQ -> GEMINI)
    # ------------------------------------------------------------------
    def processar_com_ia(self, noticia: dict) -> dict | None:
        """Processa a notícia com IA e retorna um dicionário estruturado para BlogPost."""
        print(f"🧠 Processando com IA: {noticia['titulo']}")

        prompt = f"""
Você é um redator para um blog brasileiro de tecnologia e inteligência artificial chamado NEXUSRDR.

Use a NOTÍCIA ORIGINAL abaixo apenas como referência e crie um RESUMO 100% ORIGINAL em português brasileiro.

NOTÍCIA ORIGINAL (NÃO COPIE LITERALMENTE):
- Título: {noticia['titulo']}
- Resumo: {noticia['resumo'][:1500]}
- Link: {noticia['link']}
- Data: {noticia['data']}

TAREFA:
1. Explique a notícia para o público brasileiro de forma resumida (200 a 600 palavras).
2. Foque nos pontos principais.
3. Escreva o texto em estilo de blog, curto e direto.
4. Use markdown simples no corpo do texto (títulos com ## e listas com - quando fizer sentido).
5. Inclua uma frase final mencionando a fonte TechCrunch como referência.

RETORNO:
Responda APENAS com um JSON VÁLIDO, sem texto extra, no seguinte formato:
{{
  "title": "Título atrativo em português",
  "subtitle": "Subtítulo curto explicando a notícia",
  "summary": "Resumo em até 220 caracteres do que o artigo cobre",
  "content_markdown": "Texto completo em markdown",
  "tags": ["tecnologia", "ia", "produtividade"],
  "category": "inteligencia-artificial",
  "section": "novidades"
}}

IMPORTANTE:
- O campo "tags" deve ser uma lista de palavras-chave em português.
- "category" use uma destas: "tecnologia", "inteligencia-artificial", "tutoriais", "produtividade", "design", "marketing", "programacao", "novidades", "dicas".
- "section" use uma destas: "novidades", "dicas", "destaque", "geral".
- NÃO inclua comentários, markdown fora do campo "content_markdown" ou texto antes/depois do JSON.
"""

        dados_groq = self._processar_com_groq(prompt)
        if dados_groq:
            print("✅ Artigo estruturado pela IA (Groq)")
            return dados_groq

        try:
            print("⚠️ Falha na Groq, tentando Gemini como fallback...")
            response = self.model.generate_content(prompt)
            raw_text = response.text.strip()

            try:
                dados = json.loads(raw_text)
            except json.JSONDecodeError:
                start = raw_text.find("{")
                end = raw_text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    cleaned = raw_text[start : end + 1]
                    dados = json.loads(cleaned)
                else:
                    raise

            print("✅ Artigo estruturado pela IA (Gemini)")
            return dados

        except Exception as e:
            msg = str(e)
            print(f"❌ Erro ao processar com IA (Gemini - fallback): {msg}")
            return None

    def _processar_com_groq(self, prompt: str) -> dict | None:
        """Chama a API da Groq usando endpoint compatível com OpenAI."""
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            print("❌ GROQ_API_KEY não definida. Não é possível usar Groq.")
            return None

        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.8,
            }

            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                print(f"❌ Erro HTTP ao chamar Groq: {resp.status_code} - {resp.text[:200]}")
                return None

            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                print("❌ Resposta da Groq sem choices.")
                return None

            content = choices[0].get("message", {}).get("content", "") or ""
            content = content.strip()
            if not content:
                print("❌ Resposta vazia da Groq.")
                return None

            # Remover possíveis wrappers ```json
            if content.startswith("```"):
                linhas = content.splitlines()
                if len(linhas) >= 2:
                    if linhas[0].startswith("```"):
                        linhas = linhas[1:]
                    if linhas and linhas[-1].startswith("```"):
                        linhas = linhas[:-1]
                    content = "\n".join(linhas).strip()

            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                content = content[start : end + 1]

            def _clean_control_chars(s: str) -> str:
                return "".join(
                    ch for ch in s if ord(ch) >= 32 or ch in "\n\r\t"
                )

            cleaned = _clean_control_chars(content)

            try:
                dados = json.loads(cleaned)
            except json.JSONDecodeError as e:
                print(f"❌ JSON inválido retornado pela Groq mesmo após limpeza: {e}")
                return None

            return dados

        except Exception as e:
            print(f"❌ Erro ao processar com IA (Groq): {e}")
            return None

    # ------------------------------------------------------------------
    # DEDUPLICAÇÃO
    # ------------------------------------------------------------------
    def _post_ja_existe(self, titulo: str) -> bool:
        existente = BlogPost.query.filter_by(title=titulo).first()
        return existente is not None

    def _post_com_link_ja_existe(self, link: str | None) -> bool:
        if not link:
            return False
        existente = BlogPost.query.filter_by(cta_link=link).first()
        return existente is not None

    # ------------------------------------------------------------------
    # CRIAÇÃO DO POST
    # ------------------------------------------------------------------
    def criar_post_no_blog(self, dados: dict, noticia_original: dict) -> BlogPost | None:
        """Cria um BlogPost no banco a partir dos dados gerados pela IA."""
        try:
            titulo = dados.get("title") or noticia_original["titulo"]

            link_original = noticia_original.get("link")
            if self._post_com_link_ja_existe(link_original):
                print(f"⚠️ Post já existe para o link original: {link_original}. Pulando...")
                return None

            if self._post_ja_existe(titulo):
                print(f"⚠️ Post já existe com o título: {titulo}. Pulando...")
                return None

            content_md = dados.get("content_markdown") or ""

            summary = dados.get("summary") or _auto_summary(content_md)
            reading_time = _estimate_reading_time(content_md)

            tags_list = dados.get("tags") or _extract_tags_from_text(titulo, content_md)
            tags_json = json.dumps(tags_list, ensure_ascii=False)

            category = dados.get("category") or "novidades"
            section = dados.get("section") or "novidades"

            slug = _generate_unique_slug(titulo)

            cover_data = self._baixar_capa(noticia_original)

            post = BlogPost(
                title=titulo,
                subtitle=dados.get("subtitle"),
                slug=slug,
                category=category,
                section=section,
                tags=tags_json,
                cover=cover_data,
                summary=summary,
                content=content_md,
                priority="normal",
                active=True,
                reading_time=reading_time,
                meta_description=summary[:155],
                cta_link=link_original,
            )

            db.session.add(post)
            db.session.commit()

            print(f"✅ Post criado: {post.title} (/blog/{post.slug})")
            return post

        except Exception as e:
            db.session.rollback()
            print(f"❌ Erro ao salvar post no banco: {e}")
            return None

    # ------------------------------------------------------------------
    # EXTRAÇÃO DE IMAGEM (RSS)
    # ------------------------------------------------------------------
    def _extrair_url_imagem(self, entry) -> str | None:
        """Tenta extrair a URL de imagem de um item do feed RSS (apenas RSS)."""
        if not entry:
            return None

        # 1) media_content
        media_content = getattr(entry, "media_content", None)
        if media_content and isinstance(media_content, list):
            for m in media_content:
                url = m.get("url") if isinstance(m, dict) else None
                if url:
                    print(f"🖼️ Imagem encontrada em media_content: {url}")
                    return url

        # 2) media_thumbnail
        media_thumbnail = getattr(entry, "media_thumbnail", None)
        if media_thumbnail and isinstance(media_thumbnail, list):
            for m in media_thumbnail:
                url = m.get("url") if isinstance(m, dict) else None
                if url:
                    print(f"🖼️ Imagem encontrada em media_thumbnail: {url}")
                    return url

        # 3) links com rel="enclosure" e tipo image/*
        links = getattr(entry, "links", None)
        if links:
            for link in links:
                if not isinstance(link, dict):
                    continue
                rel = link.get("rel")
                href = link.get("href")
                tipo = link.get("type", "")
                if rel == "enclosure" and href and tipo.startswith("image/"):
                    print(f"🖼️ Imagem encontrada em link enclosure: {href}")
                    return href

        # 4) tentar extrair <img> do HTML do summary/description
        summary = getattr(entry, "summary", None) or getattr(entry, "description", None)
        if summary:
            match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, flags=re.IGNORECASE)
            if match:
                print(f"🖼️ Imagem encontrada no summary/description: {match.group(1)}")
                return match.group(1)

        # 5) tentar extrair <img> do HTML completo em entry.content
        contents = getattr(entry, "content", None)
        if contents and isinstance(contents, list) and contents:
            first_content = contents[0]
            html_content = getattr(first_content, "value", None) or str(first_content)
            if html_content:
                match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, flags=re.IGNORECASE)
                if match:
                    print(f"🖼️ Imagem encontrada no content HTML: {match.group(1)}")
                    return match.group(1)

        print("⚠️ Nenhuma URL de imagem encontrada neste item do feed.")
        return None

    # ------------------------------------------------------------------
    # EXTRAÇÃO DE IMAGEM (PÁGINA HTML)
    # ------------------------------------------------------------------
    def _extrair_imagem_da_pagina(self, link: str) -> str | None:
        """Tenta extrair URL de imagem diretamente da página HTML (og:image, twitter:image ou primeira <img>)."""
        if not link:
            return None

        try:
            print(f"🔎 Buscando imagem diretamente na página: {link}")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            }

            resp = requests.get(link, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.text:
                print(f"❌ Falha ao carregar página para extrair imagem. Status: {resp.status_code}")
                return None

            html = resp.text

            # 1) meta property="og:image"
            match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
            if match:
                url = match.group(1)
                print(f"🖼️ Imagem encontrada em og:image: {url}")
                return url

            # 2) meta name="twitter:image"
            match = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
            if match:
                url = match.group(1)
                print(f"🖼️ Imagem encontrada em twitter:image: {url}")
                return url

            # 3) primeira <img> da página (src, data-src ou srcset)
            match = re.search(
                r'<img[^>]+(?:src|data-src|data-original|srcset)=["\']([^"\']+)["\']',
                html,
                flags=re.IGNORECASE,
            )
            if match:
                url = match.group(1)
                print(f"🖼️ Imagem encontrada no HTML da página (bruta): {url}")
                return url

            print("⚠️ Nenhuma imagem encontrada na página HTML.")
            return None
        except Exception as e:
            print(f"❌ Erro ao extrair imagem da página: {e}")
            return None

    # ------------------------------------------------------------------
    # DOWNLOAD DA CAPA
    # ------------------------------------------------------------------
    def _baixar_capa(self, noticia_original: dict) -> str | None:
        """Baixa a imagem de capa e retorna data URL base64, ou None.

        1) Tenta extrair do RSS.
        2) Se não achar, tenta extrair da página HTML.
        """
        try:
            entry = noticia_original.get("raw") if isinstance(noticia_original, dict) else noticia_original
            url = self._extrair_url_imagem(entry)

            if not url and isinstance(noticia_original, dict):
                link = noticia_original.get("link")
                url = self._extrair_imagem_da_pagina(link)

                # Normalizar URL relativa / protocol-relative
                if url and link:
                    if url.startswith("//"):
                        parsed = urlparse(link)
                        url = f"{parsed.scheme}:{url}"
                    elif url.startswith("/") or not urlparse(url).scheme:
                        url = urljoin(link, url)

            if not url:
                print("⚠️ Nenhuma URL de imagem encontrada no feed nem na página.")
                return None

            print(f"🖼️ Tentando baixar capa da URL: {url}")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": noticia_original.get("link", "") if isinstance(noticia_original, dict) else "",
            }

            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200 or not resp.content:
                print(f"❌ Falha ao baixar imagem da capa. Status: {resp.status_code}")
                return None

            content_type = resp.headers.get("Content-Type", "image/jpeg")
            if not content_type.startswith("image/"):
                content_type = "image/jpeg"

            encoded = base64.b64encode(resp.content).decode("utf-8")
            return f"data:{content_type};base64,{encoded}"
        except Exception as e:
            print(f"❌ Erro ao baixar capa: {e}")
            return None

        print(f"🖼️ Tentando baixar capa da URL: {url}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": noticia_original.get("link", "") if isinstance(noticia_original, dict) else "",
        }

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200 or not resp.content:
            print(f"❌ Falha ao baixar imagem da capa. Status: {resp.status_code}")
            return None

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"

        encoded = base64.b64encode(resp.content).decode("utf-8")
        return f"data:{content_type};base64,{encoded}"
    except Exception as e:
        print(f"❌ Erro ao baixar capa: {e}")
        return None

# ------------------------------------------------------------------
# EXECUÇÃO PRINCIPAL
# ------------------------------------------------------------------
def executar(self):
    """Executa o processo completo: buscar notícias de hoje e publicar no blog."""
    print("🚀 Iniciando TechNews Bot...")
    print("=" * 50)

    noticias = self.buscar_noticias_de_hoje()
    if not noticias:
        print("Nenhuma notícia de hoje para processar.")
        # Retorna 0 para permitir que chamadas programáticas saibam que nada foi criado
        return 0

    max_posts = int(os.getenv("ROBO_MAX_POSTS", "1"))
    processadas = 0

    for noticia in noticias:
        if processadas >= max_posts:
            break

        link_original = noticia.get("link")
        if self._post_com_link_ja_existe(link_original):
            print(f"⚠️ Notícia já existente no banco (link): {link_original}. Pulando...")
            continue

        if self._post_ja_existe(noticia["titulo"]):
            print(f"⚠️ Notícia já existente no banco (título): {noticia['titulo']}. Pulando...")
            continue

        dados = self.processar_com_ia(noticia)
        if not dados:
            print("⚠️ IA falhou para esta notícia. Encerrando execução para evitar estourar limites.")
            break

        post = self.criar_post_no_blog(dados, noticia)
        if post:
            processadas += 1

    print("=" * 50)
    print(f"🎉 PROCESSO CONCLUÍDO! Posts criados nesta execução: {processadas}")

    # Retornar quantidade criada para uso por schedulers, CLI e painel admin
    return processadas


def main():
    """Função principal para execução via linha de comando."""

    load_dotenv()

    rodar_robo_raw = (os.getenv("rodar_robo", "0") or "0").strip().lower()
    rodar_robo_ativo = rodar_robo_raw in {"1", "true", "yes", "sim"}

    if not rodar_robo_ativo:
        print("⚠️ Flag rodar_robo está desligada (rodar_robo != true/1). Robô NÃO será executado.")
        return 0

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("❌ GEMINI_API_KEY não definida. Configure no .env antes de rodar o robô.")
        return 0

    bot = TechNewsBot(api_key)
    created = bot.executar()
    return created or 0


if __name__ == "__main__":
    main()